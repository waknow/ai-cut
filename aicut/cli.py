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
    """素材接入：支持增量与自动扫描（SOURCE 省略时扫描项目 media/ 目录）。"""
    project = os.path.abspath(args.project)
    source = os.path.abspath(args.source) if args.source else None
    result = core.ingest(project, source, core.load_config())
    auto = "（自动扫描 media/）" if source is None else ""
    print(f"素材接入完成：{result['project_dir']}{auto}")
    for i, item in enumerate(result["sources"], 1):
        src = item["source"]
        mark = {"added": "新增", "unchanged": "已存在，跳过"}[item["status"]]
        print(f"  [{i}] {item['id']} · {os.path.basename(item['path'])} · {mark}")
        print(f"      时长 {src['duration']:.1f}s · {src['width']}x{src['height']} · "
              f"{src['fps']:.2f}fps · {src['video_codec']} / {src['audio_codec'] or '无音轨'}")
        if item["proxies"]:
            print(f"      360p: {os.path.join(project, item['proxies']['proxy_360p'])}")
            print(f"      720p: {os.path.join(project, item['proxies']['proxy_720p'])}")
            print(f"      音频: {os.path.join(project, item['proxies']['speech_16k_wav'])}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """从磁盘产物重建 Media Index（合并 transcript 与 Shot，JSON 权威）。"""
    project = os.path.abspath(args.project)
    if not os.path.isfile(os.path.join(project, "analysis", "shots.json")):
        print("aicut: 错误：未找到 analysis/shots.json，请先执行 ingest", file=sys.stderr)
        return 1
    index = core.build_index(project)
    out = os.path.join(project, "analysis", "media-index.json")
    print(f"Media Index 已重建：{out}")
    print(f"  sources: {len(index['sources'])} · shots: {len(index['shots'])} · "
          f"transcript: {'有' if 'transcript' in index else '无'}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """生成 Story Plan 与 Timeline IR。"""
    project = os.path.abspath(args.project)
    media_index = core._read_json(os.path.join(project, "analysis", "media-index.json"))
    if not media_index:
        print("aicut: 错误：未找到 analysis/media-index.json，请先执行 ingest", file=sys.stderr)
        return 1
    result = core.plan(media_index, goal=args.goal, target_duration=args.target,
                       config=core.load_config())
    for rel, obj in (("edit/story-plan.json", result["story_plan"]),
                     ("edit/timeline.json", result["timeline"])):
        core._write_json(os.path.join(project, rel), obj)
    tl = result["timeline"]
    sp = result["story_plan"]
    print(f"Story Plan 与 Timeline 已生成：{os.path.join(project, 'edit')}")
    print(f"  目标 {tl['target_duration']:.0f}s · 成片 {tl['duration']:.1f}s · "
          f"{len(tl['clips'])} 个片段")
    for beat in sp["beats"]:
        n = sum(1 for c in sp["candidates"] if c["beat_id"] == beat["id"])
        print(f"  {beat['id']} {beat['name']}：目标 {beat['target_seconds']:.0f}s · {n} 个片段")
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

    p_ingest = sub.add_parser("ingest", help="素材接入：探测、Proxy、音频（SOURCE 省略时自动扫描项目 media/）")
    p_ingest.add_argument("project", help="项目目录路径")
    p_ingest.add_argument("source", nargs="?", default=None,
                          help="原始视频路径（可选；省略时自动扫描项目 media/ 目录）")
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
