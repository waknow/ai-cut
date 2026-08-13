"""分析阶段测试：detect_shots / make_contact_sheet / build_index（架构 §4.2–4.5）。

规则覆盖：
- scene 阈值检测转场（360p Proxy）
- 忽略首尾 0.25s 伪切点、最短 Shot 0.15s、超 20s 强制分段
- Contact Sheet 动态抽帧（<1.5s→1 / 1.5–4→3 / 4–8→4 / 8–15→6 / ≥15→9）
- 抽样点位于时间分区中点
- ingest 后产出 shots.json / contact-sheets/ / media-index.json（增量分析）
"""

import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from aicut import core


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def make_static_video(path, duration=8, size="640x360", rate=30):
    """静态画面（testsrc2 固定内容）：无场景切换。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    run(["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"testsrc2=duration={duration}:size={size}:rate={rate}",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-an", path])


def make_cut_video(path, seg_duration=3, size="640x360", rate=30):
    """两段不同内容拼接（testsrc2 → 黑场），产生一个明显场景切换。"""
    workdir = os.path.dirname(path)
    seg1 = os.path.join(workdir, "_seg1.mp4")
    seg2 = os.path.join(workdir, "_seg2.mp4")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"testsrc2=duration={seg_duration}:size={size}:rate={rate}",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", seg1])
    run(["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"color=c=black:duration={seg_duration}:size={size}:rate={rate}",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", seg2])
    with open(os.path.join(workdir, "_list.txt"), "w", encoding="utf-8") as f:
        f.write(f"file '{seg1}'\nfile '{seg2}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i",
         os.path.join(workdir, "_list.txt"),
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", path])


class ShotDetectionTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.config = core.load_config()

    def test_static_video_yields_single_shot(self):
        video = os.path.join(self.root, "static.mp4")
        make_static_video(video, duration=8)
        proxy = os.path.join(self.root, "static-360p.mp4")
        core._run(["ffmpeg", "-y", "-i", video, "-vf", "scale=-2:360",
                   "-c:v", "libx264", "-preset", "veryfast", "-an", proxy],
                  "生成测试 proxy")
        shots = core.detect_shots(proxy, self.config, source_id="s0001",
                                  duration=8.0)
        self.assertEqual(len(shots), 1)
        shot = shots[0]
        self.assertEqual(shot["source_id"], "s0001")
        self.assertTrue(shot["id"].startswith("shot-"))
        self.assertAlmostEqual(shot["start"], 0.0, delta=0.1)
        self.assertAlmostEqual(shot["end"], 8.0, delta=0.5)
        self.assertAlmostEqual(shot["duration"], shot["end"] - shot["start"], delta=0.01)

    def test_cut_video_yields_multiple_shots(self):
        video = os.path.join(self.root, "cut.mp4")
        make_cut_video(video, seg_duration=3)
        proxy = os.path.join(self.root, "cut-360p.mp4")
        core._run(["ffmpeg", "-y", "-i", video, "-vf", "scale=-2:360",
                   "-c:v", "libx264", "-preset", "veryfast", "-an", proxy],
                  "生成测试 proxy")
        shots = core.detect_shots(proxy, self.config, source_id="s0001",
                                  duration=6.0)
        self.assertGreaterEqual(len(shots), 2)
        # 切点应在拼接处（~3s）附近：存在一个 shot 边界在 2–4s 之间
        boundaries = [s["start"] for s in shots[1:]]
        self.assertTrue(any(2.0 <= b <= 4.0 for b in boundaries),
                        f"未在拼接处检出切点: {boundaries}")

    def test_long_shot_is_split_at_max_seconds(self):
        video = os.path.join(self.root, "long.mp4")
        make_static_video(video, duration=25)
        proxy = os.path.join(self.root, "long-360p.mp4")
        core._run(["ffmpeg", "-y", "-i", video, "-vf", "scale=-2:360",
                   "-c:v", "libx264", "-preset", "veryfast", "-an", proxy],
                  "生成测试 proxy")
        shots = core.detect_shots(proxy, self.config, source_id="s0001",
                                  duration=25.0)
        self.assertGreaterEqual(len(shots), 2)
        for s in shots:
            self.assertLessEqual(s["duration"], 20.01)

    # ---- 内部规则（单元测试） ----

    def test_frame_count_boundaries(self):
        cases = [(1.4, 1), (1.5, 3), (4.0, 4), (8.0, 6), (15.0, 9), (30.0, 9)]
        for duration, expected in cases:
            self.assertEqual(core._frame_count(duration), expected, duration)

    def test_sample_times_are_midpoints(self):
        times = core._sample_times(10.0, 20.0, 4)
        self.assertEqual(len(times), 4)
        self.assertAlmostEqual(times[0], 11.25)
        self.assertAlmostEqual(times[1], 13.75)
        self.assertAlmostEqual(times[2], 16.25)
        self.assertAlmostEqual(times[3], 18.75)
        for t in times:
            self.assertTrue(10.0 < t < 20.0)

    def test_clean_cuts_filters_edges_and_min_length(self):
        # 0.1 为边缘伪切点；5.1 与 5.0 间隔 < 0.15 应合并
        segs = core._clean_cuts([0.1, 5.0, 5.1, 12.0], duration=15.0)
        self.assertEqual(segs, [(0.0, 5.0), (5.0, 12.0), (12.0, 15.0)])

    def test_clean_cuts_drops_tiny_tail(self):
        segs = core._clean_cuts([], duration=15.05)
        self.assertEqual(segs, [(0.0, 15.05)])  # 无切点：整段保留


class ContactSheetTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _make_shot(self, start, end, shot_id="shot-00001"):
        return {"id": shot_id, "source_id": "s0001",
                "start": start, "end": end, "duration": end - start}

    def test_contact_sheet_created_with_timestamp(self):
        video = os.path.join(self.root, "src.mp4")
        make_static_video(video, duration=6)
        out_dir = os.path.join(self.root, "sheets")
        from PIL import Image
        # 短 shot（1 帧）：宽 = 320
        single = self._make_shot(0.5, 1.5)
        p1 = core.make_contact_sheet(video, single, out_dir)
        self.assertEqual(os.path.basename(p1), "shot-00001.jpg")
        self.assertTrue(os.path.isfile(p1))
        self.assertEqual(Image.open(p1).width, 320)
        # 4s shot（4 帧，3 列）：宽 = 3×320
        four = self._make_shot(1.0, 5.0, "shot-00002")
        p2 = core.make_contact_sheet(video, four, out_dir)
        self.assertEqual(Image.open(p2).width, 960)
        self.assertGreater(Image.open(p2).height, 0)

    def test_contact_sheet_frames_vary_by_duration(self):
        video = os.path.join(self.root, "src.mp4")
        make_static_video(video, duration=16)
        out_dir = os.path.join(self.root, "sheets")
        short = self._make_shot(0.0, 1.0)
        long = self._make_shot(0.0, 16.0, "shot-00002")
        p1 = core.make_contact_sheet(video, short, out_dir)
        p2 = core.make_contact_sheet(video, long, out_dir)
        from PIL import Image
        h1 = Image.open(p1).height
        h2 = Image.open(p2).height
        self.assertLess(h1, h2)  # 1 帧 < 9 帧


class IngestAnalysisTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        # 隔离外部感知依赖（whisper/ollama），由 test_perception.py 单独覆盖
        self._perception_patches = [
            mock.patch.object(core, "_ollama_available", return_value=False),
            mock.patch.object(core, "_whisper_available", return_value=False),
        ]
        for _p in self._perception_patches:
            _p.start()
            self.addCleanup(_p.stop)


    def test_ingest_produces_analysis_artifacts(self):
        project = os.path.join(self.root, "demo")
        video = os.path.join(self.root, "src.mp4")
        make_static_video(video, duration=6)
        core.ingest(project, video)
        self.assertTrue(os.path.isfile(os.path.join(project, "analysis", "shots.json")))
        with open(os.path.join(project, "analysis", "shots.json"), encoding="utf-8") as f:
            shots = json.load(f)
        self.assertGreaterEqual(len(shots["shots"]), 1)
        sheet = shots["shots"][0]["contact_sheet"]
        self.assertTrue(os.path.isfile(os.path.join(project, sheet)), sheet)
        self.assertTrue(os.path.isfile(os.path.join(project, "analysis", "media-index.json")))
        with open(os.path.join(project, "analysis", "media-index.json"), encoding="utf-8") as f:
            idx = json.load(f)
        self.assertEqual(idx["schema_version"], "1.0")
        self.assertEqual(len(idx["sources"]), 1)
        self.assertEqual(len(idx["shots"]), len(shots["shots"]))

    def test_ingest_analysis_incremental(self):
        project = os.path.join(self.root, "demo")
        v1 = os.path.join(self.root, "a.mp4")
        v2 = os.path.join(self.root, "b.mp4")
        make_static_video(v1, duration=4)
        make_static_video(v2, duration=5)
        core.ingest(project, v1)
        with open(os.path.join(project, "analysis", "shots.json"), encoding="utf-8") as f:
            before = json.load(f)
        ids_before = {s["id"] for s in before["shots"]}
        core.ingest(project, v2)  # 只应分析新素材
        with open(os.path.join(project, "analysis", "shots.json"), encoding="utf-8") as f:
            after = json.load(f)
        ids_after = {s["id"] for s in after["shots"]}
        self.assertLess(len(ids_before), len(ids_after))
        self.assertTrue(ids_before.issubset(ids_after))
        self.assertEqual({s["source_id"] for s in after["shots"]}, {"s0001", "s0002"})

    def test_ingest_analysis_idempotent(self):
        project = os.path.join(self.root, "demo")
        video = os.path.join(self.root, "src.mp4")
        make_static_video(video, duration=4)
        core.ingest(project, video)
        with open(os.path.join(project, "analysis", "shots.json"), encoding="utf-8") as f:
            first = json.load(f)
        core.ingest(project, video)
        with open(os.path.join(project, "analysis", "shots.json"), encoding="utf-8") as f:
            second = json.load(f)
        self.assertEqual(len(first["shots"]), len(second["shots"]))


if __name__ == "__main__":
    unittest.main()
