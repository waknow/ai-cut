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
- **qwen3-vl**：`ollama pull qwen3-vl`（6.1GB，registry.ollama.ai 可达）。
  首次推理含模型加载，本机 16GB 内存 + 部分 GPU 卸载下单个请求约 3–5 分钟属正常。

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
