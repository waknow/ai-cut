# AICut

AI 视频剪辑流水线：把「理解原片、组织故事、选择镜头、生成时间线、导入剪映」拆成可独立验证的阶段，让 AI 完成约 80%–90% 的素材整理和初剪，人工完成最后 10%–20% 的节奏、审美、音乐、字幕与精修。

> 当前状态：**0.1 PoC**（已跑通的纵向切片）。目标平台：macOS（M1 Air 优先）、Linux。

## 核心原则

- **原片只读**：源视频仅通过绝对路径读取，中间文件全部写入项目目录，核心流程绝不覆盖、移动或重命名原片。
- **先索引后导演**：Director 不直接读原片，只查询结构化证据层 Media Index。
- **两阶段视觉分析**：一级用每 Shot 一张 Contact Sheet 做粗理解；只有被选中的候选 Shot 才进入二级密集抽帧精排，把昂贵推理集中在少量帧上。
- **稳定中间表示**：Media Index 与 Timeline IR 是带 `schema_version` 的文件契约，隔离模型、FFmpeg 与剪映版本变化。
- **程序化验证**：模型只负责描述、排序和叙事决策；时间范围、轨道冲突、素材边界、语音截断等由 Validator 确定性校验，Error 阻断写入，Warning 交人工决策。
- **剪映完成人工精修与导出**：核心系统输出稳定的 `capcut-adapter.json` 契约，剪映兼容性问题被隔离在 CapCutWriter 内。

## 流水线

```text
视频素材 → Media Index → Story Plan → Timeline IR → Validator → NLE Draft
```

| 阶段 | 职责 |
| --- | --- |
| Ingest | `ffprobe` 元数据、头部哈希、生成 720p / 360p Proxy 与 16kHz 单声道 WAV |
| Shot 切分 | FFmpeg scene 检测转场（生产版可换 PySceneDetect，保持 Shot 契约不变） |
| Contact Sheet | 每 Shot 一张动态抽帧概览图（帧数按时长 1–9 变化），只用于粗理解 |
| 理解 | Whisper/whisper.cpp 时间戳转录 + 本地 Qwen3-VL 读取 Contact Sheet，两条独立管线 |
| Media Index | 源信息、Shot、视觉描述、Transcript、质量分合并为统一证据库（JSON 权威 + SQLite 查询缓存） |
| Director | 把 Goal 转成叙事 Beat，再检索 Media Index 生成 Story Plan 与候选 Shot |
| 二级分析 | 对候选 Shot 按 2–4 fps 密集抽帧，检测动作/表情/失焦/晃动，输出精确 `source_in` / `source_out` |
| Timeline IR | NLE 无关的剪辑中间表示，`[start, end)` 秒级区间，不含剪映内部字段 |
| Validator | 程序化校验（见下表），通过后才允许写入 |
| CapCut Adapter | 版本固定的 Writer 调用 capcut-mate 生成真实剪映 Draft |

Validator 规则：`UNKNOWN_SHOT` / `SOURCE_BOUNDS` / `NON_POSITIVE_DURATION` / `TIMELINE_OVERLAP` 为 Error（阻断自动写入）；`LOW_QUALITY` / `SPEECH_CUT` / `REUSED_SHOT` / `TARGET_DURATION` 为 Warning。默认时长容差 `max(2s, 目标时长 × 8%)`。

## 当前实现边界

- ✅ 已实现：素材登记、Proxy、音频、Shot、Contact Sheet、Transcript（whisper.cpp）、视觉理解（ollama qwen3-vl）、Media Index、LLM Director（Goal 拆硬约束/软偏好 → 叙事 Beat → 程序化检索，可降级确定性回退）、Timeline、CapCut 适配契约。
- ⏳ 已定义未接通：二级密集分析（P4）、真实 capcut-mate Writer（P5）、Review UI（P6）。
- 感知层（whisper/ollama）**自动执行、增量、可降级**：任一模型不可用或调用失败时，跳过该模态并警告，Media Index 仍以另一模态继续构建；已分析的素材/Shot 不再重复处理。
- Director 默认走外部大模型（OpenAI 兼容端点，如 opencode-go 的 deepseek-v4-flash，见 `config.json` 的 `director` 段）：把 Goal 拆为硬约束/软偏好与叙事 Beat，程序按 Beat query 对视觉摘要+语音文本做中文匹配检索（质量分/语音加分/硬约束罚分），再让外部模型对每个 Beat 候选做语义重排并写理由；外部不可用时可回退本地 ollama（同 qwen2.5vl），再不可用回退确定性 Director（按有效时长排序，每 Shot 最多 8 秒），同一 Story Plan 契约。图片理解（Contact Sheet）始终走本地视觉模型。
- 当前 CapCut 输出是稳定适配契约，不是可直接由剪映打开的原生 Draft。

## 路线图

```mermaid
flowchart LR
    P1["P1 基础媒体流水线 ✅"] --> P2["P2 Whisper + Qwen3-VL"]
    P2 --> P3["P3 LLM Director"]
    P3 --> P4["P4 Dense Reranker"]
    P4 --> P5["P5 capcut-mate Writer"]
    P5 --> P6["P6 Review UI + Eval"]
```

完整架构与实现说明见 [docs/AICut-architecture-and-implementation.md](docs/AICut-architecture-and-implementation.md)。

## 工程目录（规划）

```text
aicut/
├── aicut/
│   ├── __main__.py       # python -m aicut 入口
│   ├── cli.py            # init/ingest/index/plan/validate/export/run
│   └── core.py           # PoC 纵向流水线实现
├── docs/
├── tests/
│   └── test_core.py
├── config.example.json   # 约定的默认参数
├── pyproject.toml
└── README.md
```

CLI 命令：`init` / `ingest` / `index` / `plan` / `validate` / `export` / `run`，全部可重复执行。

## 设计文档

- `docs/AICut-architecture-and-implementation.md` — 权威架构与实现说明（目标、分层、流程、契约、性能与可靠性设计、测试与验收、实施顺序）。

## 许可证

待定。
