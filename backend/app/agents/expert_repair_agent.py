"""ExpertRepairAgent - 专家模式多轮会话（分析 + 引导）

专家模式首轮由 /answer/expert 端点完成"拆解 → 并行 ReAct → 分组五段式分析"，
本 Agent 负责在其之上补齐三件事：
1. 首轮：多故障共因/关联判定 + 维修优先级说明 + 2-3 个"下一步排查方向"选项（带推荐）
2. 会话：Redis 持久化（24h TTL），步数上限 30，历史超长用 SessionSummarizer 增量压缩
3. 后续轮：用户反馈后生成【分析】+ 2-3 个方向（带优先级），识别"解决/部分解决"决定继续或结束

会话结构（Redis JSON）：
{
  initial_question: 用户原始问题
  sub_queries: 拆解出的单故障子查询
  faults: [{name, case_titles}]  首轮各故障及其命中的案例标题（轻量概览）
  first_analysis: 首轮共因分析 + 优先级说明（注入后续轮上下文）
  chat_history: [{user, ai}]     多轮对话记录
  history_summary: 增量压缩出的历史摘要
  status: diagnosing / completed
  step_count: 已引导轮数
  created_at: 时间戳
}
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger

from app.core.config import settings
from app.core.langfuse_tracer import tracer


@dataclass
class ExpertOption:
    """排查方向选项"""
    id: str = ""
    cause: str = ""
    diagnostic_action: str = ""


@dataclass
class ExpertStepResult:
    """单轮引导结果"""
    session_id: str = ""
    step: int = 0
    analysis: str = ""
    options: List[ExpertOption] = field(default_factory=list)
    status: str = "awaiting_action"  # awaiting_action / completed
    summary: str = ""
    all_resolved: bool = False


class ExpertRepairAgent:
    """专家模式会话 + 引导生成"""

    _SESSION_TTL = 24 * 3600  # 会话有效期 24 小时
    _SESSION_KEY_PREFIX = "expert_repair_session:"

    MAX_STEPS = 30  # 引导轮数上限（对齐追踪维修）
    _HISTORY_COMPRESS_THRESHOLD = 25
    _HISTORY_KEEP_RAW = 20

    # ============ 首轮：共因判定 + 优先级 + 方向选项 ============

    FIRST_ROUND_PROMPT = """你是一个设备维修专家。用户一次描述了多个故障现象，每个故障都已检索到历史维修案例。

## 你的任务（分三步）
1. **共因/关联判断**：分析这些故障现象是否可能由同一个根因引起；若是，说明它们如何由该共因联动产生（如"油温高+锁模力不足+马达不转 ← 液压系统压力不足"）
2. **维修优先级**：明确说出先修哪个、为什么（共因优先 / 影响连锁优先 / 危险程度优先）
3. **下一步排查方向**：给出 2-3 个方向（**按优先级排序，第 1 个是推荐先做的**），每个方向必须包含三要素：
   - 先查哪（部件/回路/测量点）
   - 怎么查（具体操作：测什么、怎么测）
   - 判断标准（正常值/异常时说明什么）

## 硬约束
- 只能基于检索案例中明确写到的内容；案例没有的数值/方法不得编造，标注"案例未覆盖，按通用排查逻辑给出方向"
- 若多故障确无共因（各自独立），明确说"各故障相互独立"，并按危险程度/影响排序
- 输出严格 JSON，不要 markdown 代码块

## 返回格式
{
  "analysis": "【多故障关联分析】...（含共因判断 + 优先级说明，80-200字）",
  "options": [
    {"id": "A", "cause": "先查XX（推荐先做，因共因/影响最大）", "diagnostic_action": "怎么查 + 判断标准"},
    {"id": "B", "cause": "若共因排除后仍存在再查XX", "diagnostic_action": "怎么查 + 判断标准"}
  ]
}"""

    # ============ 后续轮：反馈解读 + 下一步方向 ============

    NEXT_STEP_PROMPT = """你是设备维修引导专家，正在带维修员逐步排查。用户描述了多个故障现象，首轮分析已给出方向和优先级，现在根据用户反馈继续。

