import unittest

import aicut
from aicut import core

# 尚未实现的组件（骨架占位，下一步填充）
UNIMPLEMENTED = (
    "detect_shots",
    "make_contact_sheet",
    "import_transcript",
    "build_index",
    "plan",
    "validate",
    "export",
)


class CoreSmokeTest(unittest.TestCase):
    """骨架冒烟测试：模块可导入、核心组件函数签名存在。"""

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

    def test_unimplemented_components_raise(self):
        for name in UNIMPLEMENTED:
            with self.assertRaises(NotImplementedError, msg=name):
                getattr(core, name)()


if __name__ == "__main__":
    unittest.main()
