# AGENTS.md — 给 AI 编码代理的仓库指南

本文件为在该仓库工作的 AI 代理（如 Codex、Claude Code、pi 等）提供项目背景、核心不变式与工作约定。权威架构说明见 `docs/AICut-architecture-and-implementation.md`，冲突时以该文档为准。

## 项目一句话

AICut 是面向约 30 分钟 2K 素材的 AI 视频剪辑流水线：`视频素材 → Media Index → Story Plan → Timeline IR → Validator → NLE Draft`，目标是 AI 完成初剪、人工精修，在 M1 Air 上可本地运行。

## 不可破坏的核心不变式

1. **原片只读**。源视频只通过绝对路径读取；所有中间产物写入项目目录；禁止覆盖、移动、重命名原片。导出前校验源文件头部哈希。
2. **Director 不读原片**。LLM/决策层只允许查询 Media Index；媒体处理由程序层完成。
3. **稳定中间表示**。Media Index、Story Plan、Timeline IR、Validation Report 都是带 `schema_version` 的文件契约。修改契约必须同步升级版本号并迁移旧数据。
4. **两阶段视觉分析**。一级 VLM 只读每 Shot 一张 Contact Sheet；二级密集抽帧只针对 Director 选中的少量候选 Shot。不得让 VLM 逐帧扫描全片。
5. **模型输出必须先解析为 JSON Schema**，再进入下一阶段。时间范围、轨道冲突、边界、语音截断由程序验证，不信任模型数字。
6. **Validator 是最后一道闸**。Error 阻断自动写入；Warning 交人工或 Director 二次决策。
7. **剪映隔离**。核心层不直接改剪映内部 JSON；通过 `capcut-adapter.json` 契约 + 版本固定的 CapCutWriter 对接 capcut-mate。

## 架构分层

| 层 | 内容 | 说明 |
| --- | --- | --- |
| L5 交互与编排 | CLI / Goal / 项目配置 | 入口 |
| L4 智能决策 | Director / Dense Reranker / Prompt | LLM 只做描述、排序、叙事决策 |
| L3 领域模型 | Media Index / Story Plan / Timeline IR / Validation Report | 文件契约，JSON 权威 + SQLite 缓存 |
| L2 媒体分析 | FFmpeg / Shot Detection / Contact Sheet / Whisper / Qwen3-VL | 全部程序化、可缓存 |
| L1 适配输出 | capcut-mate Adapter / Review HTML / 剪映 | 可替换 |

各层只通过文件契约交互；外部模型或工具升级时只换对应适配器。

## 工作约定

- **先跑测试再改**：`python -m unittest discover -s tests -v`（覆盖 Contact Sheet 抽帧边界、Timeline bounds 校验、合成视频端到端、多素材增量、感知层契约解析/增量/降级）。
- **感知层依赖（本机）**：whisper.cpp 在 `~/tools/whisper.cpp`（`build/bin/whisper-cli` + `models/ggml-small.bin`）；ollama 服务在 `127.0.0.1:11434`（模型 `qwen3-vl`）。路径在 `config.example.json` 的 `speech.bin/model` 与 `vision.host/model`。缺依赖时 ingest 自动降级警告，不阻断。
- **感知层测试隔离**：核心流水线测试 mock 掉 `_ollama_available`/`_whisper_available`，感知层自身契约/增量/降级测试在 `tests/test_perception.py`（外部调用全部 mock）。
- **可恢复执行**：每个阶段写独立文件，中断可从最后成功阶段继续；生产版需加 `stage-manifest.json`（输入哈希、配置哈希、工具版本、状态）。
- **缓存**：每个阶段按输入哈希 + 配置哈希生成缓存键，未变化时复用。Media Index 建成后，改 Goal 不重新分析原片。
- **新增阶段**：输出必须落在既有契约目录下（`analysis/`、`edit/`、`export/`），并写入 `stage-manifest.json`。
- **时间语义**：一律使用秒、`[start, end)` 区间。Shot ID 稳定顺序编号 `shot-00001`。

## 测试与验收要求

任何新功能必须补测试。生产验收关注：场景检测集（硬切/淡入淡出/长镜头/闪光）、中英混合语音、低照度/抖动/失焦/重复镜头、30 分钟 2K 素材的峰值内存/耗时/磁盘、Timeline JSON Schema 属性测试、剪映 Draft 回归、人工评分（故事完整度、精彩度、节奏、语音完整度、可用率）。

## 开发节奏（推荐顺序）

1. **P1 基础媒体流水线** — ✅ 已完成
2. **P2 感知层** — whisper.cpp 封装 + Ollama Qwen3-VL 强制 JSON 输出，自动填充 Media Index
3. **P3 LLM Director** — Goal 拆硬约束/软偏好，先生成 Story Plan 再检索
4. **P4 精剪** — 候选区间密集抽帧，入点/出点局部搜索
5. **P5 打通剪映** — 固定版本，实现素材导入/音视频轨/字幕/转场映射，写入前后校验 + 结构回读
6. **P6 质量闭环** — Review UI 从 Issue 跳时间点，人工改动入评测集

改动前如果对某个阶段的设计意图不确定，先读 `docs/AICut-architecture-and-implementation.md` 对应章节，不要凭猜测扩展契约。
