"""P3 LLM Director 测试：Goal 拆解、Beat 检索、降级回退、契约保持。

覆盖：
- _direct_goal：JSON 契约、target_ratio 归一化、非法输出报错
- _match_score / _hard_constraint_penalty：语义匹配与硬约束
- _retrieve_shots：按 Beat 检索、理由与备选
- plan()：LLM 路径契约、无语义/无 ollama 时回退确定性、确定性
"""

import json
import unittest
from unittest import mock

from aicut import core


def make_index(shots_data, source_id="s0001", transcript_text=""):
    """构造带视觉/语音语义的 Media Index fixture。

    shots_data: [(id, start, end, duration, summary, tags, quality)]
    """
    shots = []
    visual = {"schema_version": "1.0", "shots": {}}
    segments = []
    cursor = 0.0
    for i, (sid, start, end, duration, summary, tags, quality) in enumerate(shots_data, 1):
        shot = {
            "id": sid,
            "source_id": source_id,
            "start": start,
            "end": end,
            "duration": duration,
            "contact_sheet": f"analysis/contact-sheets/{sid}.jpg",
        }
        shots.append(shot)
        visual["shots"][sid] = {
            "summary": summary,
            "people": [],
            "actions": [],
            "location": "",
            "quality": {"score": quality, "issues": []},
            "mood": "",
            "tags": tags,
        }
        if transcript_text:
            segments.append({"start": start, "end": end, "text": transcript_text})
        cursor = max(cursor, end)
    index = {
        "schema_version": "1.0",
        "sources": [{"path": "/tmp/v.mp4", "duration": cursor}],
        "shots": shots,
    }
    if segments:
        index["transcript"] = {"schema_version": "1.0", "sources": {
            source_id: {"segments": segments, "words": []}}}
    else:
        index["transcript"] = {"schema_version": "1.0", "sources": {
            source_id: {"segments": [], "words": []}}}
    index["visual"] = visual
    return index


def make_directed(beats_ratio=(0.2, 0.6, 0.2)):
    """构造 _direct_goal 的固定输出 fixture。"""
    names = ["开场·场地空镜", "发展·婚礼仪式", "收束·宾客欢聚"]
    queries = ["场地 布置 空镜", "婚礼 宣誓 仪式 戒指", "宾客 举杯 欢笑"]
    return {
        "hard_constraints": ["不使用模糊镜头", "必须包含婚礼环节"],
        "soft_preferences": ["节奏明快"],
        "beats": [
            {"id": f"beat-{i+1:02d}", "name": names[i], "intent": names[i],
             "query": queries[i], "target_ratio": beats_ratio[i],
             "target_seconds": 60.0 * beats_ratio[i]}
            for i in range(3)
        ],
    }


class MatchScoreTest(unittest.TestCase):

    def test_word_and_bigram_hits(self):
        # 整词命中 2 分 + 字符 bigram 命中 1 分
        self.assertGreater(core._match_score("婚礼 仪式", "婚礼现场 宣誓 仪式"), 0)
        self.assertEqual(core._match_score("婚礼", "婚礼"), 3.0)
        self.assertEqual(core._match_score("婚礼", "海边旅行"), 0.0)

    def test_bigram_partial(self):
        # 查询词以 bigram 形式出现在文本中（"婚礼现场" vs "婚礼现场布置"）
        self.assertGreater(core._match_score("婚礼现场", "婚礼现场布置"), 0)
        # 无关文本无命中
        self.assertEqual(core._match_score("婚礼现场", "海边日落"), 0.0)


