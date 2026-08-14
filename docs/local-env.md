# 本地环境初始化（Windows）

本机（`D:\Projects\ai-cut`）已按下列步骤初始化，供复现与排障参考。感知层依赖
（whisper.cpp + qwen3-vl）全部就绪，`init / ingest / index / plan` 已端到端验证。

## 解释器

系统 `python` 是 3.9（不满足 `pyproject.toml` 的 >=3.10），使用 Anaconda Python
3.12.7：

```bash
/c/Users/Jove/anaconda3/python.exe -m aicut ...        # 运行 CLI
/c/Users/Jove/anaconda3/python.exe -m unittest discover -s tests -v   # 跑测试
```

包已以 editable 方式安装（含 dev 依赖 pytest）：`pip install -e ".[dev]"`。

## 可执行文件与 PATH

- **ffmpeg / ffprobe**：`winget install Gyan.FFmpeg` 安装 9.0，另复制到
  `C:\Users\Jove\tools\bin\`，并已写入用户 PATH（重启终端生效）。
- **whisper-cli.exe**：`~/tools/whisper.cpp/build/bin/`（v1.9.2 预编译，含全部
  ggml*.dll，从 gh-proxy.com 下载 GitHub Release 解压）。
- 本会话（pi 的 bash 工具）每命令新开 shell 且不读 .bashrc，需要临时
  `export PATH="$PATH:/c/Users/Jove/tools/bin"`；终端新开窗口直接可用。

## 模型

- **whisper.cpp 模型**：`~/tools/whisper.cpp/models/ggml-small.bin`（487MB，f16）。
  本网络直连 huggingface.co / github.com 超时，走两条路：
  1. `small.pt` 从 Azure Edge（openaipublic.azureedge.net）下载 —— 该 CDN 可达且快；
  2. 用 whisper.cpp v1.9.2 的 `models/convert-pt-to-ggml.py` + conda 的 torch 转换
     （tokenizer 资源 `whisper/assets/multilingual.tiktoken`、`mel_filters.npz`
     从 jsdelivr 拉取，放在 `~/tools/whisper.cpp/repo/whisper/assets/`）。
  保留 `small.pt`（483MB）以防需要重转。
- **qwen2.5vl:3b**：`ollama pull qwen2.5vl:3b`（3.2GB），本机视觉模型。GTX 1660
  SUPER（4GB 显存）下 100% GPU 卸载，热启动约 2s/张，5 个 Shot 全量重分析约
  52s（qwen3-vl 6.1GB 只能部分卸载，单请求 3–5 分钟，已弃用但保留在 ollama 中，
  可用 `ollama rm qwen3-vl` 释放 6.1GB）。小模型常按 0–10 分制输出
  `quality.score`，`understand_shot` 已做程序化归一化到 0.0–1.0（不信任模型数字）。

## 本地配置

仓库根 `config.json`（已 gitignore）覆盖 `config.example.json` 的路径：

```json
"bin":   "C:/Users/Jove/tools/whisper.cpp/build/bin/whisper-cli.exe",
"model": "C:/Users/Jove/tools/whisper.cpp/models/ggml-small.bin",
"host":  "http://127.0.0.1:11434", "model": "qwen3-vl"
```

## 代码改动

- `aicut/core.py` `_run()`：`subprocess.run(..., text=True)` 在中文 Windows 默认按
  GBK 解码子进程输出会抛 UnicodeDecodeError（reader 线程），改为
  `encoding="utf-8", errors="replace"`。测试全绿（55/55）。