## 你的任务
1. **【分析】** 解读用户反馈：这次操作结果说明什么（正常/异常分别意味着什么），当前定位到哪里
2. **判断是否解决**：
   - 反馈表明该方向已解决（解决/好了/恢复正常/修复/恢复 等）→ 判断是否还有其他未解决的故障现象：
     - 全部解决 → status=completed，给出维修总结 summary
     - 部分解决（共因解决了但还有现象在）→ 继续给出剩余方向的下一步，并说明"剩余现象"是哪些
   - 未解决 → 在该方向上深挖或切换到下一个优先方向
3. **下一步方向**：给 2-3 个方向（带优先级，第 1 个推荐），每个含"先查哪 + 怎么查 + 判断标准"

## 硬约束
- **不要重复已经排查过、已排除的方向**
- 只能基于检索案例明确内容；案例不足如实说明
- 输出严格 JSON，不要 markdown 代码块

## 返回格式
{
  "analysis": "【分析】...（60-150字）",
  "options": [{"id": "A", "cause": "...", "diagnostic_action": "..."}],
  "status": "awaiting_action" 或 "completed",
  "all_resolved": true/false,
  "summary": "（completed 时必填，否则空字符串）",
  "remaining_faults": "（部分解决时说明剩余现象，否则空字符串）"
}"""

    def __init__(self):
        self._llm: Optional[object] = None

    @property
    def llm(self):
        """懒加载 DeepSeek（决策/引导 temperature 0.3，稳定且稍有发散空间）"""
        if self._llm is None:
            from langchain_openai import ChatOpenAI
            self._llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.3,
                streaming=False,
                timeout=60,
                max_retries=1,
            )
        return self._llm

    # ============ 会话存取 ============

    def _load_session(self, session_id: str) -> Optional[Dict]:
        try:
            from app.core.cache_service import cache_service
            return cache_service.get(f"{self._SESSION_KEY_PREFIX}{session_id}")
        except Exception as e:
            logger.warning(f"[ExpertRepair] 会话加载失败: {e}")
            return None

    def _save_session(self, session_id: str, data: Dict):
        try:
            self._maybe_compress_history(data)
            from app.core.cache_service import cache_service
            cache_service.set(f"{self._SESSION_KEY_PREFIX}{session_id}", data, ttl=self._SESSION_TTL)
        except Exception as e:
            logger.warning(f"[ExpertRepair] 会话保存失败: {e}")

    def create_session(self, question: str, sub_queries: List[str],
                       faults: List[Dict], first_analysis: str) -> str:
        """首轮分析完成后创建会话，返回 session_id"""
        sid = str(uuid.uuid4())
        self._save_session(sid, {
            "initial_question": question,
            "sub_queries": sub_queries or [question],
            "faults": [
                {"name": f.get("name", f"故障{i + 1}"),
                 "case_titles": [c.get("title", "") for c in f.get("cases", [])][:5]}
                for i, f in enumerate(faults)
            ],
            "first_analysis": first_analysis,
            "chat_history": [],
            "history_summary": "",
            "status": "diagnosing",
            "step_count": 0,
            "created_at": time.time(),
        })
        return sid

    def _maybe_compress_history(self, session: Dict):
        """chat_history 过长时增量压缩最旧部分（同追踪维修策略）"""
        history = session.get("chat_history", [])
        if not history or len(history) <= self._HISTORY_COMPRESS_THRESHOLD:
            return
        split = len(history) - self._HISTORY_KEEP_RAW
        old, keep = history[:split], history[split:]
        msgs = []
        if session.get("history_summary"):
            msgs.append({"role": "assistant", "content": f"[历史摘要]\n{session['history_summary']}"})
        for h in old:
            msgs.append({"role": "user", "content": h.get("user", "")})
            if h.get("ai"):
                msgs.append({"role": "assistant", "content": h["ai"]})
        try:
            from app.agents.session_summarizer import session_summarizer
            summary = session_summarizer.summarize(msgs)
        except Exception as e:
            logger.warning(f"[ExpertRepair] 历史摘要压缩失败，保留原文: {e}")
            return
        session["history_summary"] = summary
        session["chat_history"] = keep
        logger.info(f"[ExpertRepair] 历史已压缩: {len(old)} 条并入摘要，保留最近 {len(keep)} 条原文")

    # ============ 首轮：共因判定 + 优先级 + 选项 ============

    def generate_first_round(self, question: str, faults: List[Dict]) -> Dict:
        """基于拆解出的故障及其案例，生成共因分析 + 优先级 + 2-3 个方向选项

        Returns:
            {"analysis": str, "options": [{"id","cause","diagnostic_action"}]}
        """
        faults_text = ""
        for i, f in enumerate(faults, 1):
            name = f.get("name", f"故障{i}")
            cases = f.get("cases", [])
            faults_text += f"\n## 故障{i}: {name}\n"
            if not cases:
                faults_text += "（该故障未检索到案例）\n"
                continue
            for j, c in enumerate(cases[:3], 1):
                faults_text += (f"### 案例{j}（相关度: {c.get('score', 0):.0%}）\n"
                                f"- 标题: {c.get('title', '')}\n"
                                f"- 故障码: {c.get('fault_code', '')}\n"
                                f"- 内容要点: {(c.get('content', '') or '')[:400]}\n")

        user_prompt = f"""## 用户问题
{question}