class DirectGoalTest(unittest.TestCase):

    def _ollama_config(self):
        """无 director 配置 → _direct_goal 走本地 ollama 后端。"""
        cfg = core.load_config()
        cfg.pop("director", None)
        return cfg

    def _fake_resp(self, text):
        m = mock.Mock()
        m.json.return_value = {"response": text}
        m.raise_for_status = lambda: None
        return m

    def test_parses_goal_contract(self):
        fake = {
            "hard_constraints": ["不使用模糊镜头"],
            "soft_preferences": ["节奏明快"],
            "beats": [
                {"name": "开场", "intent": "建立氛围", "query": "场地 布置",
                 "target_ratio": 0.2},
                {"name": "高潮", "intent": "仪式", "query": "婚礼 宣誓",
                 "target_ratio": 0.5},
                {"name": "收束", "intent": "欢聚", "query": "宾客 举杯",
                 "target_ratio": 0.3},
            ],
        }
        with mock.patch("requests.post", return_value=self._fake_resp(json.dumps(fake, ensure_ascii=False))):
            directed = core._direct_goal("婚礼记录", 60.0, self._ollama_config())
        self.assertEqual(directed["hard_constraints"], ["不使用模糊镜头"])
        beats = directed["beats"]
        self.assertEqual(len(beats), 3)
        for b in beats:
            self.assertIn("id", b)
            self.assertIn("target_seconds", b)
        # target_seconds 按占比归一化（0.2/0.5/0.3 → 12/30/18）
        self.assertAlmostEqual(sum(b["target_seconds"] for b in beats), 60.0, delta=0.1)
        self.assertAlmostEqual(beats[1]["target_seconds"], 30.0, delta=0.1)

    def test_ratio_normalized_when_not_summing_to_one(self):
        fake = {"beats": [
            {"name": "a", "query": "x", "target_ratio": 1.0},
            {"name": "b", "query": "y", "target_ratio": 1.0},
        ]}
        with mock.patch("requests.post", return_value=self._fake_resp(json.dumps(fake))):
            directed = core._direct_goal("g", 30.0, self._ollama_config())
        seconds = [b["target_seconds"] for b in directed["beats"]]
        self.assertAlmostEqual(sum(seconds), 30.0, delta=0.1)
        self.assertAlmostEqual(seconds[0], seconds[1], delta=0.1)

    def test_missing_ratio_defaults_equal(self):
        fake = {"beats": [{"name": "a", "query": "x"}, {"name": "b", "query": "y"}]}
        with mock.patch("requests.post", return_value=self._fake_resp(json.dumps(fake))):
            directed = core._direct_goal("g", 20.0, self._ollama_config())
        self.assertAlmostEqual(directed["beats"][0]["target_seconds"], 10.0, delta=0.1)

    def test_invalid_json_raises(self):
        with mock.patch("requests.post", return_value=self._fake_resp("not json at all")):
            with self.assertRaises(RuntimeError):
                core._direct_goal("g", 10.0, self._ollama_config())

    def test_missing_beats_raises(self):
        with mock.patch("requests.post", return_value=self._fake_resp('{"hard_constraints": []}')):
            with self.assertRaises(RuntimeError):
                core._direct_goal("g", 10.0, self._ollama_config())

    def test_ollama_request_failure_raises(self):
        with mock.patch("requests.post", side_effect=RuntimeError("conn refused")):
            with self.assertRaises(RuntimeError):
                core._direct_goal("g", 10.0, self._ollama_config())


class HardConstraintTest(unittest.TestCase):

    def test_low_quality_penalized(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场 宣誓", ["婚礼"], 0.2),   # 低质量
            ("shot-00002", 10, 20, 10, "婚礼现场 宣誓", ["婚礼"], 0.9),
        ])
        p1 = core._hard_constraint_penalty(["不使用模糊镜头"], index["shots"][0], index)
        p2 = core._hard_constraint_penalty(["不使用模糊镜头"], index["shots"][1], index)
        self.assertGreater(p1, p2)

    def test_missing_required_term_penalized(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "海边旅行", [], 0.9),
            ("shot-00002", 10, 20, 10, "婚礼 宣誓 交换戒指", [], 0.9),
        ])
        p1 = core._hard_constraint_penalty(["必须包含婚礼环节"], index["shots"][0], index)
        p2 = core._hard_constraint_penalty(["必须包含婚礼环节"], index["shots"][1], index)
        self.assertGreater(p1, p2)


