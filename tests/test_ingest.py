"""ingest 阶段测试：init_project / probe / make_proxy / ingest。

覆盖架构文档 §4.1 素材接入与 §8 组件映射（Source Registry / Proxy Builder）。
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
        self.assertEqual(meta["schema_version"], "1.0")
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
        self.assertEqual(data["schema_version"], "1.0")
        self.assertTrue(data["source_immutable"])
        self.assertIsNone(data["source_path"])

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
        out = core.make_proxy(video, project, core.load_config())
        p360 = os.path.join(project, out["proxy_360p"])
        p720 = os.path.join(project, out["proxy_720p"])
        wav = os.path.join(project, out["speech_16k_wav"])
        self.assertTrue(os.path.isfile(p360))
        self.assertTrue(os.path.isfile(p720))
        self.assertTrue(os.path.isfile(wav))
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
        out = core.make_proxy(video, project, core.load_config())
        wav = os.path.join(project, out["speech_16k_wav"])
        self.assertTrue(os.path.isfile(wav))
        sr, ch = _probe_audio(wav)
        self.assertEqual(sr, 16000)

    # ---- ingest ----

    def test_ingest_end_to_end(self):
        project = os.path.join(self.root, "demo")
        video = os.path.join(self.root, "src.mp4")
        make_test_video(video, duration=8, size="1280x720")
        core.ingest(project, video)
        for rel in ("media/source.json", "proxy/proxy-360p.mp4",
                    "proxy/proxy-720p.mp4", "audio/speech-16k.wav"):
            self.assertTrue(os.path.isfile(os.path.join(project, rel)), rel)
        with open(os.path.join(project, "project.json"), encoding="utf-8") as f:
            proj = json.load(f)
        self.assertEqual(proj["source_path"], os.path.abspath(video))
        self.assertEqual(len(proj["source_head_sha256"]), 64)

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
        core.ingest(project, video)  # 同素材重复执行，幂等


if __name__ == "__main__":
    unittest.main()
