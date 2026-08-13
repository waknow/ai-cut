"""index 阶段测试：从磁盘产物重建 Media Index，合并 transcript（架构 §7 index 命令）。"""

import json
import os
import tempfile
import unittest
from unittest import mock

from aicut import core

from test_analysis import make_static_video


class IndexTest(unittest.TestCase):

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


    def test_index_rebuilds_media_index(self):
        project = os.path.join(self.root, "demo")
        video = os.path.join(self.root, "src.mp4")
        make_static_video(video, duration=5)
        core.ingest(project, video)
        index_file = os.path.join(project, "analysis", "media-index.json")
        self.assertTrue(os.path.isfile(index_file))
        # 删除后重建（模拟产物丢失）
        os.remove(index_file)
        index = core.build_index(project)
        self.assertEqual(index["schema_version"], "1.0")
        self.assertEqual(len(index["sources"]), 1)
        self.assertGreaterEqual(len(index["shots"]), 1)
        self.assertTrue(os.path.isfile(index_file))

    def test_index_merges_transcript(self):
        project = os.path.join(self.root, "demo")
        video = os.path.join(self.root, "src.mp4")
        make_static_video(video, duration=5)
        core.ingest(project, video)
        # 手动放置转录产物（whisper 就绪后由 import_transcript 生成）
        transcript = {
            "schema_version": "1.0",
            "sources": {
                "s0001": {
                    "segments": [{"start": 0.4, "end": 2.8, "text": "今天我们准备出发。"}],
                    "words": [{"start": 0.4, "end": 0.7, "word": "今天"}],
                }
            },
        }
        with open(os.path.join(project, "analysis", "transcript.json"), "w",
                  encoding="utf-8") as f:
            json.dump(transcript, f, ensure_ascii=False)
        index = core.build_index(project)
        self.assertIn("transcript", index)
        self.assertEqual(index["transcript"]["sources"]["s0001"]["segments"][0]["text"],
                         "今天我们准备出发。")

    def test_index_is_idempotent(self):
        project = os.path.join(self.root, "demo")
        video = os.path.join(self.root, "src.mp4")
        make_static_video(video, duration=5)
        core.ingest(project, video)
        a = core.build_index(project)
        b = core.build_index(project)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