class RetrieveShotsTest(unittest.TestCase):

    def test_beat_query_selects_matching_shots(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场 宣誓 交换戒指", ["婚礼"], 0.9),
            ("shot-00002", 10, 20, 10, "海边日落 散步", ["风景"], 0.9),
        ])
        directed = make_directed()
        candidates = core._retrieve_shots(index, directed["beats"], directed, core.load_config())
        # 婚礼 beat 应优先选 shot-00001
        wedding = [c for c in candidates if c["beat_id"] == "beat-02"]
        self.assertTrue(wedding)
        self.assertEqual(wedding[0]["shot"]["id"], "shot-00001")
        self.assertIn("命中", wedding[0]["reason"])

    def test_alternatives_listed(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场", ["婚礼"], 0.9),
            ("shot-00002", 10, 20, 10, "婚礼 敬酒", ["婚礼"], 0.8),
            ("shot-00003", 20, 30, 10, "宾客 欢聚", ["宾客"], 0.9),
        ])
        directed = make_directed()
        candidates = core._retrieve_shots(index, directed["beats"], directed, core.load_config())
        for c in candidates:
            self.assertIn("alternatives", c)

    def test_no_semantic_match_falls_back_to_quality(self):
        # 全部零匹配：按质量兜底仍产生候选（reason 标注）
        index = make_index([
            ("shot-00001", 0, 10, 10, "纯色测试画面", [], 0.5),
            ("shot-00002", 10, 20, 10, "纯色测试画面", [], 0.9),
        ])
        directed = make_directed()
        candidates = core._retrieve_shots(index, directed["beats"], directed, core.load_config())
        self.assertTrue(candidates)


class PlanLlmPathTest(unittest.TestCase):

    def test_llm_path_keeps_contracts(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场 布置 空镜", ["场地"], 0.9),
            ("shot-00002", 10, 20, 10, "婚礼 宣誓 戒指", ["婚礼"], 0.9),
            ("shot-00003", 20, 30, 10, "宾客 举杯 欢笑", ["宾客"], 0.9),
        ], transcript_text="谢谢大家 今天 见证")
        directed = make_directed()
        with mock.patch.object(core, "_direct_goal", return_value=directed), \
                mock.patch.object(core, "_ollama_available", return_value=True), \
                mock.patch.object(core, "_rank_beat_candidates",
                                  side_effect=lambda b, c, m, d: c):
            result = core.plan(index, goal="60 秒婚礼记录", target_duration=60.0,
                               config=core.load_config())
        sp = result["story_plan"]
        self.assertEqual(sp["schema_version"], "1.0")
        self.assertEqual(sp["goal"], "60 秒婚礼记录")
        self.assertEqual(sp["target_duration"], 60.0)
        self.assertEqual(sp["hard_constraints"], directed["hard_constraints"])
        self.assertEqual(len(sp["beats"]), 3)
        self.assertGreaterEqual(len(sp["candidates"]), 1)
        for cand in sp["candidates"]:
            for key in ("shot_id", "source_id", "duration", "reason", "beat_id"):
                self.assertIn(key, cand)
        tl = result["timeline"]
        self.assertEqual(tl["schema_version"], "1.0")
        for clip in tl["clips"]:
            for key in ("id", "shot_id", "source_in", "source_out",
                        "timeline_in", "timeline_out", "track", "transition_out"):
                self.assertIn(key, clip)
            self.assertEqual(clip["track"], "V1")
        # 时间线无缝衔接
        cursor = 0.0
        for clip in tl["clips"]:
            self.assertAlmostEqual(clip["timeline_in"], cursor, delta=1e-6)
            cursor = clip["timeline_out"]
        self.assertAlmostEqual(tl["duration"], cursor, delta=1e-6)

    def test_llm_path_deterministic_with_mock(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场", ["婚礼"], 0.9),
            ("shot-00002", 10, 20, 10, "宾客", ["宾客"], 0.9),
        ])
        directed = make_directed()
        with mock.patch.object(core, "_direct_goal", return_value=directed), \
                mock.patch.object(core, "_ollama_available", return_value=True), \
                mock.patch.object(core, "_rank_beat_candidates",
                                  side_effect=lambda b, c, m, d: c):
            a = core.plan(index, goal="g", target_duration=30.0, config=core.load_config())
            b = core.plan(index, goal="g", target_duration=30.0, config=core.load_config())
        self.assertEqual(a["timeline"]["clips"], b["timeline"]["clips"])
        self.assertEqual(a["story_plan"]["candidates"], b["story_plan"]["candidates"])

    def test_no_semantics_falls_back(self):
        index = {"schema_version": "1.0", "sources": [], "shots": [
            {"id": "shot-00001", "source_id": "s0001", "start": 0.0, "end": 5.0,
             "duration": 5.0, "contact_sheet": "x.jpg"},
        ]}
        with mock.patch.object(core, "_direct_goal") as m:
            result = core.plan(index, goal="g", target_duration=10.0, config=core.load_config())
        m.assert_not_called()
        self.assertEqual(result["story_plan"]["schema_version"], "1.0")
        self.assertGreaterEqual(len(result["timeline"]["clips"]), 1)

    def test_ollama_unavailable_falls_back(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场", ["婚礼"], 0.9),
        ])
        with mock.patch.object(core, "_ollama_available", return_value=False), \
                mock.patch.object(core, "_direct_goal") as m:
            result = core.plan(index, goal="g", target_duration=10.0, config=core.load_config())
        m.assert_not_called()
        self.assertGreaterEqual(len(result["timeline"]["clips"]), 1)

    def test_direct_goal_failure_falls_back(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场", ["婚礼"], 0.9),
        ])
        with mock.patch.object(core, "_direct_goal", side_effect=RuntimeError("boom")), \
                mock.patch.object(core, "_ollama_available", return_value=True):
            result = core.plan(index, goal="g", target_duration=10.0, config=core.load_config())
        self.assertGreaterEqual(len(result["timeline"]["clips"]), 1)
        self.assertEqual(result["story_plan"]["schema_version"], "1.0")


