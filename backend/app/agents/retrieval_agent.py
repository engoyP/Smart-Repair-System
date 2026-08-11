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
    """LLM 可选的动作清单（行动空间）——每轮决策只能选其中一个"""
    VECTOR_SEARCH = "vector_search"            # 向量语义检索（模糊查询用）
    BM25_SEARCH = "bm25_search"                # 关键词检索（明确关键词/故障码用）
    CONDITIONAL_QUERY = "conditional_query"    # 按设备类型/故障码精确筛选
    GRAPH_QUERY = "graph_query"                # 关联查询（与指定设备/故障相关的知识）
    REWRITE_QUERY = "rewrite_query"            # 查询改写（结果不足时的重试路径，不产生新结果）
    FINISH = "finish"                          # 结束检索


@dataclass
class AgentStep:
    """ReAct 循环中的单步记录（= scratchpad 里的一张"推理卡片"）"""
    step: int                  # 第几轮迭代
    thought: str = ""          # LLM 的思考内容（reasoning）
    action: str = ""           # 本步选择的动作（AgentAction 之一）
    tool_input: dict = field(default_factory=dict)  # 调用工具时的参数
    observation: str = ""      # 执行动作后的观察结果（检索到几条/失败原因）


@dataclass
class RetrievalResult:
    """检索 Agent 的最终结果包"""
    query: str                                 # 用户原始查询（回显用）
    results: List[Dict]                        # 检索结果列表（RRF 融合/排序后的）
    strategies_used: List[str]                 # 实际用过的检索策略名
    rewrite_count: int = 0                     # 查询被改写了几次
    rewritten_queries: List[str] = field(default_factory=list)  # 改写出的新查询词
    scratchpad: List[AgentStep] = field(default_factory=list)   # 完整推理链路（调试用）
    total_time_ms: float = 0.0                 # 总耗时（毫秒）


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

    MAX_ITERATIONS = 5                # ReAct 循环硬上限：最多 5 轮（防死循环）
    MIN_RESULTS_FOR_QUALITY = 3       # 质量达标的最低结果数：≥3 条
    MIN_SCORE_FOR_QUALITY = 0.6       # "高分"判定线：单条分数 ≥0.6 算高分

    def __init__(self, tools: RetrievalTools):
        self.tools = tools            # 检索工具集（vector/bm25/conditional/graph/rewrite）
        self._llm: Optional[ChatOpenAI] = None  # LLM 懒加载（首次调用才创建）

    @property
    def llm(self) -> ChatOpenAI:
        """懒加载 DeepSeek LLM（决策模块专用，temperature=0.1 保证决策稳定）"""
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.1,       # 低温度：决策尽量稳定，少发散
                streaming=False,       # 决策不需要流式，一次性返回 JSON
                timeout=30,            # 单次决策调用超时 30s，防止 DeepSeek 网络卡死阻塞整个检索
                max_retries=1,         # 最多重试 1 次，重试失败走 _fallback_decision 降级
            )
        return self._llm

    def search(self, query: str, device_type: Optional[str] = None,
               fault_code: Optional[str] = None, max_results: int = 10,
               require_hybrid: bool = False) -> RetrievalResult:
        """
        主入口：执行完整的 ReAct 检索流程
        Args:
            query: 用户自然语言查询
            device_type: 设备类型过滤（可选）
            fault_code: 故障码过滤（可选）
            max_results: 最大返回结果数
            require_hybrid: 为 True 时首轮强制执行 vector+BM25 双路检索，
                避免 ReAct 第一轮选 vector 且质量达标就早停，导致"混合检索"名存实亡。
                双路结果质量达标则直接进 RRF 融合；不达标继续走 LLM 决策循环。
        Returns:
            包含检索结果和推理链路的 RetrievalResult
        """
        import time
        start_time = time.time()

        # ===== 跨轮累积的全局状态（每轮共用） =====
        scratchpad: List[AgentStep] = []       # 推理卡片（每轮追加一张）
        all_results: List[Dict] = []           # 所有轮搜到的结果（去重累积，不覆盖）
        strategies_used: List[str] = []        # 用过的策略名集合
        rewrite_count = 0                      # 改写次数
        rewritten_queries = [query]            # 改写历史（首元素=原始查询）
        current_query = query                  # 当前查询词（可能被改写替换）

        # ===== 强制混合前置：首轮先确定性执行 vector + BM25 双路检索 =====
        hybrid_done = False
        if require_hybrid:
            step = AgentStep(step=1)
            for name, tool_call in (
                ("vector_search", lambda: self.tools.vector_search(
                    query=current_query, top_k=10,
                    device_type=device_type, fault_code=fault_code,
                    score_threshold=0.0)),
                ("bm25_search", lambda: self.tools.bm25_search(
                    query=current_query, top_k=10,
                    device_type=device_type, fault_code=fault_code)),
            ):
                result = tool_call()
                if result.success:
                    strategies_used.append(result.metadata.get("method", name))
                    existing_ids = {r.get("knowledge_id") for r in all_results if r.get("knowledge_id")}
                    for item in result.data:
                        kid = item.get("knowledge_id") or item.get("id")
                        if kid not in existing_ids:
                            existing_ids.add(kid)
                            all_results.append(item)
            step.thought = "首轮强制混合检索（vector + BM25 双路）"
            step.action = "hybrid(vector+bm25)"
            step.observation = f"混合检索累计 {len(all_results)} 条结果"
            scratchpad.append(step)
            logger.info(f"[Agent ReAct] 强制混合首轮: vector + BM25 累计 {len(all_results)} 条")
            # 双路结果质量达标 → 跳过 LLM 决策循环，直接进 RRF 融合
            if self._evaluate_quality(all_results, 1)["sufficient"]:
                logger.info(f"[Agent ReAct] 强制混合结果质量达标，停止搜索")
                hybrid_done = True

        for iteration in range(1, self.MAX_ITERATIONS + 1):   # 第1~5轮
            if hybrid_done:
                break
            step = AgentStep(step=iteration)   # 本轮的"推理卡片"（先建空卡）

            # === 1. 思考（每轮调一次 LLM） ===
            thought = self._think(
                current_query=current_query,
                device_type=device_type,
                fault_code=fault_code,
                scratchpad=scratchpad,         # 喂给 LLM：之前的完整推理历史
                all_results=all_results,       # 喂给 LLM：已搜到的结果摘要
                iteration=iteration,           # 喂给 LLM：当前第几轮
            )
            step.thought = thought["reasoning"]   # 记录 LLM 的思考
            step.action = thought["action"]       # 记录 LLM 选的动作

            logger.info(f"[Agent ReAct] 迭代 {iteration} | 思考: {thought['reasoning'][:80]}...")
            logger.info(f"[Agent ReAct] 迭代 {iteration} | 行动: {thought['action']}")

            # === 如果 LLM 判断已达到目标，输出 ===
            if thought["action"] == AgentAction.FINISH.value or thought.get("finish", False):
                step.observation = "Agent 判断检索结果已充分，终止搜索"
                scratchpad.append(step)
                logger.info(f"[Agent ReAct] Agent 决定完成，结果数: {len(all_results)}")
                break

            # === 2. 行动（按 LLM 选的动作分派到不同工具） ===
            if thought["action"] == AgentAction.REWRITE_QUERY.value:
                # 查询改写 —— 专门的重试路径：不检索，只"改写查询词"再进下一轮
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
                        current_query = rq     # 用改写后的第一个查询继续
                        # 使用改写后的查询继续下一轮循环（执行向量+BM25）
                        break
                    continue                   # 跳过下面的"观察/判断"，直接下一轮去检索
                else:
                    step.observation = f"查询改写失败: {rewrite_result.error}"
                    scratchpad.append(step)
                    break                      # 改写失败 → 强制结束（避免死循环）

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
                # 关联查询：排除已搜到的知识，避免重复
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

            # === 3. 观察（记录执行结果 + 去重累积） ===
            if result.success:
                step.observation = f"检索到 {len(result.data)} 条结果"
                strategies_used.append(result.metadata.get("method", thought["action"]))
                # 加入到累计结果（按 knowledge_id 去重，避免同一知识重复累积）
                existing_ids = {r.get("knowledge_id") for r in all_results if r.get("knowledge_id")}
                for item in result.data:
                    kid = item.get("knowledge_id") or item.get("id")
                    if kid not in existing_ids:
                        existing_ids.add(kid)
                        all_results.append(item)   # 新知识才加，已有知识跳过
            else:
                step.observation = f"检索失败: {result.error}"

            scratchpad.append(step)   # 本轮卡片归档进推理历史

            # === 4. 判断（规则判断，不调 LLM，省一次调用） ===
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
        # 构建 scratchpad 文本（把之前所有轮的思考/行动/观察压成文本）
        scratchpad_text = ""
        for s in scratchpad:
            scratchpad_text += f"""
步骤 {s.step}:
  思考: {s.thought}
  行动: {s.action}({json.dumps(s.tool_input, ensure_ascii=False)})
  观察: {s.observation}
"""

        results_summary = self._summarize_results(all_results)   # 已搜到的结果摘要

        # ===== 系统提示词：给 LLM 的"角色说明 + 工具手册 + 决策规则" =====
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

        # 判断是否需要改写（给 LLM 一个"建议改写"的提示，帮它做决定）
        quality = self._evaluate_quality(all_results, iteration)
        needs_rewrite_hint = ""
        if not quality["sufficient"] and len(all_results) > 0:
            needs_rewrite_hint = f"\n!!! 当前结果质量不足 ({quality['reason']})，建议用 rewrite_query 改写查询后重试"

        # ===== 用户消息：给 LLM 喂"当前完整状态" =====
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
            # 清理可能的 markdown 代码块包裹（```json ... ```）
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
            decision = json.loads(content)          # 解析 LLM 返回的 JSON
            # 填充默认值：LLM 漏给字段时兜底
            decision.setdefault("reasoning", "")
            decision.setdefault("action", "finish")  # 默认"结束"，宁可保守
            decision.setdefault("top_k", 10)
            return decision
        except Exception as e:
            logger.error(f"Agent think 失败: {e}")
            # 降级策略：LLM 挂了也不能让整个检索崩掉
            return self._fallback_decision(iteration, all_results)

    def _fallback_decision(self, iteration: int, all_results: List[Dict]) -> dict:
        """LLM 调用失败时的降级决策（按固定规则，保证不崩）"""
        if iteration == 1:
            return {"reasoning": "首轮，执行向量检索（降级策略）", "action": "vector_search", "top_k": 10}
        elif len(all_results) < 3 and iteration < self.MAX_ITERATIONS:
            return {"reasoning": "结果不足，改写查询重试（降级策略）", "action": "rewrite_query", "top_k": 10}
        else:
            return {"reasoning": "达到终止条件", "action": "finish", "finish": True}

    def _evaluate_quality(self, results: List[Dict], iteration: int) -> dict:
        """评估检索结果质量（规则判断，不用 LLM，省一次调用）"""
        if len(results) == 0:
            return {"sufficient": False, "reason": "无结果"}

        high_score_count = sum(1 for r in results if r.get("score", 0) >= self.MIN_SCORE_FOR_QUALITY)
        max_score = max(r.get("score", 0) for r in results)

        # 达标条件：≥3条 且（≥2条高分 或 最高分≥0.7）
        if len(results) >= self.MIN_RESULTS_FOR_QUALITY and (high_score_count >= 2 or max_score >= 0.7):
            return {"sufficient": True, "reason": f"结果充足 ({len(results)} 条, 最高分 {max_score:.2f})"}

        # 到最后一轮：无论如何强制算"够"（硬性结束，防死循环）
        if iteration >= self.MAX_ITERATIONS:
            return {"sufficient": True, "reason": f"达到最大迭代次数 {self.MAX_ITERATIONS}"}

        return {"sufficient": False, "reason": f"结果不足 ({len(results)} 条, 最高分 {max_score:.2f})"}

    def _summarize_results(self, results: List[Dict]) -> str:
        """生成检索结果摘要（喂给 LLM 让它知道"已经查到什么了"）"""
        if not results:
            return "（暂无结果）"

        summary_parts = []
        for i, r in enumerate(results[:5]):   # 最多展示前 5 条，控制 token
            title = r.get("title", "无标题")
            score = r.get("score", r.get("rrf_score", 0))
            dt = r.get("device_type", "")
            fc = r.get("fault_code", "")
            content_preview = (r.get("content", "") or "")[:80]
            summary_parts.append(f"  {i+1}. [{score:.2f}] {title} | {dt}/{fc} | {content_preview}...")

        return "\n".join(summary_parts) + (
            f"\n  ... 共 {len(results)} 条" if len(results) > 5 else ""
        )
