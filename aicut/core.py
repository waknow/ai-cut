"""AICut 核心纵向流水线（PoC）。

已实现（架构 §8 组件映射）：

| 组件            | 函数              | 说明                                   |
| --------------- | ----------------- | -------------------------------------- |
| Source Registry | probe()           | ffprobe 元数据 + 头部哈希               |
| Proxy Builder   | make_proxy()      | 720p / 360p Proxy 与 16kHz WAV         |
| 项目编排        | init_project()    | 目录结构 + project.json                |
| 组合入口        | ingest()          | init → probe → make_proxy              |

时间语义：一律秒、[start, end) 区间。Shot ID 稳定顺序编号 shot-00001。
原片只读：仅通过绝对路径读取头部 1 MiB 计算哈希，绝不覆盖/移动/重命名原片。
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
HEAD_HASH_BYTES = 1 << 20  # 读取原片头部 1 MiB 计算哈希
PROJECT_SUBDIRS = ("media", "proxy", "audio", "analysis", "edit", "export")

# 内置默认配置，与仓库根 config.example.json 保持同步
DEFAULT_CONFIG = {
    "proxy": {
        "coarse_height": 360,
        "review_height": 720,
        "scene_threshold": 0.32,
        "max_shot_seconds": 20,
    },
    "speech": {
        "sample_rate": 16000,
        "engine": "whisper.cpp",
        "word_timestamps": True,
    },
    "vision": {
        "engine": "ollama",
        "model": "qwen3-vl",
        "coarse_mode": "contact_sheet",
        "dense_candidate_fps": 3,
    },
    "validation": {
        "minimum_quality": 0.35,
        "target_duration_tolerance_ratio": 0.08,
        "target_duration_tolerance_seconds": 2,
    },
}


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------

def _write_json(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _run(cmd: list[str], task: str) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError(f"{task} 失败：未找到命令 {cmd[0]}（请确认已安装）")
    if proc.returncode != 0:
        raise RuntimeError(
            f"{task} 失败：{' '.join(cmd)}\n{proc.stderr.strip()}"
        )
    return proc


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_fraction(value) -> float:
    num, sep, den = str(value).partition("/")
    if not sep or not den:
        try:
            return float(num or 0)
        except ValueError:
            return 0.0
    try:
        return float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _head_sha256(path: str, size: int = HEAD_HASH_BYTES) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(size))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def load_config(config_path: str | None = None) -> dict:
    """加载配置。

    优先级：显式路径 > cwd/config.json（本地覆盖） > 仓库根 config.example.json > 内置默认。
    """
    candidates: list[str] = []
    if config_path:
        candidates.append(os.path.abspath(config_path))
    candidates.append(os.path.join(os.getcwd(), "config.json"))
    candidates.append(str(Path(__file__).resolve().parent.parent / "config.example.json"))
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return copy.deepcopy(DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# 阶段一：素材接入（架构 §4.1）
# ---------------------------------------------------------------------------

def probe(source: str) -> dict:
    """读取源视频元数据（时长、分辨率、帧率、编码）与头部哈希。

    原片只读：仅通过绝对路径读取，返回 media/source.json 契约。
    """
    source = os.path.abspath(source)
    if not os.path.isfile(source):
        raise FileNotFoundError(f"源视频不存在：{source}")
    proc = _run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,format_name",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
            "-of", "json", source,
        ],
        "ffprobe 探测源视频",
    )
    data = json.loads(proc.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "path": source,
            "duration": float(fmt.get("duration") or 0.0),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "fps": _parse_fraction(video.get("r_frame_rate", "0/1")),
            "video_codec": video.get("codec_name") or "",
            "audio_codec": audio.get("codec_name") or "",
            "head_sha256": _head_sha256(source),
        },
    }


def init_project(project_dir: str) -> dict:
    """初始化项目目录结构与 project.json（可重复执行，幂等）。"""
    project_dir = os.path.abspath(project_dir)
    for sub in PROJECT_SUBDIRS:
        os.makedirs(os.path.join(project_dir, sub), exist_ok=True)
    proj_file = os.path.join(project_dir, "project.json")
    if not os.path.isfile(proj_file):
        _write_json(proj_file, {
            "schema_version": SCHEMA_VERSION,
            "source_immutable": True,
            "source_path": None,
            "source_head_sha256": None,
            "created_at": _now_iso(),
        })
    return {
        "project_dir": project_dir,
        "directories": list(PROJECT_SUBDIRS),
        "project_file": proj_file,
    }


def _extract_audio(source: str, wav: str, sample_rate: int) -> bool:
    """提取 16kHz 单声道 WAV；源无音轨时返回 False。"""
    try:
        _run(
            ["ffmpeg", "-y", "-i", source, "-map", "0:a:0?", "-vn",
             "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", wav],
            "提取 16kHz 单声道音频",
        )
        return os.path.isfile(wav) and os.path.getsize(wav) > 0
    except RuntimeError:
        return False


def make_proxy(source: str, project_dir: str, config: dict) -> dict:
    """生成 proxy-720p.mp4、proxy-360p.mp4 与 speech-16k.wav。

    返回相对项目目录的路径字典。无音轨素材生成静音 WAV（时长等于源时长）。
    """
    source = os.path.abspath(source)
    project_dir = os.path.abspath(project_dir)
    proxy_cfg = config.get("proxy", {})
    coarse = proxy_cfg.get("coarse_height", 360)
    review = proxy_cfg.get("review_height", 720)
    sample_rate = config.get("speech", {}).get("sample_rate", 16000)

    proxy_dir = os.path.join(project_dir, "proxy")
    audio_dir = os.path.join(project_dir, "audio")
    os.makedirs(proxy_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)

    p360 = os.path.join(proxy_dir, "proxy-360p.mp4")
    p720 = os.path.join(proxy_dir, "proxy-720p.mp4")
    wav = os.path.join(audio_dir, "speech-16k.wav")

    _run(
        ["ffmpeg", "-y", "-i", source, "-map", "0:v:0",
         "-vf", f"scale=-2:{coarse}", "-an", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", p360],
        "生成 360p Proxy",
    )
    _run(
        ["ffmpeg", "-y", "-i", source, "-map", "0:v:0",
         "-vf", f"scale=-2:{review}", "-an", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", p720],
        "生成 720p Proxy",
    )
    if not _extract_audio(source, wav, sample_rate):
        duration = probe(source)["source"]["duration"]
        _run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl=mono",
             "-t", f"{duration:.3f}", "-c:a", "pcm_s16le", wav],
            "生成静音音频（源无音轨）",
        )

    return {
        "proxy_360p": os.path.relpath(p360, project_dir),
        "proxy_720p": os.path.relpath(p720, project_dir),
        "speech_16k_wav": os.path.relpath(wav, project_dir),
    }


def ingest(project_dir: str, source: str, config: dict | None = None) -> dict:
    """组合入口：init → probe → 登记 → make_proxy。

    可重复执行；检测到源素材被替换（头部哈希变化）时报错，保护既有分析产物。
    """
    config = config or load_config()
    init_project(project_dir)
    meta = probe(source)
    src = meta["source"]

    proj_file = os.path.join(project_dir, "project.json")
    proj = _read_json(proj_file, {}) or {}
    existing_hash = proj.get("source_head_sha256")
    if existing_hash and existing_hash != src["head_sha256"]:
        raise RuntimeError(
            "检测到源素材被替换（头部哈希变化）。原片只读："
            "请新建项目目录，或清理旧 project.json / proxy / analysis 后重新 ingest。"
        )
    proj.update({
        "source_path": src["path"],
        "source_head_sha256": src["head_sha256"],
        "ingested_at": _now_iso(),
    })
    _write_json(proj_file, proj)
    _write_json(os.path.join(project_dir, "media", "source.json"), meta)

    proxies = make_proxy(source, project_dir, config)
    return {
        "project_dir": project_dir,
        "project_file": proj_file,
        "source": src,
        "proxies": proxies,
    }


# ---------------------------------------------------------------------------
# 尚未实现的组件（下一步填充）
# ---------------------------------------------------------------------------

def detect_shots(proxy_360p: str | None = None, config: dict | None = None) -> list[dict]:
    """FFmpeg scene 检测转场，输出稳定 Shot 契约（id/start/end/duration）。"""
    raise NotImplementedError


def make_contact_sheet(source: str | None = None, shot: dict | None = None,
                       output_dir: str | None = None) -> str:
    """每 Shot 一张动态抽帧概览图（帧数按时长 1–9 变化）。"""
    raise NotImplementedError


def import_transcript(wav: str | None = None, config: dict | None = None) -> dict:
    """Whisper/whisper.cpp 转录，标准化 segment/word 时间戳。"""
    raise NotImplementedError


def build_index(project_dir: str | None = None, source_meta: dict | None = None,
                shots: list[dict] | None = None, transcript: dict | None = None,
                visual: list[dict] | None = None) -> dict:
    """合并为统一 Media Index（JSON 权威 + SQLite 缓存）。"""
    raise NotImplementedError


def plan(media_index: dict | None = None, goal: str = "", target_duration: float = 60.0,
         config: dict | None = None) -> dict:
    """确定性回退 Director：按语音/质量分/有效时长排序，输出 Story Plan 与 Timeline IR。"""
    raise NotImplementedError


def validate(timeline: dict | None = None, media_index: dict | None = None,
             config: dict | None = None) -> dict:
    """程序化校验 Timeline IR，输出 Validation Report（Error 阻断 / Warning 提示）。"""
    raise NotImplementedError


def export(timeline: dict | None = None, media_index: dict | None = None,
           project_dir: str | None = None) -> dict:
    """生成 capcut-adapter.json 与 review.html。"""
    raise NotImplementedError