class ExternalDirectorTest(unittest.TestCase):
    """外部大模型（OpenAI 兼容 /chat/completions）Director 后端。"""

    def _config(self):
        cfg = core.load_config()
        cfg["director"] = {
            "engine": "external",
            "base_url": "https://opencode.ai/zen/go/v1",
            "api_key": "sk-test-key",
            "model": "deepseek-v4-flash",
            "temperature": 0.3,
            "max_tokens": 8192,
        }
        return cfg

    def _mock_chat(self, content):
        m = mock.Mock()
        m.json.return_value = {"choices": [{"message": {"content": content}}]}
        m.raise_for_status = lambda: None
        return m

    def test_external_endpoint_and_parsing(self):
        fake = {"beats": [{"name": "开场", "query": "场地", "target_ratio": 1.0}]}
        with mock.patch("requests.post", return_value=self._mock_chat(json.dumps(fake, ensure_ascii=False))) as mp:
            directed = core._direct_goal("旅行", 30.0, self._config())
        # 请求格式：Bearer + /chat/completions + model + messages
        call = mp.call_args
        self.assertEqual(call.args[0], "https://opencode.ai/zen/go/v1/chat/completions")
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer sk-test-key")
        body = call.kwargs["json"]
        self.assertEqual(body["model"], "deepseek-v4-flash")
        self.assertIn("开场", body["messages"][0]["content"])
        self.assertEqual(directed["beats"][0]["target_seconds"], 30.0)

    def test_external_empty_content_raises(self):
        # 推理模型思考未结束时 content 为空 → RuntimeError（plan 层会降级）
        with mock.patch("requests.post", return_value=self._mock_chat("")):
            with self.assertRaises(RuntimeError):
                core._direct_goal("旅行", 30.0, self._config())

    def test_external_request_failure_raises(self):
        with mock.patch("requests.post", side_effect=RuntimeError("network down")):
            with self.assertRaises(RuntimeError):
                core._direct_goal("旅行", 30.0, self._config())

    def test_dispatch_to_external_when_configured(self):
        with mock.patch.object(core, "_direct_goal_external") as ext, \
                mock.patch.object(core, "_direct_goal_ollama") as oll:
            core._direct_goal("g", 10.0, self._config())
        ext.assert_called_once()
        oll.assert_not_called()

    def test_dispatch_to_ollama_when_not_configured(self):
        cfg = core.load_config()
        cfg.pop("director", None)
        with mock.patch.object(core, "_direct_goal_external") as ext, \
                mock.patch.object(core, "_direct_goal_ollama") as oll:
            core._direct_goal("g", 10.0, cfg)
        oll.assert_called_once()
        ext.assert_not_called()

    def test_plan_uses_external_director(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场", ["婚礼"], 0.9),
        ])
        directed = make_directed()
        with mock.patch.object(core, "_direct_goal", return_value=directed) as dg, \
                mock.patch.object(core, "_ollama_available", return_value=True), \
                mock.patch.object(core, "_rank_beat_candidates",
                                  side_effect=lambda b, c, m, d: c):
            result = core.plan(index, goal="g", target_duration=30.0, config=self._config())
        dg.assert_called_once()
        self.assertGreaterEqual(len(result["timeline"]["clips"]), 1)


