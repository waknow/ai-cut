"""ingest 阶段测试：init_project / probe / make_proxy / ingest（多素材、增量、自动扫描）。

覆盖架构文档 §4.1 素材接入、§8 组件映射（Source Registry / Proxy Builder）
与生产版演进方向（素材库、多文件项目）。
"""

import json
import os
import subprocess
import tempfile
import unittest

from aicut import core


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def make_test_video(path, duration=8, size="1280x720", rate=30, with_audio=True):
    """用 ffmpeg 合成测试视频（testsrc2 彩条 + 可选正弦音）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           f"testsrc2=duration={duration}:size={size}:rate={rate}"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += [path]
    run(cmd)


def _probe_height(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=height", "-of", "csv=p=0", path],
        check=True, capture_output=True, text=True)
    return int(out.stdout.strip())


def _probe_audio(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0", path],
        check=True, capture_output=True, text=True)
    sr, ch = out.stdout.strip().split(",")
    return int(sr), int(ch)


class IngestTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    # ---- probe ----

    def test_probe_returns_source_metadata(self):
        video = os.path.join(self.root, "src.mp4")
        make_test_video(video, duration=8, size="1280x720")
        meta = core.probe(video)
        src = meta["source"]
        self.assertEqual(meta["schema_version"], "1.1")
        self.assertEqual(src["path"], os.path.abspath(video))
        self.assertAlmostEqual(src["duration"], 8.0, delta=0.5)
        self.assertEqual(src["width"], 1280)
        self.assertEqual(src["height"], 720)
        self.assertAlmostEqual(src["fps"], 30.0, delta=0.01)
        self.assertEqual(src["video_codec"], "h264")
        self.assertEqual(src["audio_codec"], "aac")
        self.assertEqual(len(src["head_sha256"]), 64)

    def test_probe_hash_changes_when_source_replaced(self):
        video = os.path.join(self.root, "src.mp4")
        make_test_video(video, duration=2, size="640x360")
        h1 = core.probe(video)["source"]["head_sha256"]
        make_test_video(video, duration=2, size="1280x720")
        h2 = core.probe(video)["source"]["head_sha256"]
        self.assertNotEqual(h1, h2)

    def test_probe_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            core.probe(os.path.join(self.root, "nope.mp4"))

    # ---- init ----

    def test_init_project_creates_structure(self):
        project = os.path.join(self.root, "demo")
        info = core.init_project(project)
        for sub in ("media", "proxy", "audio", "analysis", "edit", "export"):
            self.assertTrue(os.path.isdir(os.path.join(project, sub)), sub)
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["schema_version"], "1.1")
        self.assertTrue(data["source_immutable"])
        self.assertEqual(data["sources"], [])

    def test_init_project_is_idempotent(self):
        project = os.path.join(self.root, "demo")
        core.init_project(project)
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            first = f.read()
        core.init_project(project)
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            second = f.read()
        self.assertEqual(first, second)

    # ---- make_proxy ----

    def test_make_proxy_generates_proxies_and_audio(self):
        project = os.path.join(self.root, "demo")
        core.init_project(project)
        video = os.path.join(self.root, "src.mp4")
        make_test_video(video, duration=8, size="1280x720")
        out = core.make_proxy(video, project, "s0001", core.load_config())
        p360 = os.path.join(project, out["proxy_360p"])
        p720 = os.path.join(project, out["proxy_720p"])
        wav = os.path.join(project, out["speech_16k_wav"])
        self.assertTrue(os.path.isfile(p360))
        self.assertTrue(os.path.isfile(p720))
        self.assertTrue(os.path.isfile(wav))
        self.assertEqual(os.path.basename(p360), "s0001-360p.mp4")
        self.assertEqual(os.path.basename(p720), "s0001-720p.mp4")
        self.assertEqual(os.path.basename(wav), "s0001-16k.wav")
        self.assertEqual(_probe_height(p360), 360)
        self.assertEqual(_probe_height(p720), 720)
        sr, ch = _probe_audio(wav)
        self.assertEqual(sr, 16000)
        self.assertEqual(ch, 1)

    def test_make_proxy_without_audio_creates_silent_wav(self):
        project = os.path.join(self.root, "demo")
        core.init_project(project)
        video = os.path.join(self.root, "silent.mp4")
        make_test_video(video, duration=4, size="640x360", with_audio=False)
        out = core.make_proxy(video, project, "s0001", core.load_config())
        wav = os.path.join(project, out["speech_16k_wav"])
        self.assertTrue(os.path.isfile(wav))
        sr, ch = _probe_audio(wav)
        self.assertEqual(sr, 16000)

    # ---- ingest：单素材 ----

    def test_ingest_single_source(self):
        project = os.path.join(self.root, "demo")
        video = os.path.join(self.root, "src.mp4")
        make_test_video(video, duration=8, size="1280x720")
        result = core.ingest(project, video)
        for rel in ("media/sources/s0001.json", "proxy/s0001-360p.mp4",
                    "proxy/s0001-720p.mp4", "audio/s0001-16k.wav"):
            self.assertTrue(os.path.isfile(os.path.join(project, rel)), rel)
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            proj = json.load(f)
        self.assertEqual(len(proj["sources"]), 1)
        self.assertEqual(proj["sources"][0]["path"], os.path.abspath(video))
        self.assertEqual(proj["sources"][0]["id"], "s0001")
        self.assertEqual(len(proj["sources"][0]["head_sha256"]), 64)
        self.assertEqual(result["sources"][0]["status"], "added")

    def test_ingest_detects_replaced_source(self):
        project = os.path.join(self.root, "demo")
        video = os.path.join(self.root, "src.mp4")
        make_test_video(video, duration=2, size="640x360")
        core.ingest(project, video)
        make_test_video(video, duration=4, size="640x360")
        with self.assertRaises(RuntimeError):
            core.ingest(project, video)

    def test_ingest_is_repeatable_for_same_source(self):
        project = os.path.join(self.root, "demo")
        video = os.path.join(self.root, "src.mp4")
        make_test_video(video, duration=6, size="640x360")
        core.ingest(project, video)
        result = core.ingest(project, video)  # 同素材重复执行，幂等
        self.assertEqual(result["sources"][0]["status"], "unchanged")
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            proj = json.load(f)
        self.assertEqual(len(proj["sources"]), 1)

    # ---- ingest：多素材增量 ----

    def test_ingest_incremental_multiple_sources(self):
        project = os.path.join(self.root, "demo")
        core.init_project(project)
        v1 = os.path.join(self.root, "a.mp4")
        v2 = os.path.join(self.root, "b.mp4")
        make_test_video(v1, duration=2, size="640x360")
        make_test_video(v2, duration=3, size="640x360")
        core.ingest(project, v1)
        result = core.ingest(project, v2)  # 第二个素材：追加而非报错
        self.assertEqual(result["sources"][0]["status"], "added")
        self.assertEqual(result["sources"][0]["id"], "s0002")
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            proj = json.load(f)
        self.assertEqual([s["id"] for s in proj["sources"]], ["s0001", "s0002"])
        # 两个素材的产物互不覆盖
        self.assertTrue(os.path.isfile(os.path.join(project, "proxy", "s0001-360p.mp4")))
        self.assertTrue(os.path.isfile(os.path.join(project, "proxy", "s0002-360p.mp4")))
        self.assertTrue(os.path.isfile(os.path.join(project, "audio", "s0001-16k.wav")))
        self.assertTrue(os.path.isfile(os.path.join(project, "audio", "s0002-16k.wav")))
        self.assertTrue(os.path.isfile(os.path.join(project, "media", "sources", "s0001.json")))
        self.assertTrue(os.path.isfile(os.path.join(project, "media", "sources", "s0002.json")))

    # ---- ingest：自动扫描 ----

    def test_ingest_auto_scans_media_dir(self):
        project = os.path.join(self.root, "demo")
        core.init_project(project)
        media = os.path.join(project, "media")
        v1 = os.path.join(media, "DJI_0031.MP4")
        v2 = os.path.join(media, "DJI_0033.MP4")
        make_test_video(v1, duration=2, size="640x360")
        make_test_video(v2, duration=2, size="640x360")
        with open(os.path.join(media, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("not a video")
        result = core.ingest(project)  # 不带 source：自动扫描 media/
        self.assertEqual(len(result["sources"]), 2)
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            proj = json.load(f)
        self.assertEqual(len(proj["sources"]), 2)
        self.assertEqual(proj["sources"][0]["path"], os.path.abspath(v1))
        self.assertEqual(proj["sources"][1]["path"], os.path.abspath(v2))

    def test_ingest_auto_scan_is_idempotent(self):
        project = os.path.join(self.root, "demo")
        core.init_project(project)
        v1 = os.path.join(project, "media", "a.mp4")
        make_test_video(v1, duration=2, size="640x360")
        core.ingest(project)
        result = core.ingest(project)  # 再次扫描：全部 unchanged
        self.assertEqual([s["status"] for s in result["sources"]], ["unchanged"])
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            proj = json.load(f)
        self.assertEqual(len(proj["sources"]), 1)

    def test_ingest_auto_scan_no_videos_raises(self):
        project = os.path.join(self.root, "demo")
        core.init_project(project)
        with self.assertRaises(RuntimeError):
            core.ingest(project)

    # ---- 1.0 → 1.1 迁移 ----

    def test_init_migrates_legacy_single_source_project(self):
        project = os.path.join(self.root, "demo")
        os.makedirs(os.path.join(project, "media"), exist_ok=True)
        video = os.path.join(self.root, "legacy.mp4")
        make_test_video(video, duration=2, size="640x360")
        legacy = {
            "schema_version": "1.0",
            "source_immutable": True,
            "source_path": os.path.abspath(video),
            "source_head_sha256": "x" * 64,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        with open(os.path.join(project, "project.json"), "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        core.init_project(project)
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            proj = json.load(f)
        self.assertEqual(proj["schema_version"], "1.1")
        self.assertEqual(len(proj["sources"]), 1)
        self.assertEqual(proj["sources"][0]["path"], os.path.abspath(video))
        self.assertNotIn("source_path", proj)


if __name__ == "__main__":
    unittest.main()