## 按故障分组的检索案例
{faults_text}

请完成共因/关联判断、维修优先级、下一步排查方向，返回 JSON。"""

        default = {
            "analysis": "已分析多故障关联与排查优先级。",
            "options": [{"id": "A", "cause": "继续排查",
                         "diagnostic_action": "请描述执行后的设备状态，以便给出下一步方向。"}],
        }
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            with tracer.trace("expert_first_round", metadata={
                "question_length": len(question),
                "faults_count": len(faults),
            }) as trace_obj:
                resp = self.llm.invoke([
                    SystemMessage(content=self.FIRST_ROUND_PROMPT),
                    HumanMessage(content=user_prompt),
                ])
                trace_obj.generation("expert_first_round_llm", model=settings.DEEPSEEK_MODEL,
                                     prompt=user_prompt, response=resp.content)
                data = self._parse_json(resp.content)
                if not data or "options" not in data:
                    return default
                options = []
                for idx, o in enumerate(data.get("options", [])[:3]):
                    options.append({
                        "id": o.get("id") or chr(65 + idx),
                        "cause": o.get("cause", ""),
                        "diagnostic_action": o.get("diagnostic_action", ""),
                    })
                return {
                    "analysis": data.get("analysis", "") or default["analysis"],
                    "options": options or default["options"],
                }
        except Exception as e:
            logger.error(f"[ExpertRepair] 首轮共因/方向生成失败: {e}")
            return default

    # ============ 后续轮：反馈解读 + 下一步方向 ============

    def next_step(self, session_id: str, message: str) -> ExpertStepResult:
        session = self._load_session(session_id)
        if not session:
            return ExpertStepResult(
                session_id=session_id, step=0,
                analysis="会话不存在或已过期，请重新开始。",
                status="completed",
            )

        step_num = session.get("step_count", 0) + 1
        if step_num > self.MAX_STEPS:
            return ExpertStepResult(
                session_id=session_id, step=step_num,
                analysis="已达到最大排查轮数（30 轮）。建议将目前排查情况提交给资深工程师进一步分析。",
                options=[], status="completed",
                summary=self._build_final_summary(session),
            )

        # 检索：初始问题 + 当前反馈
        cases = self._search_knowledge(f"{session['initial_question']} {message}")

        # 构建上下文：首轮分析 + 历史摘要 + 最近原文
        context = [f"【首轮多故障分析】\n{session.get('first_analysis', '')}"]
        if session.get("history_summary"):
            context.append(f"【已压缩的历史摘要】\n{session['history_summary']}")
        for h in session.get("chat_history", [])[-self._HISTORY_KEEP_RAW:]:
            context.append(f"维修员: {h.get('user', '')}\n你: {h.get('ai', '')}")
        history_text = "\n\n".join(context)

        cases_text = ""
        for i, c in enumerate(cases, 1):
            cases_text += (f"### 参考案例{i}（相关度: {c.get('score', 0):.0%}）\n"
                           f"- 标题: {c.get('title', '')}\n"
                           f"- 内容要点: {(c.get('content', '') or '')[:400]}\n")
        if not cases_text:
            cases_text = "（未检索到匹配案例，请如实说明，不得编造排查步骤）"

        user_prompt = f"""## 初始多故障问题
{session['initial_question']}