class RankCandidatesTest(unittest.TestCase):
    """外部 LLM 对 Beat 候选的语义重排。"""

    def _config(self):
        cfg = core.load_config()
        cfg["director"] = {
            "engine": "external",
            "base_url": "https://opencode.ai/zen/go/v1",
            "api_key": "sk-test",
            "model": "deepseek-v4-flash",
            "rank": True,
        }
        return cfg

    def _chosen(self, index, shot_ids):
        by_id = {s["id"]: s for s in index["shots"]}
        out = []
        for sid in shot_ids:
            s = by_id[sid]
            out.append({"shot": s, "source_in": s["start"], "source_out": s["end"],
                        "use": s["duration"], "beat_id": "beat-01",
                        "reason": "程序化理由", "score": 1.0})
        return out

    def _mock_chat(self, ranking):
        m = mock.Mock()
        m.json.return_value = {"choices": [{"message": {
            "content": json.dumps({"ranking": ranking}, ensure_ascii=False)}}]}
        m.raise_for_status = lambda: None
        return m

    def test_reorder_and_reason(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场 宣誓", ["婚礼"], 0.9),
            ("shot-00002", 10, 20, 10, "宾客 举杯", ["宾客"], 0.9),
        ])
        beat = {"id": "beat-01", "name": "仪式", "intent": "仪式感", "query": "婚礼"}
        chosen = self._chosen(index, ["shot-00001", "shot-00002"])
        ranking = [
            {"shot_id": "shot-00002", "score": 9, "reason": "宾客举杯更有氛围"},
            {"shot_id": "shot-00001", "score": 7, "reason": "仪式宣誓镜头"},
        ]
        with mock.patch("requests.post", return_value=self._mock_chat(ranking)) as mp:
            out = core._rank_beat_candidates(beat, chosen, index, self._config()["director"])
        self.assertEqual([c["shot"]["id"] for c in out], ["shot-00002", "shot-00001"])
        self.assertEqual(out[0]["reason"], "宾客举杯更有氛围")
        # 请求包含节拍与候选摘要
        body = mp.call_args.kwargs["json"]
        self.assertIn("举杯", body["messages"][0]["content"])
        self.assertIn("仪式", body["messages"][0]["content"])

    def test_failure_keeps_original_order(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场", ["婚礼"], 0.9),
        ])
        beat = {"id": "beat-01", "name": "x", "intent": "x", "query": "x"}
        chosen = self._chosen(index, ["shot-00001"])
        with mock.patch("requests.post", side_effect=RuntimeError("net down")):
            out = core._rank_beat_candidates(beat, chosen, index, self._config()["director"])
        self.assertEqual(out, chosen)

    def test_ranking_invalid_json_keeps_order(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场", ["婚礼"], 0.9),
        ])
        beat = {"id": "beat-01", "name": "x", "intent": "x", "query": "x"}
        chosen = self._chosen(index, ["shot-00001"])
        m = mock.Mock()
        m.json.return_value = {"choices": [{"message": {"content": "garbage"}}]}
        m.raise_for_status = lambda: None
        with mock.patch("requests.post", return_value=m):
            out = core._rank_beat_candidates(beat, chosen, index, self._config()["director"])
        self.assertEqual(out, chosen)

    def test_retrieve_ranks_when_configured(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场", ["婚礼"], 0.9),
        ])
        directed = make_directed()
        cfg = self._config()
        with mock.patch.object(core, "_rank_beat_candidates",
                               side_effect=lambda b, c, m, d: c) as rk:
            cands = core._retrieve_shots(index, directed["beats"], directed, cfg, cfg["director"])
        self.assertGreater(rk.call_count, 0)
        self.assertTrue(cands)

    def test_retrieve_skips_ranking_when_not_configured(self):
        index = make_index([
            ("shot-00001", 0, 10, 10, "婚礼现场", ["婚礼"], 0.9),
        ])
        directed = make_directed()
        with mock.patch.object(core, "_rank_beat_candidates") as rk:
            cands = core._retrieve_shots(index, directed["beats"], directed, core.load_config())
        rk.assert_not_called()
        self.assertTrue(cands)


if __name__ == "__main__":
    unittest.main()
