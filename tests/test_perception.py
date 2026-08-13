"""P2 感知层测试：import_transcript（whisper.cpp 解析）与 understand（qwen3-vl / ollama）。

外部工具调用全部 mock：验证契约解析、增量、降级与错误处理。
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from aicut import core


def fake_whisper_json():
    """构造 whisper.cpp -ojf 输出的最小样例。"""
    return {
        "systeminfo": "x",
        "model": {"type": "small"},
        "transcription": [
            {
                "offsets": {"from": 0, "to": 4000},
                "text": " 今天我们准备出发。",
                "tokens": [
                    {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}},
                    {"text": " 今天", "offsets": {"from": 400, "to": 900}},
                    {"text": " 我们", "offsets": {"from": 900, "to": 1500}},
                    {"text": "[_TT_]", "offsets": {"from": 0, "to": 0}},
                ],
            },
            {
                "offsets": {"from": 4000, "to": 8200},
                "text": " 目的地到了。",
                "tokens": [
                    {"text": " 目的地", "offsets": {"from": 4100, "to": 5600}},
                ],
            },
        ],
    }


class ImportTranscriptTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.config = core.load_config()
        self.config["speech"]["bin"] = "/tmp/whisper-cli"
        self.config["speech"]["model"] = "/tmp/model.bin"

    def _fake_run(self, cmd, task):
        """mock core._run：把假 whisper JSON 写到 -of 指定的输出文件。"""
        out_base = cmd[cmd.index("-of") + 1]
        with open(out_base + ".json", "w", encoding="utf-8") as f:
            json.dump(fake_whisper_json(), f)

    def test_import_transcript_parses_segments_and_words(self):
        wav = os.path.join(self.root, "s0001-16k.wav")
        open(wav, "wb").close()
        with mock.patch("os.path.isfile", return_value=True), \
                mock.patch.object(core, "_run", side_effect=self._fake_run):
            result = core.import_transcript(wav, self.config, source_id="s0001")
        self.assertEqual(result["schema_version"], "1.0")
        src = result["sources"]["s0001"]
        self.assertEqual(len(src["segments"]), 2)
        self.assertEqual(src["segments"][0]["start"], 0.0)
        self.assertEqual(src["segments"][0]["end"], 4.0)
        self.assertEqual(src["segments"][0]["text"], "今天我们准备出发。")
        # word 级时间戳，过滤特殊 token（[_BEG_] [_TT_]）
        self.assertEqual(len(src["words"]), 3)
        self.assertEqual(src["words"][0]["word"], "今天")
        self.assertEqual(src["words"][0]["start"], 0.4)
        self.assertEqual(src["words"][0]["end"], 0.9)

    def test_import_transcript_missing_bin_raises(self):
        wav = os.path.join(self.root, "a.wav")
        open(wav, "wb").close()
        self.config["speech"]["bin"] = "/nonexistent/whisper-cli"
        with self.assertRaises(RuntimeError):
            core.import_transcript(wav, self.config, source_id="s0001")

    def test_import_transcript_missing_model_raises(self):
        wav = os.path.join(self.root, "a.wav")
        open(wav, "wb").close()
        self.config["speech"]["model"] = "/nonexistent/model.bin"
        with self.assertRaises(RuntimeError):
            core.import_transcript(wav, self.config, source_id="s0001")


class UnderstandShotTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.sheet = os.path.join(self.root, "shot-00001.jpg")
        with open(self.sheet, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"0" * 100)  # 假 JPEG
        self.config = core.load_config()

    def test_understand_shot_returns_structured_result(self):
        fake_response = {
            "summary": "人物在门口整理背包",
            "people": ["背包客"],
            "actions": ["整理背包"],
            "location": "门口",
            "quality": {"score": 0.82, "issues": []},
            "mood": "期待",
            "tags": ["人物", "出发", "室外"],
        }
        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"response": json.dumps(fake_response, ensure_ascii=False)}
            mock_post.return_value.raise_for_status = lambda: None
            result = core.understand_shot(self.sheet, self.config)
        self.assertEqual(result["summary"], "人物在门口整理背包")
        self.assertEqual(result["quality"]["score"], 0.82)
        # 请求应包含图片 base64
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["model"], "qwen3-vl")
        self.assertTrue(payload["images"][0].startswith("/9j/"))  # JPEG base64 头

    def test_understand_shot_fills_defaults(self):
        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"response": '{"summary": "x"}'}
            mock_post.return_value.raise_for_status = lambda: None
            result = core.understand_shot(self.sheet, self.config)
        for key in ("people", "actions", "tags", "quality", "mood", "location"):
            self.assertIn(key, result)

    def test_understand_shot_invalid_json_raises(self):
        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"response": "not json"}
            mock_post.return_value.raise_for_status = lambda: None
            with self.assertRaises(RuntimeError):
                core.understand_shot(self.sheet, self.config)

    def test_understand_shot_network_error_raises(self):
        import requests
        with mock.patch("requests.post",
                        side_effect=requests.exceptions.ConnectionError("conn refused")):
            with self.assertRaises(RuntimeError):
                core.understand_shot(self.sheet, self.config)


class UnderstandIncrementalTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.project = os.path.join(self.root, "demo")
        os.makedirs(os.path.join(self.project, "analysis", "contact-sheets"), exist_ok=True)
        self.shots = {
            "schema_version": "1.0",
            "shots": [
                {"id": "shot-00001", "source_id": "s0001", "start": 0, "end": 4,
                 "duration": 4, "contact_sheet": "analysis/contact-sheets/shot-00001.jpg"},
                {"id": "shot-00002", "source_id": "s0001", "start": 4, "end": 8,
                 "duration": 4, "contact_sheet": "analysis/contact-sheets/shot-00002.jpg"},
            ],
        }
        with open(os.path.join(self.project, "analysis", "shots.json"), "w",
                  encoding="utf-8") as f:
            json.dump(self.shots, f)
        for sid in ("shot-00001", "shot-00002"):
            with open(os.path.join(self.project, "analysis", "contact-sheets", f"{sid}.jpg"),
                      "wb") as f:
                f.write(b"\xff\xd8\xff\xe0" + b"0" * 50)
        self.config = core.load_config()

    def test_understand_processes_only_missing_shots(self):
        with mock.patch.object(core, "understand_shot",
                               return_value={"summary": "s", "quality": {"score": 0.5}}) as m:
            result = core.understand(self.project, self.config)
        self.assertEqual(m.call_count, 2)
        self.assertEqual(len(result["shots"]), 2)
        # 第二次：全部已分析，不重复调用
        with mock.patch.object(core, "understand_shot") as m2:
            result2 = core.understand(self.project, self.config)
        self.assertEqual(m2.call_count, 0)
        self.assertEqual(len(result2["shots"]), 2)
        self.assertTrue(os.path.isfile(
            os.path.join(self.project, "analysis", "visual.json")))

    def test_understand_writes_visual_json(self):
        with mock.patch.object(core, "understand_shot",
                               return_value={"summary": "s", "quality": {"score": 0.5}}):
            core.understand(self.project, self.config)
        with open(os.path.join(self.project, "analysis", "visual.json"), encoding="utf-8") as f:
            visual = json.load(f)
        self.assertEqual(visual["schema_version"], "1.0")
        self.assertIn("shot-00001", visual["shots"])


class TranscribeMissingTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.project = os.path.join(self.root, "demo")
        os.makedirs(os.path.join(self.project, "audio"), exist_ok=True)
        proj = {"schema_version": "1.1", "source_immutable": True,
                "sources": [{"id": "s0001", "path": "/tmp/a.mp4"},
                            {"id": "s0002", "path": "/tmp/b.mp4"}]}
        with open(os.path.join(self.project, "project.json"), "w", encoding="utf-8") as f:
            json.dump(proj, f)
        for sid in ("s0001", "s0002"):
            with open(os.path.join(self.project, "audio", f"{sid}-16k.wav"), "wb") as f:
                f.write(b"RIFF" + b"0" * 50)
        self.config = core.load_config()

    def test_transcribe_missing_incremental(self):
        def fake_import(wav, config, source_id):
            return {"schema_version": "1.0",
                    "sources": {source_id: {"segments": [{"start": 0, "end": 1,
                                                           "text": "hi"}], "words": []}}}

        with mock.patch.object(core, "import_transcript", side_effect=fake_import) as m:
            core._transcribe_missing(self.project, self.config)
        self.assertEqual(m.call_count, 2)
        with open(os.path.join(self.project, "analysis", "transcript.json"),
                  encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("s0001", data["sources"])
        # 再跑：两个素材均已转录，不再调用
        with mock.patch.object(core, "import_transcript") as m2:
            core._transcribe_missing(self.project, self.config)
        self.assertEqual(m2.call_count, 0)

    def test_transcribe_unavailable_warns_and_continues(self):
        with mock.patch.object(core, "_whisper_available", return_value=False), \
                mock.patch.object(core, "import_transcript") as m:
            core._transcribe_missing(self.project, self.config)
        m.assert_not_called()


if __name__ == "__main__":
    unittest.main()
