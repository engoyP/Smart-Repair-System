"""RetrievalAssistantAgent - 知识检索助手 Agent（ReAct 循环）

功能：
- 向量语义检索 + BM25 关键词检索 + RRF 融合排序
- ReAct 循环：思考 → 行动 → 观察 → 判断 → (输出 or 继续)
- 结果不足时自动调用查询改写，重试检索
- scratchpad 记录完整推理链路
"""
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from app.core.config import settings
from app.agents.tools import RetrievalTools, rrf_merge, ToolResult


class AgentAction(str, Enum):
    VECTOR_SEARCH = "vector_search"
    BM25_SEARCH = "bm25_search"
    CONDITIONAL_QUERY = "conditional_query"
    GRAPH_QUERY = "graph_query"
    REWRITE_QUERY = "rewrite_query"
    FINISH = "finish"


@dataclass
class AgentStep:
    """ReAct 循环中的单步记录"""
    step: int
    thought: str = ""
    action: str = ""
    tool_input: dict = field(default_factory=dict)
    observation: str = ""


@dataclass
class RetrievalResult:
    """检索结果"""
    query: str
    results: List[Dict]
    strategies_used: List[str]
    rewrite_count: int = 0
    rewritten_queries: List[str] = field(default_factory=list)
    scratchpad: List[AgentStep] = field(default_factory=list)
    total_time_ms: float = 0.0


