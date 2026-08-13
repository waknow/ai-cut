"""AICut CLI —— init/ingest/index/plan/validate/export/run。

所有命令均可重复执行；每个阶段写出独立文件，中断可从最后成功阶段继续。
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from aicut import __version__


def _not_implemented(command: str) -> None:
    raise NotImplementedError(f"命令 `{command}` 尚未实现（当前为目录骨架阶段）")


def cmd_init(args: argparse.Namespace) -> int:
    """初始化项目目录与策略（写入 project.json，source_immutable=true）。"""
    _not_implemented("init")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """探测、Proxy、音频、Shot、Contact Sheet、初始索引。"""
    _not_implemented("ingest")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """合并 transcript 与 Shot，重建 Media Index JSON/SQLite。"""
    _not_implemented("index")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """生成 Story Plan 与 Timeline IR。"""
    _not_implemented("plan")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """生成验证报告。"""
    _not_implemented("validate")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """生成 CapCut 适配载荷与 Review HTML。"""
    _not_implemented("export")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """串行执行完整 PoC 流水线。"""
    _not_implemented("run")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aicut",
        description="AI 视频剪辑流水线：素材理解、故事编排、时间线生成与剪映导入。",
    )
    parser.add_argument("--version", action="version", version=f"aicut {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="初始化项目目录和策略")
    p_init.add_argument("project", help="项目目录路径")
    p_init.set_defaults(func=cmd_init)

    p_ingest = sub.add_parser("ingest", help="探测、Proxy、音频、Shot、Contact Sheet、初始索引")
    p_ingest.add_argument("project", help="项目目录路径")
    p_ingest.add_argument("source", help="原始视频绝对路径")
    p_ingest.set_defaults(func=cmd_ingest)

    p_index = sub.add_parser("index", help="合并 transcript 与 Shot，重建 JSON/SQLite")
    p_index.add_argument("project", help="项目目录路径")
    p_index.set_defaults(func=cmd_index)

    p_plan = sub.add_parser("plan", help="生成 Story Plan 与 Timeline IR")
    p_plan.add_argument("project", help="项目目录路径")
    p_plan.add_argument("--goal", required=True, help="用户目标，如：剪成 60 秒旅行回顾")
    p_plan.add_argument("--target", type=float, required=True, help="目标时长（秒）")
    p_plan.set_defaults(func=cmd_plan)

    p_validate = sub.add_parser("validate", help="生成验证报告")
    p_validate.add_argument("project", help="项目目录路径")
    p_validate.set_defaults(func=cmd_validate)

    p_export = sub.add_parser("export", help="生成 CapCut 适配载荷和 Review HTML")
    p_export.add_argument("project", help="项目目录路径")
    p_export.set_defaults(func=cmd_export)

    p_run = sub.add_parser("run", help="串行执行完整 PoC")
    p_run.add_argument("project", help="项目目录路径")
    p_run.add_argument("source", help="原始视频绝对路径")
    p_run.add_argument("--goal", required=True, help="用户目标")
    p_run.add_argument("--target", type=float, required=True, help="目标时长（秒）")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NotImplementedError as exc:
        print(f"aicut: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
