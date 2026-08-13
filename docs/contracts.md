# 契约文档

本文件为规划占位。当前稳定文件契约（均带 `schema_version`）：

| 契约 | 路径 | 说明 |
| --- | --- | --- |
| 项目文件 | `project.json` | `source_immutable=true`，记录原片路径与头部哈希 |
| Source 元数据 | `media/source.json` | ffprobe 元数据 + 头部哈希 |
| Shot 列表 | `analysis/shots.json` | `id/start/end/duration`，稳定编号 `shot-00001` |
| Transcript | `analysis/transcript.json` | segment/word 级源时间戳 |
| Media Index | `analysis/media-index.json` + `.sqlite` | 统一证据库，JSON 权威 |
| Story Plan | `edit/story-plan.json` | Beat 结构与候选 Shot 及理由 |
| Timeline IR | `edit/timeline.json` | NLE 无关剪辑决策，`[start, end)` 秒 |
| Validation Report | `edit/validation.json` | Error 阻断 / Warning 提示 |
| CapCut 适配 | `export/capcut-adapter.json` + `review.html` | 稳定 Adapter Contract |

契约示例与规则详见权威文档 §4.5 / §4.8 / §4.9。修改契约必须同步升级 `schema_version` 并迁移旧数据。
