"""验证 Agent（VerifyAgent）—— 回答生成前对检索结果做三层把关，杜绝胡编乱造

职责：保证进入回答阶段的案例/手册条目**真实存在于知识库/手册库、且验证通过**。

三层把关：
1. Gate（客观，零 LLM）：候选为空 / 错误码未命中手册 —— 只拦事实，无主观阈值
2. Judge（语义，LLM）：整体可答性裁决（sufficient / reason / missing）—— 边界由语义判断
3. 存在性核对（DB 工具）：knowledge_id / manual_code_id 必须在 PG 中真实存在

自主重搜循环（agentic loop，使其成为"真 Agent"）：
- Judge 判 insufficient → 分析失败原因 → 改写查询 / 放宽设备 / 补手册路 → 工具重搜 → 再 Judge
- 停止条件：sufficient / max_iterations（资源护栏，非质量边界）/ 重搜无进展

设计原则：
- 质量边界交给 LLM 语义裁决，不设拍脑袋的数字阈值
- 唯一保留的数字是 MAX_ITERATIONS，定位为成本护栏
- 全程降级：LLM 失败 → 规则宽松兜底（不假装精确）

与 LangGraph 集成：作为 QaGraph 故障子图的一个节点（filter → verify → answer），
内部循环对图透明；钉钉/专家模式可复用同一 verify() 入口。
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from loguru import logger
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.knowledge import KnowledgeItem
from app.models.manual_code import ManualCodeEntry


class VerifyAgent:
    """验证 Agent：检索结果进回答前的最后一道质量与真实性把关"""

    MAX_ITERATIONS = 2          # 资源护栏（成本控制），不是质量边界

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None

    # ------------------------------------------------------------------
    # LLM 懒加载（与 AnswerAgent 同一套 DeepSeek 配置）
    # ------------------------------------------------------------------
    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0,
                timeout=20,
            )
        return self._llm

    # ------------------------------------------------------------------
    # ① Gate：客观异常检查（零 LLM，只拦事实，不设主观阈值）
    # ------------------------------------------------------------------
    def gate(self, query: str, cases: List[dict], error_codes: Optional[List[str]] = None) -> List[str]:
        """返回客观异常信号列表（空 = 无客观异常）。

        - empty: 检索结果为空（客观事实）
        - manual_miss: 问题含错误码但候选 0 条手册命中（手册路失败，客观事实）
        """
        signals: List[str] = []
        if not cases:
            signals.append("empty")
        if error_codes and not any(c.get("manual_code_id") for c in cases):
            signals.append("manual_miss")
        return signals

    # ------------------------------------------------------------------
    # ② Judge：语义可答性裁决（LLM 结构化输出）
    # ------------------------------------------------------------------
    JUDGE_PROMPT = """你是检索质量评审。判断：基于以下候选案例，能否对用户问题给出可靠、基于事实、不编造的回答。

判定标准：
1. 是否有至少一个案例与问题直接相关（设备类型、故障类型匹配）
2. 案例信息是否足够支撑回答（缺失关键处理信息不算充足）
3. 宁可保守：没有可靠证据就判 insufficient

只输出 JSON（不要输出其他内容）：
{{"sufficient": true/false, "reason": "一句话理由", "missing": "缺什么（如：缺少同设备案例 / 缺少错误码手册条目）"}}

用户问题：{query}
候选案例：
{cases}"""

    def judge(self, query: str, cases: List[dict]) -> dict:
        """LLM 语义裁决；失败时宽松降级（有案例即视为可答，不假装精确）"""
        if not cases:
            return {"sufficient": False, "reason": "无候选案例", "missing": "检索结果为空"}
        case_text = ""
        for i, c in enumerate(cases[:5], 1):
            case_text += (
                f"[{i}] 标题:{c.get('title','')} | 设备:{c.get('device_type','')} "
                f"| 故障码:{c.get('fault_code','')} | 分数:{c.get('score',0):.2f}\n"
                f"    内容:{str(c.get('content',''))[:150]}\n"
            )
        try:
            resp = self.llm.invoke([HumanMessage(content=self.JUDGE_PROMPT.format(query=query, cases=case_text))])
            verdict = self._parse_json(resp.content or "")
            return {
                "sufficient": bool(verdict.get("sufficient")),
                "reason": str(verdict.get("reason", ""))[:200],
                "missing": str(verdict.get("missing", ""))[:200],
            }
        except Exception as e:
            logger.warning(f"[VerifyAgent] Judge LLM 失败，宽松降级: {e}")
            return {"sufficient": True, "reason": "LLM 降级", "missing": ""}

    # ------------------------------------------------------------------
    # ③ PlanRetry：重搜策略（LLM；失败降级为规则）
    # ------------------------------------------------------------------
    PLAN_PROMPT = """你是检索策略规划。上一轮检索未找到足够的可靠案例，请规划一次重搜。