class RetrievalAssistantAgent:
    """
    检索助手 Agent - 自主选择检索策略，实现 ReAct 循环

    工作流程：
    1. 思考（Thought）: 分析用户查询，决定使用哪些工具
    2. 行动（Action）: 调用选定工具 (vector/bm25/conditional/graph)
    3. 观察（Observe）: 评估结果质量
    4. 判断（Judge）:
       - 结果满足要求 → 输出
       - 结果不足 → 调用 rewrite_query → 回到步骤 2
       - 达到最大迭代次数 → 强制输出当前最佳结果
    """

    MAX_ITERATIONS = 5
    MIN_RESULTS_FOR_QUALITY = 3
    MIN_SCORE_FOR_QUALITY = 0.6

    def __init__(self, tools: RetrievalTools):
        self.tools = tools
        self._llm: Optional[ChatOpenAI] = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.1,
                streaming=False,
            )
        return self._llm

    def search(self, query: str, device_type: Optional[str] = None,
               fault_code: Optional[str] = None, max_results: int = 10) -> RetrievalResult:
        """
        主入口：执行完整的 ReAct 检索流程

        Args:
            query: 用户自然语言查询
            device_type: 设备类型过滤（可选）
            fault_code: 故障码过滤（可选）
            max_results: 最大返回结果数

        Returns:
            包含检索结果和推理链路的 RetrievalResult
        """
        import time
        start_time = time.time()

        scratchpad: List[AgentStep] = []
        all_results: List[Dict] = []
        strategies_used: List[str] = []
        rewrite_count = 0
        rewritten_queries = [query]
        current_query = query

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            step = AgentStep(step=iteration)

            # === 1. 思考 ===
            thought = self._think(
                current_query=current_query,
                device_type=device_type,
                fault_code=fault_code,
                scratchpad=scratchpad,
                all_results=all_results,
                iteration=iteration,
            )
            step.thought = thought["reasoning"]
            step.action = thought["action"]

            logger.info(f"[Agent ReAct] 迭代 {iteration} | 思考: {thought['reasoning'][:80]}...")
            logger.info(f"[Agent ReAct] 迭代 {iteration} | 行动: {thought['action']}")

            # === 如果 LLM 判断已达到目标，输出 ===
            if thought["action"] == AgentAction.FINISH.value or thought.get("finish", False):
                step.observation = "Agent 判断检索结果已充分，终止搜索"
                scratchpad.append(step)
                logger.info(f"[Agent ReAct] Agent 决定完成，结果数: {len(all_results)}")
                break

            # === 2. 行动 ===
            if thought["action"] == AgentAction.REWRITE_QUERY.value:
                # 查询改写 —— 专门的重试路径
                rewrite_result = self.tools.rewrite_query(
                    original_query=current_query,
                    strategy=thought.get("rewrite_strategy", "expand_synonyms"),
                )
                step.tool_input = {"query": current_query}
                if rewrite_result.success and rewrite_result.data:
                    rewritten = rewrite_result.data
                    rewrite_count += 1
                    rewritten_queries.extend(rewritten)
                    # 对各改写结果分别执行混合检索
                    step.observation = f"查询改写成功，生成 {len(rewritten)} 个新查询: {rewritten}"
                    scratchpad.append(step)
                    for rq in rewritten:
                        current_query = rq
                        # 使用改写后的查询继续下一轮循环（执行向量+BM25）
                        break
                    continue
                else:
                    step.observation = f"查询改写失败: {rewrite_result.error}"
                    scratchpad.append(step)
                    break

            elif thought["action"] == AgentAction.VECTOR_SEARCH.value:
                result = self.tools.vector_search(
                    query=current_query,
                    top_k=thought.get("top_k", 10),
                    device_type=device_type,
                    fault_code=fault_code,
                    score_threshold=thought.get("score_threshold", 0.3),
                )
                step.tool_input = {"query": current_query, "method": "vector_search"}

            elif thought["action"] == AgentAction.BM25_SEARCH.value:
                result = self.tools.bm25_search(
                    query=current_query,
                    top_k=thought.get("top_k", 10),
                    device_type=device_type,
                    fault_code=fault_code,
                )
                step.tool_input = {"query": current_query, "method": "bm25_search"}

            elif thought["action"] == AgentAction.CONDITIONAL_QUERY.value:
                result = self.tools.conditional_query(
                    device_type=device_type,
                    fault_code=fault_code,
                    keyword=thought.get("keyword"),
                    top_k=thought.get("top_k", 20),
                )
                step.tool_input = {"device_type": device_type, "fault_code": fault_code}

            elif thought["action"] == AgentAction.GRAPH_QUERY.value:
                exclude_ids = [r.get("knowledge_id") for r in all_results if r.get("knowledge_id")]
                result = self.tools.graph_query(
                    device_type=device_type,
                    fault_code=fault_code,
                    exclude_ids=exclude_ids,
                    top_k=thought.get("top_k", 10),
                )
                step.tool_input = {"device_type": device_type, "fault_code": fault_code}

            else:
                step.observation = f"未知行动: {thought['action']}"
                scratchpad.append(step)
                break

            # === 3. 观察 ===
            if result.success:
                step.observation = f"检索到 {len(result.data)} 条结果"
                strategies_used.append(result.metadata.get("method", thought["action"]))
                # 加入到累计结果（去重）
                existing_ids = {r.get("knowledge_id") for r in all_results if r.get("knowledge_id")}
                for item in result.data:
                    kid = item.get("knowledge_id") or item.get("id")
                    if kid not in existing_ids:
                        existing_ids.add(kid)
                        all_results.append(item)
            else:
                step.observation = f"检索失败: {result.error}"

            scratchpad.append(step)

            # === 4. 判断 ===
            quality = self._evaluate_quality(all_results, iteration)
            if quality["sufficient"]:
                logger.info(f"[Agent ReAct] 结果质量达标，停止搜索: {quality['reason']}")
                break

        # === 收尾：RRF 融合排序 ===
        # 将不同来源的结果按 RRF 重新排序
        if len(all_results) > 0:
            # 按来源分组进行 RRF 融合
            vector_results = [r for r in all_results if r.get("score", 0) > 0 and "tsquery" not in str(r)]
            bm25_results = [r for r in all_results if "tsquery" in str(r.get("score", ""))]

            if len(strategies_used) >= 2:
                # 多路检索 → RRF 融合
                all_results = rrf_merge(
                    [all_results],  # 简化：全部结果一起 RRF
                    top_n=max_results
                )
            else:
                # 单路检索 → 按原始得分排序
                all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
                all_results = all_results[:max_results]

        total_time_ms = (time.time() - start_time) * 1000

        return RetrievalResult(
            query=query,
            results=all_results,
            strategies_used=list(set(strategies_used)),
            rewrite_count=rewrite_count,
            rewritten_queries=rewritten_queries,
            scratchpad=scratchpad,
            total_time_ms=round(total_time_ms, 1),
        )

    def _think(
        self,
        current_query: str,
        device_type: Optional[str],
        fault_code: Optional[str],
        scratchpad: List[AgentStep],
        all_results: List[Dict],
        iteration: int,
    ) -> dict:
        """
        LLM 驱动的思考步骤 —— 基于当前状态决定下一步行动

        返回格式: {"reasoning": str, "action": str, "top_k": int, ...}
        """
        # 构建 scratchpad 文本
        scratchpad_text = ""
        for s in scratchpad:
            scratchpad_text += f"""
步骤 {s.step}:
  思考: {s.thought}
  行动: {s.action}({json.dumps(s.tool_input, ensure_ascii=False)})
  观察: {s.observation}
"""

        results_summary = self._summarize_results(all_results)

        system_prompt = f"""你是一个设备维修知识检索助手的决策模块。你的任务是根据当前状态决定下一步检索策略。

## 可用工具：
1. **vector_search** - 向量语义检索：适合模糊/语义化查询，根据意思匹配
2. **bm25_search** - BM25 关键词检索：适合包含明确关键词、故障码、设备编号的查询
3. **conditional_query** - 条件精确查询：按设备类型/故障码/标签精确筛选
4. **graph_query** - 关联查询：查询与指定设备/故障相关的知识
5. **rewrite_query** - 查询改写：当检索结果质量不足时，将模糊查询改写为更专业的表述
6. **finish** - 完成搜索：当结果足够好时停止

## 决策原则：
- 语义模糊的查询优先用 vector_search，关键词明确的查询优先用 bm25_search
- 如果用户提供了设备类型或故障码，可额外用 conditional_query 和 graph_query 补充
- 首轮建议 vector_search + bm25_search 并行（实际会顺序执行）
- 如果当前结果数 >= 3 且最高分 >= 0.6，可以 finish
- 如果结果不足（< 3 条或最高分 < 0.5），应该用 rewrite_query 改写后重试
- 不要无限循环，最多 {self.MAX_ITERATIONS} 轮

## 返回格式（严格 JSON）：
{{"reasoning": "你的推理", "action": "工具名", "top_k": 10}}

如果是 finish: {{"reasoning": "...", "action": "finish", "finish": true}}"""

        # 判断是否需要改写
        quality = self._evaluate_quality(all_results, iteration)
        needs_rewrite_hint = ""
        if not quality["sufficient"] and len(all_results) > 0:
            needs_rewrite_hint = f"\n!!! 当前结果质量不足 ({quality['reason']})，建议用 rewrite_query 改写查询后重试"

        user_message = f"""## 当前用户查询
"{current_query}"

## 过滤条件
设备类型: {device_type or '无'}
故障码: {fault_code or '无'}

## 已获结果摘要
{results_summary}

## 推理历史
{scratchpad_text if scratchpad_text else '（无，这是首轮）'}
{needs_rewrite_hint}

## 当前迭代
第 {iteration}/{self.MAX_ITERATIONS} 轮

请决定下一步行动（返回纯 JSON）："""

        try:
            response = self.llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ])
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
            decision = json.loads(content)
            # 填充默认值
            decision.setdefault("reasoning", "")
            decision.setdefault("action", "finish")
            decision.setdefault("top_k", 10)
            return decision
        except Exception as e:
            logger.error(f"Agent think 失败: {e}")
            # 降级策略
            return self._fallback_decision(iteration, all_results)

    def _fallback_decision(self, iteration: int, all_results: List[Dict]) -> dict:
        """LLM 调用失败时的降级决策"""
        if iteration == 1:
            return {"reasoning": "首轮，执行向量检索（降级策略）", "action": "vector_search", "top_k": 10}
        elif len(all_results) < 3 and iteration < self.MAX_ITERATIONS:
            return {"reasoning": "结果不足，改写查询重试（降级策略）", "action": "rewrite_query", "top_k": 10}
        else:
            return {"reasoning": "达到终止条件", "action": "finish", "finish": True}

    def _evaluate_quality(self, results: List[Dict], iteration: int) -> dict:
        """评估检索结果质量"""
        if len(results) == 0:
            return {"sufficient": False, "reason": "无结果"}

        high_score_count = sum(1 for r in results if r.get("score", 0) >= self.MIN_SCORE_FOR_QUALITY)
        max_score = max(r.get("score", 0) for r in results)

        if len(results) >= self.MIN_RESULTS_FOR_QUALITY and (high_score_count >= 2 or max_score >= 0.7):
            return {"sufficient": True, "reason": f"结果充足 ({len(results)} 条, 最高分 {max_score:.2f})"}

        if iteration >= self.MAX_ITERATIONS:
            return {"sufficient": True, "reason": f"达到最大迭代次数 {self.MAX_ITERATIONS}"}

        return {"sufficient": False, "reason": f"结果不足 ({len(results)} 条, 最高分 {max_score:.2f})"}

    def _summarize_results(self, results: List[Dict]) -> str:
        """生成检索结果摘要"""
        if not results:
            return "（暂无结果）"

        summary_parts = []
        for i, r in enumerate(results[:5]):
            title = r.get("title", "无标题")
            score = r.get("score", r.get("rrf_score", 0))
            dt = r.get("device_type", "")
            fc = r.get("fault_code", "")
            content_preview = (r.get("content", "") or "")[:80]
            summary_parts.append(f"  {i+1}. [{score:.2f}] {title} | {dt}/{fc} | {content_preview}...")

        return "\n".join(summary_parts) + (
            f"\n  ... 共 {len(results)} 条" if len(results) > 5 else ""
        )
