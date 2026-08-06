"""Embedding 编码服务 - 使用 Qwen3-Embedding-0.6B 模型做向量编码

Qwen3-Embedding-0.6B 是阿里通义千问官方出品的文本嵌入模型，
基于 Qwen3-0.6B 通过多阶段训练微调而来，输出 1024 维向量。
Embedding 取法：取模型最后一层 EOS token 的隐藏状态 + L2 归一化。
"""
import os
from typing import List
from loguru import logger

_model = None
_tokenizer = None
_device = None
_VECTOR_DIM = None

# 本地模型路径（优先加载）
_MODEL_LOCAL_PATH = r"D:\models\Qwen\Qwen3-Embedding-0___6B\models\qwen--Qwen3-Embedding-0.6B\snapshots\master"

# 若本地不存在，则从 HuggingFace Mirror 下载
_MODEL_HF_NAME = "Qwen/Qwen3-Embedding-0.6B"


def _load_model():
    """懒加载 Qwen3-Embedding 模型"""
    global _model, _tokenizer, _device, _VECTOR_DIM
    if _model is not None:
        return

    import torch
    from transformers import AutoModel, AutoTokenizer

    _device = "cuda" if torch.cuda.is_available() else "cpu"

    # 优先本地路径
    paths = []
    if os.path.isdir(_MODEL_LOCAL_PATH):
        paths.append(("本地路径", _MODEL_LOCAL_PATH))

    # 回退在线下载（使用国内镜像）
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    paths.append(("HuggingFace", _MODEL_HF_NAME))

    loaded = False
    for source, model_path in paths:
        try:
            logger.info(f"加载 Qwen3-Embedding 模型 (source={source}): {model_path} (device={_device})")
            _tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
            _model = AutoModel.from_pretrained(
                model_path,
                trust_remote_code=True,
                torch_dtype=torch.bfloat16 if _device == "cuda" else torch.float32,
            )
            _model.to(_device)
            _model.eval()
            _VECTOR_DIM = _model.config.hidden_size
            logger.info(f"Qwen3-Embedding 模型加载完成 (source={source}), 维度={_VECTOR_DIM}")
            loaded = True
            break
        except Exception as e:
            logger.warning(f"从 {source} 加载模型失败: {e}")
            _model = None
            _tokenizer = None
            continue

    if not loaded:
        raise RuntimeError("Qwen3-Embedding 模型加载失败")


def get_vector_dimension() -> int:
    """获取向量维度"""
    _load_model()
    return _VECTOR_DIM


def encode_text(text: str, max_length: int = 512) -> List[float]:
    """将文本编码为 1024 维向量

    Qwen3-Embedding 取法：
    1. tokenize 文本，末尾是 EOS token (<|endoftext|>)
    2. 取最后一层 EOS token 位置的 hidden state
    3. L2 归一化
    """
    import torch
    _load_model()

    inputs = _tokenizer(
        text,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=max_length,
        add_special_tokens=True,
    )
    inputs = {k: v.to(_device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = _model(**inputs)

    # 取 EOS token 位置的 hidden state
    last_hidden = outputs.last_hidden_state  # [1, seq_len, 1024]
    seq_lengths = inputs["attention_mask"].sum(dim=1) - 1  # EOS 位置
    batch_indices = torch.arange(last_hidden.size(0), device=_device)
    eos_embeddings = last_hidden[batch_indices, seq_lengths]  # [1, 1024]

    # L2 归一化
    eos_embeddings = torch.nn.functional.normalize(eos_embeddings, p=2, dim=1)

    return eos_embeddings[0].cpu().tolist()


def encode_texts(texts: List[str], max_length: int = 512) -> List[List[float]]:
    """批量编码"""
    _load_model()
    return [encode_text(t, max_length=max_length) for t in texts]
