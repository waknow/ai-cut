import unittest

import aicut
from aicut import core


class CoreSmokeTest(unittest.TestCase):
    """目录骨架阶段的冒烟测试：模块可导入、核心组件函数签名存在。"""

    def test_version(self):
        self.assertEqual(aicut.__version__, "0.1.0")

    def test_core_components_exist(self):
        for name in (
            "probe",
            "make_proxy",
            "detect_shots",
            "make_contact_sheet",
            "import_transcript",
            "build_index",
            "plan",
            "validate",
            "export",
        ):
            self.assertTrue(callable(getattr(core, name)), name)

    def test_core_functions_raise_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            core.probe("video.mp4")


if __name__ == "__main__":
    unittest.main()
