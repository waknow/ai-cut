# 契约文档

本文件为规划占位。当前稳定文件契约（均带 `schema_version`）：

| 契约 | 路径 | 说明 |
| --- | --- | --- |
| 项目文件 | `project.json` | `schema 1.1`，`source_immutable=true`，`sources[]` 素材注册表（稳定 ID `s0001`…） |
| 素材元数据 | `media/sources/<id>.json` | 每素材一份 ffprobe 元数据 + 头部哈希（原 1.0 的 `media/source.json` 已废弃） |
| Shot 列表 | `analysis/shots.json` | `id/start/end/duration`，稳定编号 `shot-00001` |
| Transcript | `analysis/transcript.json` | segment/word 级源时间戳 |
| Media Index | `analysis/media-index.json` + `.sqlite` | 统一证据库，JSON 权威 |
| Story Plan | `edit/story-plan.json` | Beat 结构与候选 Shot 及理由 |
| Timeline IR | `edit/timeline.json` | NLE 无关剪辑决策，`[start, end)` 秒 |
| Validation Report | `edit/validation.json` | Error 阻断 / Warning 提示 |
| CapCut 适配 | `export/capcut-adapter.json` + `review.html` | 稳定 Adapter Contract |

## 素材接入（ingest）产物

多素材模型：每个素材注册为稳定 ID `s0001`、`s0002`…（按注册顺序），产物按 ID 命名互不覆盖：

```text
media/sources/s0001.json     # 素材元数据（probe 输出）
proxy/s0001-360p.mp4         # 粗分析代理（360p）
proxy/s0001-720p.mp4         # 人工预览代理（720p）
audio/s0001-16k.wav          # 16kHz 单声道语音
```

`ingest PROJECT [SOURCE]`：SOURCE 省略时自动扫描 `media/` 目录；新素材追加注册，
已登记素材（路径+头部哈希一致）幂等跳过，同路径哈希变化报错（素材被替换）。

## 分析阶段（ingest 自动执行）产物

```text
analysis/shots.json                    # Shot 契约：{id: shot-00001, source_id, start, end, duration}
analysis/contact-sheets/shot-00001.jpg # 每 Shot 一张动态抽帧概览图（帧宽 320，≤3 列，含源时间戳）
analysis/media-index.json              # Media Index：sources[] + shots[]（JSON 权威）
```

Shot 规则：scene 阈值 0.32（360p Proxy）；忽略首尾 0.25s 伪切点；最短 0.15s；
超 20s 强制分段；Contact Sheet 抽帧数 <1.5s→1 / 1.5–4→3 / 4–8→4 / 8–15→6 / ≥15→9。
分析为增量：已分析素材跳过，新增素材只分析自身。

契约示例与规则详见权威文档 §4.5 / §4.8 / §4.9。修改契约必须同步升级 `schema_version` 并迁移旧数据。
