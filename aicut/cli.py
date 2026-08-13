"""AICut CLI —— init/ingest/index/plan/validate/export/run。

所有命令均可重复执行；每个阶段写出独立文件，中断可从最后成功阶段继续。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

from aicut import __version__
from aicut import core


def _not_implemented(command: str) -> None:
    raise NotImplementedError(f"命令 `{command}` 尚未实现（当前为目录骨架阶段）")


def cmd_init(args: argparse.Namespace) -> int:
    """初始化项目目录与策略（写入 project.json，source_immutable=true）。"""
    project = os.path.abspath(args.project)
    info = core.init_project(project)
    print(f"已初始化项目：{info['project_dir']}")
    print(f"  目录：{', '.join(info['directories'])}")
    print(f"  项目文件：{info['project_file']}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """探测、Proxy、音频（Shot、Contact Sheet 下一步实现）。"""
    project = os.path.abspath(args.project)
    source = os.path.abspath(args.source)
    result = core.ingest(project, source, core.load_config())
    src = result["source"]
    print(f"已接入素材：{src['path']}")
    print(f"  时长 {src['duration']:.1f}s · {src['width']}x{src['height']} · "
          f"{src['fps']:.2f}fps · {src['video_codec']} / {src['audio_codec'] or '无音轨'}")
    print(f"  头部哈希 {src['head_sha256'][:12]}…")
    for label, rel in (
        ("360p Proxy", result["proxies"]["proxy_360p"]),
        ("720p Proxy", result["proxies"]["proxy_720p"]),
        ("16kHz 音频", result["proxies"]["speech_16k_wav"]),
    ):
        print(f"  {label}: {os.path.join(project, rel)}")
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
    except RuntimeError as exc:
        print(f"aicut: 错误：{exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"aicut: 错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