## 排查历史
{history_text}

## 用户最新反馈
{message}

## 检索到的参考案例（唯一知识来源）
{cases_text}

请根据反馈判断是否解决、给出下一步方向，返回 JSON。"""

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            with tracer.trace("expert_next_step", metadata={
                "session_id": session_id, "step": step_num,
            }) as trace_obj:
                resp = self.llm.invoke([
                    SystemMessage(content=self.NEXT_STEP_PROMPT),
                    HumanMessage(content=user_prompt),
                ])
                trace_obj.generation("expert_next_step_llm", model=settings.DEEPSEEK_MODEL,
                                     prompt=user_prompt, response=resp.content)
                data = self._parse_json(resp.content) or {}
        except Exception as e:
            logger.error(f"[ExpertRepair] 引导生成失败: {e}")
            data = {}

        status = data.get("status") or "awaiting_action"
        options = []
        for idx, o in enumerate((data.get("options") or [])[:3]):
            options.append(ExpertOption(
                id=o.get("id") or chr(65 + idx),
                cause=o.get("cause", ""),
                diagnostic_action=o.get("diagnostic_action", ""),
            ))

        result = ExpertStepResult(
            session_id=session_id,
            step=step_num,
            analysis=data.get("analysis") or "请继续描述执行结果或设备状态。",
            options=options,
            status="completed" if status == "completed" else "awaiting_action",
            summary=data.get("summary") or "",
            all_resolved=bool(data.get("all_resolved", status == "completed")),
        )

        # 更新会话
        session["step_count"] = step_num
        session["chat_history"].append({"user": message, "ai": result.analysis})
        if result.status == "completed":
            session["status"] = "completed"
        self._save_session(session_id, session)
        return result

    # ============ 工具 ============

    def _search_knowledge(self, query: str) -> List[Dict]:
        """管道四路优先 → 阀门判定 → 不足 ReAct 救援，取 top3

        引导轮专用：先走确定性四路管道（retrieve_hybrid + 严格过滤 + 精排 + 置顶）；
        结果不满足公共阀门（≥3 条且高分≥2 或最高分≥0.7）时触发 ReAct 救援改写检索，保证引导素材充分。
        """
        try:
            from app.agents.retrieval_flow import (
                make_tools, retrieve_hybrid, filter_rerank_cases, extract_device_and_fault,
                evaluate_retrieval_quality,
            )
            tools = make_tools()
            merged, error_codes, tools = retrieve_hybrid(query, top_k=10)
            device, kws = extract_device_and_fault(tools, query)
            cases = filter_rerank_cases(
                tools, merged, query, top_n=5,
                require_device=device, require_keywords=tuple(kws),
                error_codes=error_codes,
            )
            # 管道充分 → 直接返回
            if evaluate_retrieval_quality(cases)["sufficient"]:
                return cases[:3]

            # 管道不足 → ReAct 救援（首轮强制双路），再严格过滤收口
            from app.agents.retrieval_agent import RetrievalAssistantAgent
            agent = RetrievalAssistantAgent(tools=tools)
            result = agent.search(query=query, max_results=10, require_hybrid=True)
            device, kws = extract_device_and_fault(tools, query)
            cases = filter_rerank_cases(
                tools, result.results, query, top_n=5,
                require_device=device, require_keywords=tuple(kws),
                error_codes=error_codes,
            )
            return cases[:3]
        except Exception as e:
            logger.error(f"[ExpertRepair] 检索失败: {e}")
            return []

    def _build_final_summary(self, session: Dict) -> str:
        lines = [f"**初始问题**: {session.get('initial_question', '')}", ""]
        lines.append("**已排查过程**:")
        for i, h in enumerate(session.get("chat_history", [])):
            lines.append(f"  - {h.get('user', '')[:40]}")
        lines.append("")
        lines.append("**建议**: 已达最大排查轮数，建议联系资深工程师进一步分析。")
        return "\n".join(lines)

    def _parse_json(self, content: str) -> Optional[Dict]:
        """解析 LLM 返回的 JSON（容忍 markdown 代码块包裹）"""
        if not content:
            return None
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[ExpertRepair] JSON 解析失败: {e}, raw: {content[:200]}")
            return None


expert_repair_agent = ExpertRepairAgent()
