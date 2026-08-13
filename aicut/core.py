"""AICut 核心纵向流水线（PoC 骨架）。

组件映射（见架构文档 §8）：

| 组件            | 函数              | 说明                                   |
| --------------- | ----------------- | -------------------------------------- |
| Source Registry | probe()           | ffprobe 元数据 + 头部哈希               |
| Proxy Builder   | make_proxy()      | 720p / 360p Proxy 与 16kHz WAV         |
| Shot Detector   | detect_shots()    | FFmpeg scene 检测转场                  |
| Contact Sheet   | make_contact_sheet() | 每 Shot 动态抽帧概览图              |
| Transcript      | import_transcript() | 标准化 segment/word 时间戳          |
| Media Index     | build_index()     | JSON 权威 + SQLite 查询缓存            |
| Director        | plan()            | Story Plan + 候选 Shot（确定性回退）   |
| Validator       | validate()        | 程序化校验，Error 阻断写入             |
| CapCut Adapter  | export()          | capcut-adapter.json + review.html      |

时间语义：一律秒、[start, end) 区间。Shot ID 稳定顺序编号 shot-00001。
"""

from __future__ import annotations


def probe(source: str) -> dict:
    """读取源视频元数据（时长、分辨率、帧率、编码）与头部哈希。

    原片只读：仅通过绝对路径读取头部 1 MiB 计算哈希。
    """
    raise NotImplementedError


def make_proxy(source: str, project_dir: str, config: dict) -> dict:
    """生成 proxy-720p.mp4、proxy-360p.mp4 与 speech-16k.wav。"""
    raise NotImplementedError


def detect_shots(proxy_360p: str, config: dict) -> list[dict]:
    """FFmpeg scene 检测转场，输出稳定 Shot 契约（id/start/end/duration）。"""
    raise NotImplementedError


def make_contact_sheet(source: str, shot: dict, output_dir: str) -> str:
    """每 Shot 一张动态抽帧概览图（帧数按时长 1–9 变化）。"""
    raise NotImplementedError


def import_transcript(wav: str, config: dict) -> dict:
    """Whisper/whisper.cpp 转录，标准化 segment/word 时间戳。"""
    raise NotImplementedError


def build_index(project_dir: str, source_meta: dict, shots: list[dict],
                transcript: dict, visual: list[dict] | None = None) -> dict:
    """合并为统一 Media Index（JSON 权威 + SQLite 缓存）。"""
    raise NotImplementedError


def plan(media_index: dict, goal: str, target_duration: float, config: dict) -> dict:
    """确定性回退 Director：按语音/质量分/有效时长排序，输出 Story Plan 与 Timeline IR。"""
    raise NotImplementedError


def validate(timeline: dict, media_index: dict, config: dict) -> dict:
    """程序化校验 Timeline IR，输出 Validation Report（Error 阻断 / Warning 提示）。"""
    raise NotImplementedError


def export(timeline: dict, media_index: dict, project_dir: str) -> dict:
    """生成 capcut-adapter.json 与 review.html。"""
    raise NotImplementedError
