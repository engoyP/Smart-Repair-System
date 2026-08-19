"""重排客户端 - HTTP 调用统一推理服务的 /v1/rerank（Qwen3-Reranker-0.6B）

职责：对粗筛后的候选案例做模型精排。只排序、不过滤——过滤仍由
retrieval_flow 的向量相似度阈值 + 设备/关键词硬约束负责，避免阈值语义混乱。

降级：服务不可用时返回 None，调用方回退规则重排（weighted_rerank）；
连续失败进入冷却期（60s），期间直接返回 None，避免每次请求都打失败日志。
"""
import time
from typing import List, Optional

import httpx
from loguru import logger

from app.core.config import settings

_SERVER_URL = settings.EMBEDDING_SERVER_URL.rstrip("/")
_TIMEOUT = 60.0          # 30 条候选分块批打分，CPU 上单块 1~5s，总预算给足
_COOLDOWN_SECS = 60.0    # 失败冷却期：期间不再尝试调用
_FAIL_THRESHOLD = 3      # 连续失败 N 次进入冷却期

_DOC_CHAR_LIMIT = 500    # 单文档送打字符上限：cross-encoder 的判定信息集中在
                         # 标题+正文开头，截短既提速又防服务端注意力矩阵爆内存
_CHUNK_SIZE = 8          # 每次 HTTP 调用的文档数：分块控制服务端单批内存峰值

_HTTP = httpx.Client(timeout=_TIMEOUT)
_fail_count = 0
_cooldown_until = 0.0


def _in_cooldown() -> bool:
    return time.time() < _cooldown_until


def rerank_scores(query: str, documents: List[str]) -> Optional[List[float]]:
    """对 (query, doc) 批量打分，返回与 documents 同序的 0~1 分数；失败返回 None

    分块调用（每块 _CHUNK_SIZE 条）：30 条长文本一次全发会让服务端
    attention 矩阵达到数 GB 级，CPU 内存不足直接 500（实测 3.3~4.8GB 分配失败）。
    """
    global _fail_count, _cooldown_until
    if _in_cooldown():
        return None
    scores: List[float] = []
    try:
        for start in range(0, len(documents), _CHUNK_SIZE):
            chunk = documents[start: start + _CHUNK_SIZE]
            r = _HTTP.post(
                f"{_SERVER_URL}/v1/rerank",
                json={
                    "model": settings.RERANKER_MODEL_NAME,
                    "query": query,
                    "documents": chunk,
                    "top_n": None,
                },
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            results = r.json()["results"]
            # 服务端按分数降序返回；还原为 chunk 同序
            chunk_scores = [0.0] * len(chunk)
            for item in results:
                chunk_scores[item["index"]] = item["score"]
            scores.extend(chunk_scores)
        _fail_count = 0
        return scores
    except Exception as e:
        _fail_count += 1
        if _fail_count >= _FAIL_THRESHOLD:
            _cooldown_until = time.time() + _COOLDOWN_SECS
            logger.warning(f"Reranker 连续失败 {_fail_count} 次，进入冷却期 {_COOLDOWN_SECS}s: {e}")
        else:
            logger.warning(f"Reranker 调用失败（第 {_fail_count} 次）: {e}")
        return None


def rerank_cases(cases: List[dict], query: str) -> Optional[List[dict]]:
    """对候选案例列表做模型精排，写入 rerank_score 并按分数降序重排

    Args:
        cases: RRF 融合后的候选（含 title/content/error_code）
        query: 原始查询

    Returns:
        重排后的列表（分数写回 item["rerank_score"]）；失败返回 None（调用方回退规则重排）
    """
    if not cases:
        return cases
    # 送打分文本截短：判定信息集中在标题+正文开头，全量正文只会拖慢 CPU
    # 并推高服务端内存（attention 随序列长平方增长）
    documents = [
        f"{c.get('title', '')}\n{str(c.get('content', ''))[:_DOC_CHAR_LIMIT]}"
        + (f"\n错误码:{c.get('error_code')}" if c.get("error_code") else "")
        for c in cases
    ]
    scores = rerank_scores(query, documents)
    if scores is None:
        return None

    for c, s in zip(cases, scores):
        c["rerank_score"] = round(s, 4)
    cases.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
    return cases
