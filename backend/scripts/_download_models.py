"""临时脚本：下载 bge-m3 + Qwen3-Reranker-0.6B 到本地路径（重试 + 忽略无关文件）

用 snapshot_download 补全缺失文件（已下载的会被跳过）。bge-m3 仓库里的
.DS_Store（macOS 元数据，403）与 onnx 目录（FlagEmbedding 不需要）忽略。
"""
import os
import time

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from huggingface_hub import snapshot_download  # noqa: E402

TASKS = [
    {
        "repo": "BAAI/bge-m3",
        "local_dir": r"D:\models\BAAI\BAAI__bge-m3",
        "ignore": [".DS_Store", "**/.DS_Store", "onnx/**", "**/onnx/**"],
    },
    {
        "repo": "Qwen/Qwen3-Reranker-0.6B",
        "local_dir": r"D:\models\Qwen\Qwen3-Reranker-0___6B",
        "ignore": [".DS_Store", "**/.DS_Store"],
    },
]

for task in TASKS:
    for attempt in range(1, 6):
        try:
            print(f"[{task['repo']}] 尝试 {attempt}/5 ...", flush=True)
            snapshot_download(
                task["repo"],
                local_dir=task["local_dir"],
                ignore_patterns=task["ignore"],
                max_workers=4,
            )
            print(f"[{task['repo']}] 完成", flush=True)
            break
        except Exception as e:
            print(f"[{task['repo']}] 失败: {type(e).__name__}: {e}", flush=True)
            if attempt == 5:
                raise
            time.sleep(5)
