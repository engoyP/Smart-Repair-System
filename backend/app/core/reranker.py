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
_TIMEOUT = 30.0          # 30 条候选批打分，CPU 上可能 1~3s
_COOLDOWN_SECS = 60.0    # 失败冷却期：期间不再尝试调用
_FAIL_THRESHOLD = 3      # 连续失败 N 次进入冷却期

_HTTP = httpx.Client(timeout=_TIMEOUT)
_fail_count = 0
_cooldown_until = 0.0


def _in_cooldown() -> bool:
    return time.time() < _cooldown_until


def rerank_scores(query: str, documents: List[str]) -> Optional[List[float]]:
    """对 (query, doc) 批量打分，返回与 documents 同序的 0~1 分数；失败返回 None"""
    global _fail_count, _cooldown_until
    if _in_cooldown():
        return None
    try:
        r = _HTTP.post(
            f"{_SERVER_URL}/v1/rerank",
            json={
                "model": settings.RERANKER_MODEL_NAME,
                "query": query,
                "documents": documents,
                "top_n": None,
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        results = r.json()["results"]
        _fail_count = 0
        # 服务端按分数降序返回；还原为 documents 同序
        scores = [0.0] * len(documents)
        for item in results:
            scores[item["index"]] = item["score"]
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
    documents = [
        f"{c.get('title', '')}\n{c.get('content', '')}"
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
