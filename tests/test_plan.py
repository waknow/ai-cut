"""plan 阶段测试：确定性回退 Director（架构 §4.6–4.8）。

覆盖：
- Story Plan 契约（goal / target_duration / beats / candidates）
- Timeline IR 契约（clips：source_in/out、timeline_in/out、track）
- 每 Shot 最多取 8 秒；超长 Shot 取中部
- clip 不出 Shot 边界；时间线无缝衔接；时长接近目标
- 确定性：两次调用输出一致；素材不足时全部使用
"""

import unittest

from aicut import core


def make_index(durations, source_id="s0001"):
    """构造 Media Index fixture：每项一个 Shot，时长依次为 durations。"""
    shots = []
    cursor = 0.0
    for i, d in enumerate(durations, 1):
        shots.append({
            "id": f"shot-{i:05d}",
            "source_id": source_id,
            "start": round(cursor, 3),
            "end": round(cursor + d, 3),
            "duration": d,
            "contact_sheet": f"analysis/contact-sheets/shot-{i:05d}.jpg",
        })
        cursor += d
    return {
        "schema_version": "1.0",
        "sources": [{"path": "/tmp/v.mp4", "duration": cursor}],
        "shots": shots,
    }


class PlanTest(unittest.TestCase):

    def test_story_plan_contract(self):
        result = core.plan(make_index([5, 5, 5]), goal="60 秒旅行回顾", target_duration=12.0)
        sp = result["story_plan"]
        self.assertEqual(sp["schema_version"], "1.0")
        self.assertEqual(sp["goal"], "60 秒旅行回顾")
        self.assertEqual(sp["target_duration"], 12.0)
        self.assertGreaterEqual(len(sp["beats"]), 3)
        for beat in sp["beats"]:
            for key in ("id", "name", "intent", "target_seconds"):
                self.assertIn(key, beat)
        self.assertGreaterEqual(len(sp["candidates"]), 1)
        for cand in sp["candidates"]:
            for key in ("shot_id", "source_id", "duration", "reason", "beat_id"):
                self.assertIn(key, cand)

    def test_timeline_contract(self):
        result = core.plan(make_index([5, 5, 5]), goal="g", target_duration=12.0)
        tl = result["timeline"]
        self.assertEqual(tl["schema_version"], "1.0")
        self.assertEqual(tl["goal"], "g")
        self.assertEqual(tl["target_duration"], 12.0)
        self.assertIn("duration", tl)
        self.assertGreaterEqual(len(tl["clips"]), 1)
        for clip in tl["clips"]:
            for key in ("id", "shot_id", "source_in", "source_out",
                        "timeline_in", "timeline_out", "track", "transition_out"):
                self.assertIn(key, clip)
            self.assertEqual(clip["track"], "V1")

    def test_clips_within_shot_bounds(self):
        result = core.plan(make_index([3, 4, 5]), goal="g", target_duration=12.0)
        index = make_index([3, 4, 5])
        by_id = {s["id"]: s for s in index["shots"]}
        for clip in result["timeline"]["clips"]:
            shot = by_id[clip["shot_id"]]
            self.assertGreaterEqual(clip["source_in"], shot["start"] - 1e-6)
            self.assertLessEqual(clip["source_out"], shot["end"] + 1e-6)
            self.assertLess(clip["source_in"], clip["source_out"])

    def test_max_clip_seconds(self):
        # 单 Shot 100s：最多取 8s，且取中部
        result = core.plan(make_index([100.0]), goal="g", target_duration=10.0)
        clip = result["timeline"]["clips"][0]
        self.assertAlmostEqual(clip["source_out"] - clip["source_in"], 8.0, delta=0.01)
        mid_center = 50.0  # shot [0,100) 中部
        self.assertAlmostEqual((clip["source_in"] + clip["source_out"]) / 2, mid_center, delta=0.1)

    def test_duration_near_target(self):
        result = core.plan(make_index([10, 10, 10, 10]), goal="g", target_duration=20.0)
        tl = result["timeline"]
        self.assertGreaterEqual(tl["duration"], 20.0 - 1e-6)
        self.assertLess(tl["duration"], 20.0 + 8.0 + 1e-6)  # 不会远超目标

    def test_timeline_contiguous(self):
        result = core.plan(make_index([3, 4, 5]), goal="g", target_duration=20.0)
        cursor = 0.0
        for clip in result["timeline"]["clips"]:
            self.assertAlmostEqual(clip["timeline_in"], cursor, delta=1e-6)
            cursor = clip["timeline_out"]
        self.assertAlmostEqual(result["timeline"]["duration"], cursor, delta=1e-6)

    def test_deterministic(self):
        index = make_index([8, 2, 6, 4, 12])
        a = core.plan(index, goal="g", target_duration=18.0)
        b = core.plan(index, goal="g", target_duration=18.0)
        self.assertEqual(a["timeline"]["clips"], b["timeline"]["clips"])
        self.assertEqual(a["story_plan"]["candidates"], b["story_plan"]["candidates"])

    def test_insufficient_material_uses_all(self):
        result = core.plan(make_index([3, 4]), goal="g", target_duration=60.0)
        tl = result["timeline"]
        self.assertEqual(len(tl["clips"]), 2)
        self.assertAlmostEqual(tl["duration"], 7.0, delta=0.01)

    def test_no_shots_raises(self):
        with self.assertRaises(ValueError):
            core.plan(make_index([]), goal="g", target_duration=10.0)

    def test_target_duration_must_be_positive(self):
        with self.assertRaises(ValueError):
            core.plan(make_index([5]), goal="g", target_duration=0)

    def test_longer_shots_preferred(self):
        # 回退策略：有效时长降序 → 12s 的 Shot 优先于 2s 的
        result = core.plan(make_index([2, 12, 3]), goal="g", target_duration=10.0)
        first = result["timeline"]["clips"][0]
        self.assertEqual(first["shot_id"], "shot-00002")


if __name__ == "__main__":
    unittest.main()
