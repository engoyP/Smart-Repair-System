"""阈值标定脚本 - 统计 bge-m3 余弦分数分布，输出建议阈值

背景：召回模型从 Qwen3-Embedding-0.6B 换成 bge-m3 后，向量相似度的分数分布
随之改变，原先基于旧模型标定的 0.15/0.3/0.45/0.55 等阈值必须按新分布重新标定。

本脚本对一组代表性查询跑向量检索（score_threshold=-1 取全量），统计：
- 每条查询的命中数、min/max/P50/P90/P95
- 全部命中汇总的分数分布（P5/P50/P85/P95）
- 依据分位数给出建议阈值（粗筛 / 单路检索 / 去重候选 / 去重确认）

使用方式:
    cd backend
    python scripts/calibrate_thresholds.py                     # 全部代表性查询
    python scripts/calibrate_thresholds.py --query "注塑机料筒温度偏高"  # 指定单条
    python scripts/calibrate_thresholds.py --top-k 50          # 每条查询召回条数

前提条件:
    - 推理服务已启动（bge-m3 编码走 HTTP）：start_all.ps1 或 python -m app.core.embedding_server
    - Milvus 已启动，knowledge 集合已灌入 bge-m3 向量
"""
import sys
import os
import argparse

# 确保 backend 目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from app.core.config import settings
from app.core.vector_store import vector_store
from app.core.embeddings import encode_texts, is_server_available


def check_inference_server():
    """推理服务连通性检查（服务化后，向量脚本必须先启动推理服务）"""
    if not is_server_available():
        logger.error(f"推理服务不可用: {settings.EMBEDDING_SERVER_URL}")
        logger.error("请先启动推理服务：start_all.ps1 或 python -m app.core.embedding_server")
        sys.exit(1)


# 覆盖知识库全部设备类型的代表性维修问题
REPRESENTATIVE_QUERIES = [
    "注塑机料筒温度偏高报警处理",
    "注塑机锁模力不足制品飞边",
    "注塑机液压油温度过高",
    "数控机床主轴异响振动大",
    "数控机床伺服驱动器过流报警",
    "CNC加工尺寸超差X轴",
    "液压系统压力建立不起来",
    "液压缸爬行与抖动",
    "传送带跑偏调整方法",
    "空压机排气温度高报警停机",
    "变压器油中溶解气体乙炔超标",
    "三相异步电机绝缘电阻过低",
    "锅炉水位计假水位",
    "制冷系统制冷效果差",
    "工业机器人定位偏差过大",
]


def _percentile(sorted_vals, p):
    """p 分位数（0~100，线性插值）"""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def calibrate(queries, top_k):
    check_inference_server()
    logger.info(f"推理服务正常，开始标定 {len(queries)} 条查询（每条 top_k={top_k}）...")

    vectors = encode_texts(queries)
    per_query = []
    all_scores = []

    for q, vec in zip(queries, vectors):
        hits = vector_store.search(query_vector=vec, limit=top_k, score_threshold=-1.0)
        scores = sorted(h["score"] for h in hits)
        all_scores.extend(scores)
        per_query.append({
            "query": q,
            "count": len(scores),
            "min": scores[0] if scores else 0.0,
            "max": scores[-1] if scores else 0.0,
            "p50": _percentile(scores, 50),
            "p90": _percentile(scores, 90),
            "p95": _percentile(scores, 95),
        })
        logger.info(f"  [{q[:22]}...] 命中 {len(scores)} 条")

    all_sorted = sorted(all_scores)
    print("\n" + "=" * 80)
    print("bge-m3 余弦分数分布标定报告（集合: knowledge）")
    print("=" * 80)
    print(f"{'查询':<24}{'命中':>6}{'min':>8}{'P50':>8}{'P90':>8}{'P95':>8}{'max':>8}")
    print("-" * 80)
    for row in per_query:
        print(f"{row['query'][:22]:<24}{row['count']:>6}{row['min']:>8.3f}"
              f"{row['p50']:>8.3f}{row['p90']:>8.3f}{row['p95']:>8.3f}{row['max']:>8.3f}")

    agg = {
        "min": all_sorted[0],
        "max": all_sorted[-1],
        "p5": _percentile(all_sorted, 5),
        "p50": _percentile(all_sorted, 50),
        "p85": _percentile(all_sorted, 85),
        "p90": _percentile(all_sorted, 90),
        "p95": _percentile(all_sorted, 95),
    }
    print("-" * 80)
    print(f"{'汇总（全部命中）':<24}{len(all_sorted):>6}"
          f"{agg['min']:>8.3f}{agg['p50']:>8.3f}{agg['p90']:>8.3f}{agg['p95']:>8.3f}{agg['max']:>8.3f}")

    print("\n建议阈值（按分位数初拟，请结合实际检索效果微调后回填 .env）:")
    suggestions = [
        ("RETRIEVAL_COARSE_THRESHOLD（粗筛下限）", agg["p5"],
         "95% 的真实命中分数应高于此值，低于它基本是噪声"),
        ("RETRIEVAL_VECTOR_THRESHOLD（单路检索默认）", agg["p50"],
         "典型检索得分的中间水平，偏高会漏召回、偏低噪声多"),
        ("DEDUP_CANDIDATE_THRESHOLD（去重候选）", agg["p85"],
         "高相似才值得进入下一步 LLM 核对"),
        ("DEDUP_LLM_THRESHOLD（去重确认）", agg["p95"],
         "极高相似，基本可判重复"),
    ]
    for name, val, note in suggestions:
        print(f"  {name:<46} {val:>6.3f}   {note}")
    print("\n回填方式：修改 backend/.env 对应配置项（如 RETRIEVAL_COARSE_THRESHOLD=0.xx），重启后端生效。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="bge-m3 分数分布标定（换模型后回填阈值配置）")
    parser.add_argument("--query", default="",
                        help="指定单条查询（默认跑全部代表性查询）")
    parser.add_argument("--top-k", type=int, default=50,
                        help="每条查询召回条数（默认 50）")
    args = parser.parse_args()

    queries = [args.query] if args.query else REPRESENTATIVE_QUERIES
    calibrate(queries, args.top_k)