输入信息：
- 用户问题：{query}
- 上轮不相关原因：{reason}
- 识别出的错误码：{codes}

只输出 JSON（不要输出其他内容）：
{{"rewritten_query": "改写后的查询词（去噪声词、聚焦核心故障，中文）", "loosen_device": true/false, "use_manual_codes": true/false}}

规则：改写的查询要更聚焦故障本质；原查询已有明确设备时 loosen_device 可 false，检索过严时 true。"""

    def plan_retry(self, query: str, cases: List[dict], error_codes: Optional[List[str]]) -> dict:
        """返回重搜策略；失败时规则降级（取核心词 + 放宽设备 + 有错误码则补手册路）"""
        reason = ""
        try:
            verdict = self.judge(query, cases)
            reason = verdict.get("reason", "")
        except Exception:
            pass
        try:
            resp = self.llm.invoke([HumanMessage(content=self.PLAN_PROMPT.format(
                query=query, reason=reason, codes=",".join(error_codes or [])))])

            strategy = self._parse_json(resp.content or "")
            return {
                "rewritten_query": str(strategy.get("rewritten_query") or query)[:100],
                "loosen_device": bool(strategy.get("loosen_device", True)),
                "use_manual_codes": bool(strategy.get("use_manual_codes", bool(error_codes))),
            }
        except Exception as e:
            logger.warning(f"[VerifyAgent] PlanRetry LLM 失败，规则降级: {e}")
            from app.agents.retrieval_flow import make_tools
            try:
                cleaned = make_tools().query_extractor.extract(query, use_llm_fallback=False)
                rewritten = cleaned or query
            except Exception:
                rewritten = query
            return {
                "rewritten_query": rewritten[:100],
                "loosen_device": True,
                "use_manual_codes": bool(error_codes),
            }

    # ------------------------------------------------------------------
    # ④ Research：工具重搜（复用公共检索编排层）
    # ------------------------------------------------------------------
    def research(self, strategy: dict, query: str, device_type: Optional[str],
                 error_codes: Optional[List[str]]) -> List[dict]:
        from app.agents.retrieval_flow import retrieve_hybrid, filter_rerank_cases, extract_device_and_fault
        q = strategy.get("rewritten_query") or query
        dev = None if strategy.get("loosen_device") else device_type
        try:
            merged, codes, tools = retrieve_hybrid(q, top_k=10, device_type=dev, fault_code=None)
            device, kws = extract_device_and_fault(tools, q)
            return filter_rerank_cases(
                tools, merged, q,
                require_device=device if not strategy.get("loosen_device") else "",
                require_keywords=tuple(kws),
                error_codes=codes or error_codes,
            )
        except Exception as e:
            logger.error(f"[VerifyAgent] 重搜失败: {e}")
            return []

    @staticmethod
    def _made_progress(old: List[dict], new: List[dict]) -> bool:
        """重搜是否带来新案例（防死循环）"""
        def ids(cases):
            return {c.get("knowledge_id") or c.get("manual_code_id") for c in cases}
        new_ids, old_ids = ids(new), ids(old)
        return bool(new_ids) and new_ids != old_ids

    # ------------------------------------------------------------------
    # ⑤ 存在性核对：DB 工具（硬边界，存在即存在）
    # ------------------------------------------------------------------
    def _exists_in_db(self, case: dict) -> bool:
        """knowledge_id / manual_code_id 必须在 PG 中真实存在"""
        db = SessionLocal()
        try:
            if case.get("manual_code_id"):
                return db.query(ManualCodeEntry).filter(
                    ManualCodeEntry.id == case["manual_code_id"]).first() is not None
            cid = case.get("knowledge_id") or case.get("id")
            if not cid:
                return False
            return db.query(KnowledgeItem).filter(KnowledgeItem.id == cid).first() is not None
        except Exception as e:
            logger.warning(f"[VerifyAgent] 存在性核对异常: {e}")
            return True          # 查库异常不误杀（宁可放行，配合降级）
        finally:
            db.close()

    def exists_in_db(self, cases: List[dict]) -> tuple:
        """返回 (verified, dropped) 两组案例"""
        verified, dropped = [], []
        for c in cases:
            (verified if self._exists_in_db(c) else dropped).append(c)
        return verified, dropped

    # ------------------------------------------------------------------
    # 主入口：Gate → Judge → 重搜循环 → 存在性核对
    # ------------------------------------------------------------------
    def verify(self, query: str, cases: List[dict],
               device_type: Optional[str] = None,
               fault_code: Optional[str] = None,
               error_codes: Optional[List[str]] = None) -> tuple:
        """返回 (verified_cases, report)。verified_cases 是唯一允许进入回答阶段的信息源。

        report 含每轮裁决/重搜策略/剔除数，供日志与可观测展示。
        """
        from app.agents.tools import extract_error_codes
        error_codes = error_codes or extract_error_codes(query)
        report = {
            "gate": self.gate(query, cases, error_codes),
            "rounds": [],
            "sufficient": False,
            "dropped": 0,
            "verified_count": 0,
        }

        current = list(cases)
        for round_no in range(self.MAX_ITERATIONS + 1):
            verdict = self.judge(query, current)
            report["rounds"].append({"round": round_no, "verdict": verdict})
            if verdict.get("sufficient"):
                report["sufficient"] = True
                break
            if round_no >= self.MAX_ITERATIONS:
                break
            strategy = self.plan_retry(query, current, error_codes)
            report["rounds"][-1]["strategy"] = strategy
            new_cases = self.research(strategy, query, device_type, error_codes)
            if not self._made_progress(current, new_cases):
                logger.info(f"[VerifyAgent] 重搜无新进展，停止。query={query[:30]}")
                break
            current = new_cases

        verified, dropped = self.exists_in_db(current)
        report["dropped"] = len(dropped)
        report["verified_count"] = len(verified)
        logger.info(f"[VerifyAgent] query={query[:40]} rounds={len(report['rounds'])} "
                    f"sufficient={report['sufficient']} verified={len(verified)} dropped={len(dropped)}")
        return verified, report

    # ------------------------------------------------------------------
    # 引用核对（预留）：回答文本中的 [CASE-x] / [MANUAL-x] 成员核对
    # 接"结构化引用"后启用：回答只能引用已验证集合内的 id
    # ------------------------------------------------------------------
    def check_citations(self, answer: str, allowed_cases: List[dict]) -> List[str]:
        """提取回答中的 [CASE-<id>]/[MANUAL-<id>] 引用，返回不在已验证集合内的假引用"""
        allowed = set()
        for c in allowed_cases:
            cid = c.get("knowledge_id") or c.get("manual_code_id")
            if cid:
                allowed.add(cid)
        fakes = []
        for m in re.finditer(r"\[(?:CASE|MANUAL)-(\d+)\]", answer or ""):
            if int(m.group(1)) not in allowed:
                fakes.append(m.group(0))
        return fakes

    @staticmethod
    def _parse_json(text: str) -> dict:
        """容错解析 LLM 的 JSON 输出（DeepSeek 偶发截断缺尾部括号）。

        依次尝试：完整解析 → 正则提取 `{...}` → 补闭合括号 `}`/`}}`。
        全部失败抛 ValueError（由调用方降级）。
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("空响应")

        def _loads(s):
            return json.loads(s)

        # 1. 完整响应直接解析（可能带 ```json 包裹或前后杂文本）
        try:
            return _loads(text)
        except Exception:
            pass
        # 2. 正则提取对象 + 逐级补闭合括号
        m = re.search(r"\{.*", text, re.S)
        if m:
            for extra in ("", "}", "}}"):
                try:
                    return _loads(m.group(0) + extra)
                except Exception:
                    continue
        raise ValueError(f"无法解析 JSON: {text[:80]!r}")


# 单例（与 answer_agent / guided_repair_agent 一致的模块级实例）
verify_agent = VerifyAgent()
