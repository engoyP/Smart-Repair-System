"""AnswerGenerator - 分析型回答生成器（功能工具模块，非 Agent）

功能：
- 基于检索到的历史维修案例，生成分析回答
- 在回答中整合多个案例的共同点和差异
- 返回结构化答案：分析回答 + 参考案例列表
"""
import json
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from loguru import logger

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.langfuse_tracer import tracer


@dataclass
class ReferenceCase:
    """参考案例"""
    knowledge_id: int
    title: str
    content: str
    device_type: str = ""
    fault_code: str = ""
    score: float = 0.0
    summary: str = ""


@dataclass
class AnswerResult:
    """问答结果"""
    question: str
    answer: str
    references: List[ReferenceCase] = field(default_factory=list)
    confidence: float = 0.0
    sources_count: int = 0
    thinking_process: str = ""


class AnswerGenerator:
    """分析型回答生成器 - 基于历史案例生成回答（单次 LLM 调用，智能在上游检索与验证）"""

    SYSTEM_PROMPT = """你是一个设备维修知识库检索助手。你的唯一职责是：基于系统提供的检索案例，如实回答用户问题。

## 核心规则（严格遵守）

1. **只回答检索到的内容**：你只能基于下方「检索案例」列表中的信息回答。不得编造、推测、补充任何案例中没有的内容。

2. **如实回答无匹配的情况**：如果检索案例与用户问题明显不相关（例如用户问的是非设备维修问题，或案例内容与问题完全不匹配），你必须如实回复「未检索到与该问题相关的历史案例」，不得强行拼凑回答。

3. **分数由系统决定**：案例的相关度分数（百分比）来自检索系统，不得修改、重打分或编造。展示案例时如实显示系统给出的分数。

4. **不提供通用建议**：不要提供检索案例中没有的「通用排查步骤」或「常规注意事项」。不得自行发挥，不得使用案例之外的维修经验或常识。

5. **注明来源**：检索案例会标注来源类型（「手册」= 设备说明书/维修手册，含错误码/章节/页码；「工单案例」= 历史维修工单）。回答引用某案例内容时，在该结论后注明出处：
   - 手册：`（来源：<手册名>·<章节>·<页码>·错误码 <错误码>）`
   - 工单案例：`（来源：工单案例）`

## 手册条目专用规则（案例含「情形清单」/「严重度」字段时适用）

6. **情形清单已按匹配度排序**：手册条目的情形清单按与用户日志/描述的伴随信号匹配度排序，排在前面的情形更可能是本次故障。输出「可能原因」与「处理方案」时优先引用排在前面的情形，并**保持情形分组**（每个情形的原因与处理步骤成对出现），不得把不同情形的处理步骤混在一起。

7. **严重度表述规则**（按条目的严重度字段决定回答措辞）：
   - **EX（急停）**：回答开头明示「该报警为急停级，涉及安全回路，请先确认人员安全与急停复位条件」；处理步骤必须逐条列出，不得省略。
   - **OH（停机）**：按情形给出停机原因排查与恢复步骤；原文提到复位/重启方式时说明（未提到则不写）。
   - **INFO（提示）**：**开头必须说明「该报警为提示级，设备可能并未发生实际故障」**；先给出快速确认项（原文有才写），再说明不处理可能产生的后果（原文有才写）。

## 问题类型判断（重要）

根据用户问题的性质，选择以下对应的回答格式：

### 设备类型查询（如"XX设备有哪些""XX类型有哪些""XX有多少种类"）
先纠正用户的笔误（如有），然后：
1. 从检索案例中汇总出现的设备类型及其故障码
2. 对每种设备类型，基于案例描述其典型的故障情况和表现
3. 总结当前知识库中该设备的覆盖范围

### 故障诊断查询（如"XX不亮""XX报警怎么处理"）
按以下五段结构输出完整分析：
1. **问题分析**：基于案例定位故障的本质原因
2. **可能原因**：列出案例中明确提到的所有可能原因，按可能性排序
3. **排查方向**：结合案例给出具体的排查步骤，包括检查顺序、测量参数、判断标准
4. **处理方案**：详细列出案例中的维修方法和操作步骤
5. **预防建议**：案例中提到的预防措施，没有则写"案例中未提及预防措施"

**禁止在回答末尾列出参考案例清单**。参考案例由系统界面单独展示，不需要在你的回答中重复。

## 回答风格
- 简体中文，结构清晰，内容充分
- 每个部分要展开说明，不要用"测量电压、检查保险丝"这种极简列表
- 严格基于案例内容，不添加案例中没有的信息"""

    # 案例相关度阈值：低于此分数视为不相关，不送入 LLM（配置化，换模型后按标定结果调整）
    SCORE_THRESHOLD = settings.RETRIEVAL_COARSE_THRESHOLD

    MULTI_FAULT_PROMPT = """你是一个设备维修知识库的维修专家。用户的问题中描述了同一设备同时出现的多个故障现象，你需要**按故障分组**给出分析。

## 核心规则（严格遵守）

1. **按故障分节输出**：每个故障输出一个完整小节，小节结构为：
   - **故障现象**
   - **可能原因**（基于该故障的检索案例，按可能性排序）
   - **排查方向**（结合案例给出具体的检查顺序、测量参数、判断标准）
   - **处理方案**（案例中的维修方法和操作步骤）
   - **预防建议**（案例中有则写，没有写"案例中未提及预防措施"）

2. **只基于各组检索案例回答**：每个故障小节只能引用"按故障分组的检索案例"中该故障自己的案例内容，不得编造、推测，不得用其他故障的案例凑数。

3. **未检索到案例的故障必须显式说明**：若某个故障没有对应案例，在该小节明确写"知识库中未检索到与该故障直接相关的历史案例"。

4. **分数由系统决定**：案例相关度分数来自检索系统，不得修改、重打分或编造。

5. **不提供通用建议**：不要提供检索案例中没有的"通用排查步骤"或"常规注意事项"。

## 回答风格
- 开头一句话总结："该设备共涉及 N 个故障现象，逐一分析如下。"
- 简体中文，结构清晰，每个故障之间用标题区分（如 **故障1：温度偏高**）
- **禁止在回答末尾列出参考案例清单**，参考案例由系统界面单独展示
- 严格基于案例内容，不添加案例中没有的信息"""

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.5,
                streaming=True,
                timeout=90,            # 回答生成（流式）超时 90s，超时返回"生成失败"而非无限挂起
                max_retries=2,
            )
        return self._llm

    # === 库存查询关键词 ===
    _INVENTORY_KEYWORDS = [
        "库存", "备件", "零件", "配件", "备品", "还有多少", "还剩多少",
        "查库存", "有没有", "数量", "剩下", "够不够", "缺不缺",
        "保险丝", "传感器", "继电器", "轴承", "密封圈", "电机", "泵",
    ]

    def is_inventory_query(self, question: str) -> bool:
        """检测用户问题是否为库存/备件查询"""
        q = question.strip()
        # 快速关键词匹配
        inv_kw = ["库存", "备件", "零件", "配件", "备品", "还有多少", "还剩多少", "查库存", "有没有", "剩下", "够不够", "缺不缺"]
        for kw in inv_kw:
            if kw in q:
                return True
        # 部件名 + 数量/库存组合
        part_kw = ["保险丝", "传感器", "继电器", "轴承", "密封圈", "电机", "泵", "滤芯", "螺丝", "密封垫"]
        stock_kw = ["数量", "库存", "还有", "剩", "有没有", "几个", "多少"]
        has_part = any(kw in q for kw in part_kw)
        has_stock = any(kw in q for kw in stock_kw)
        if has_part and has_stock:
            return True
        return False

    def handle_inventory_query(self, question: str, db: Session) -> AnswerResult:
        """处理库存查询：从 SparePart 表中搜索匹配部件并返回库存信息"""
        from app.models.spare_part import SparePart

        q = question.strip()
        # 从问题中提取可能的部件关键词
        search_terms = self._extract_part_keywords(q)

        if not search_terms:
            return AnswerResult(
                question=question,
                answer="抱歉，未能从您的问题中识别出具体的备件名称或编码。请尝试提供更明确的备件信息，例如「查一下保险丝的库存」或「FR-001 还有多少」。",
                references=[],
                confidence=0,
                sources_count=0,
            )

        # 用 OR 条件查询匹配的备件
        results = []
        try:
            query = db.query(SparePart)
            conditions = []
            for term in search_terms:
                conditions.append(SparePart.part_name.ilike(f"%{term}%"))
                conditions.append(SparePart.part_code.ilike(f"%{term}%"))
                conditions.append(SparePart.specification.ilike(f"%{term}%"))
                conditions.append(SparePart.device_type.ilike(f"%{term}%"))
            if conditions:
                from sqlalchemy import or_
                query = query.filter(or_(*conditions))
            results = query.all()
        except Exception as e:
            logger.error(f"[AnswerGenerator] 库存查询失败: {e}")
            return AnswerResult(
                question=question,
                answer="库存查询服务暂时不可用，请稍后重试。",
                references=[],
                confidence=0,
                sources_count=0,
            )

        if not results:
            return AnswerResult(
                question=question,
                answer=f"仓库中未找到与「{', '.join(search_terms[:3])}」匹配的备件库存记录。请确认备件名称或编码是否正确。",
                references=[],
                confidence=0,
                sources_count=0,
            )

        # 格式化库存信息
        lines = [f"查到 {len(results)} 个匹配的备件库存：\n"]
        for sp in results:
            qty = sp.stock_quantity
            safety = sp.safety_stock
            if qty <= 0:
                status = "缺货"
            elif qty <= safety:
                status = "低库存"
            else:
                status = "充足"
            lines.append(
                f"- **{sp.part_name}**（{sp.part_code}）\n"
                f"  库存: {qty} {sp.unit} | 安全库存: {safety} | 状态: {status}"
            )
            if sp.specification:
                lines[-1] += f" | 规格: {sp.specification}"
            if sp.location:
                lines[-1] += f" | 存放: {sp.location}"
            lines.append("")

        return AnswerResult(
            question=question,
            answer="\n".join(lines).strip(),
            references=[],
            confidence=0,
            sources_count=0,
        )

    def _extract_part_keywords(self, question: str) -> list:
        """从问题中提取可能的备件关键词"""
        # 常见备件名称列表（可作为关键词索引）
        known_parts = [
            "保险丝", "传感器", "继电器", "轴承", "密封圈", "电机", "泵",
            "滤芯", "螺丝", "密封垫", "加热器", "温控器", "电磁阀", "液压油",
            "润滑油", "齿轮", "皮带", "弹簧", "开关", "接触器",
            "电池", "模块", "电源", "电缆", "风扇", "散热", "油封",
            "定位销", "包胶", "刀库", "刀具", "滚筒", "托辊",
        ]
        found = []
        for kw in known_parts:
            if kw in question:
                found.append(kw)
        # 如果没有命中已知列表，尝试提取问题中的连续2-3字词作为搜索词
        if not found:
            import re
            tokens = re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9\-]+', question)
            # 清理干扰词
            noise_words = {"库存", "备件", "零件", "配件", "还有多少", "还剩多少",
                          "查一下", "看一下", "帮我", "查询", "还有", "多少",
                          "数量", "剩下", "够不够", "缺不缺", "有没有", "查"}
            for t in tokens:
                if len(t) >= 2 and t not in noise_words:
                    found.append(t)

        # 清理关键词：去掉末尾常见的干扰词，提升匹配准确率
        cleaned = []
        noise_suffixes = ["库存", "记录", "备件", "零件", "配件"]
        for term in found[:10]:
            for suffix in noise_suffixes:
                if term.endswith(suffix) and len(term) > len(suffix):
                    term = term[:-len(suffix)]
                    break
            cleaned.append(term)

        return cleaned[:5]  # 最多5个搜索词

    _NON_TECHNICAL_KEYWORDS = [
        "你好", "你好吗", "你是谁", "你叫什么", "你能做什么", "你有什么功能",
        "功能", "介绍", "帮助", "help", "hello", "hi", "你好",
        "谢谢", "感谢", "再见", "拜拜", "测试",
    ]

    def _is_technical_query(self, question: str) -> bool:
        """判断用户问题是否为设备维修相关的技术问题"""
        q = question.strip().lower()
        # 问候/功能询问/闲聊类直接拦截
        for kw in self._NON_TECHNICAL_KEYWORDS:
            if kw in q:
                return False
        # 明显非技术问题模式
        non_tech_patterns = ["你是", "你能", "你的", "功能有", "作用有", "介绍一下"]
        for p in non_tech_patterns:
            if p in q:
                return False
        return True

    def answer(self, question: str, cases: List[Dict]) -> AnswerResult:
        """
        基于历史案例回答用户问题

        Args:
            question: 用户的问题
            cases: 检索到的历史案例列表

        Returns:
            AnswerResult 包含分析回答和参考案例
        """
        # 非技术问题 → 直接回答，不参考案例
        if not self._is_technical_query(question):
            return AnswerResult(
                question=question,
                answer=self._answer_non_technical(question),
                references=[],
                confidence=0.0,
                sources_count=0,
            )

        # 技术问题但无匹配案例
        if not cases:
            return AnswerResult(
                question=question,
                answer="未检索到与该问题相关的历史案例。请尝试使用更具体的设备型号或故障描述重新提问。",
                references=[],
                confidence=0.0,
                sources_count=0,
            )

        # 案例相关度过低 → 视为无匹配
        max_score = max((c.get("score", 0) for c in cases), default=0)
        if max_score < self.SCORE_THRESHOLD:
            return AnswerResult(
                question=question,
                answer="未检索到与该问题相关的历史案例。请尝试使用更具体的设备型号或故障描述重新提问。",
                references=[],
                confidence=0.0,
                sources_count=0,
            )

        # 技术问题 + 有案例 → 完整回答
        reference_cases = []
        for c in cases:
            reference_cases.append(ReferenceCase(
                knowledge_id=c.get("knowledge_id") or c.get("id", 0),
                title=c.get("title", ""),
                content=c.get("content", "")[:300],
                device_type=c.get("device_type", ""),
                fault_code=c.get("fault_code", ""),
                score=c.get("score", 0),
                summary=self._generate_case_summary(c),
            ))

        try:
            answer_text, thinking = self._generate_answer(question, cases)
            confidence = self._estimate_confidence(cases)

            return AnswerResult(
                question=question,
                answer=answer_text,
                references=reference_cases,
                confidence=confidence,
                sources_count=len(reference_cases),
                thinking_process=thinking,
            )
        except Exception as e:
            logger.error(f"[AnswerGenerator] 回答生成失败: {e}")
            return AnswerResult(
                question=question,
                answer=f"回答生成失败，请稍后重试。错误: {str(e)[:200]}",
                references=reference_cases,
                confidence=0.0,
                sources_count=len(reference_cases),
            )

    def _generate_answer(self, question: str, cases: List[Dict]):
        """基于检索案例调用 LLM 生成回答（非流式），返回 (回答文本, 思考过程)"""
        cases_text = ""
        for i, c in enumerate(cases[:5], 1):
            title = c.get("title", "")
            content = c.get("content", "")[:1500]
            score = c.get("score", 0)
            device_type = c.get("device_type", "")
            fault_code = c.get("fault_code", "")
            # 来源标注：手册条目带出处（手册名/章节/页码/错误码），工单案例标 CASE
            if c.get("manual_code_id"):
                source = "手册"
                cite = f"（{c.get('manual_name', '')}·{c.get('chapter', '')}·{c.get('page', '')}·错误码 {c.get('error_code', '')}）"
            else:
                source = "工单案例"
                cite = ""
            # 手册条目：严重度独立成行，防长 content 截断后 LLM 丢失该信息
            sev_line = ""
            if c.get("manual_code_id") and c.get("severity"):
                sev_label = {"EX": "EX 急停级", "OH": "OH 停机级", "INFO": "INFO 提示级"}.get(c.get("severity"), c.get("severity"))
                sev_line = f"- 严重度: {sev_label}（{c.get('effect', '')}）\n"
            cases_text += f"""
### 案例 {i}（相关度: {score:.0%} · 来源: {source} {cite}）
- 标题: {title}
- 设备类型: {device_type}
- 故障码: {fault_code}
{sev_line}- 内容:
{content}

"""

        user_prompt = f"""## 用户问题
{question}

## 检索案例
{cases_text}

## 回答指令
1. 上述案例已由检索系统筛选，均与用户问题相关
2. 请根据问题类型选择对应的回答格式（参考系统提示中的「问题类型判断」）
3. 分数来自检索系统，不得修改
4. 严格基于案例内容回答，不添加案例中没有的信息"""

        with tracer.trace("answer_generation", metadata={
            "question": question,
            "cases_count": len(cases),
        }) as trace_ctx:
            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]
            response = self.llm.invoke(messages)
            answer_text = response.content if hasattr(response, "content") else str(response)
            thinking = answer_text[:200]  # 记录回答开头作为思考过程
            trace_ctx.score("answer_confidence", self._estimate_confidence(cases))
            return answer_text.strip(), thinking

    def _answer_non_technical(self, question: str) -> str:
        """处理非技术类问题"""
        q = question.strip()
        if any(kw in q for kw in ["你好", "hello", "hi"]):
            return "您好！我是 Smart-Repair-System 的智能问答助手。您可以向我描述设备故障现象，我会从历史维修案例中匹配最相关的解决方案，为您提供分析建议。"
        if any(kw in q for kw in ["功能", "能做", "作用", "介绍"]):
            return (
                "我是 Smart-Repair-System 的 AI 问答助手，主要功能包括：\n\n"
                "1. **故障诊断分析** — 描述设备故障现象，我检索历史案例给出分析\n"
                "2. **维修方案推荐** — 基于相似案例推荐排查步骤和处理方法\n"
                "3. **案例参考** — 展示相关历史维修案例供您参考\n"
                "4. **库存查询** — 发送「保险丝还有多少」等，查询备件库存\n"
                "5. **工单查询** — 发送工单号或「我的待办」，查询工单状态与名下任务\n\n"
                "您可以这样提问：\n"
                "- 「电机异响怎么处理」\n"
                "- 「注塑机温度偏高报警什么原因」\n"
                "- 「液压系统漏油如何排查」\n"
                "- 「保险丝还有多少」\n"
                "- 「WO-20260804-001 工单进度」\n"
                "- 「我的待办」"
            )
        if any(kw in q for kw in ["谢谢", "感谢"]):
            return "不客气，随时为您服务！如有设备故障问题，请直接描述现象。"
        if any(kw in q for kw in ["再见", "拜拜"]):
            return "再见！如有设备问题随时找我。"
        return f"您好！请描述您遇到的设备故障现象，我会为您检索相关的维修案例并给出分析建议。"

    def stream_answer(self, question: str, cases: List[Dict], emit_done: bool = True):
        """
        流式生成回答 - 返回一个生成器，逐 token yield

        Args:
            question: 用户问题
            cases: 检索案例列表
            emit_done: 是否发送完成信号（False 时由调用方发送，避免重复）

        Yields:
            str: SSE 格式的消息片段
        """
        # 非技术问题 → 直接返回
        if not self._is_technical_query(question):
            answer = self._answer_non_technical(question)
            yield f"data: {json.dumps({'type': 'answer', 'content': answer}, ensure_ascii=False)}\n\n"
            if emit_done:
                yield f"data: {json.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return

        # 无案例 → 直接返回
        if not cases:
            answer = "未检索到与该问题相关的历史案例。请尝试使用更具体的设备型号或故障描述重新提问。"
            yield f"data: {json.dumps({'type': 'answer', 'content': answer}, ensure_ascii=False)}\n\n"
            if emit_done:
                yield f"data: {json.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return

        # 案例相关度过低 → 视为无匹配
        max_score = max((c.get("score", 0) for c in cases), default=0)
        if max_score < self.SCORE_THRESHOLD:
            answer = "未检索到与该问题相关的历史案例。请尝试使用更具体的设备型号或故障描述重新提问。"
            yield f"data: {json.dumps({'type': 'answer', 'content': answer}, ensure_ascii=False)}\n\n"
            if emit_done:
                yield f"data: {json.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return

        # 构建 prompt
        cases_text = ""
        for i, c in enumerate(cases[:5], 1):
            title = c.get("title", "")
            content = c.get("content", "")[:1500]
            score = c.get("score", 0)
            device_type = c.get("device_type", "")
            fault_code = c.get("fault_code", "")
            # 来源标注：手册条目带出处（手册名/章节/页码/错误码），工单案例标 CASE
            if c.get("manual_code_id"):
                source = "手册"
                cite = f"（{c.get('manual_name', '')}·{c.get('chapter', '')}·{c.get('page', '')}·错误码 {c.get('error_code', '')}）"
            else:
                source = "工单案例"
                cite = ""
            # 手册条目：严重度独立成行，防长 content 截断后 LLM 丢失该信息
            sev_line = ""
            if c.get("manual_code_id") and c.get("severity"):
                sev_label = {"EX": "EX 急停级", "OH": "OH 停机级", "INFO": "INFO 提示级"}.get(c.get("severity"), c.get("severity"))
                sev_line = f"- 严重度: {sev_label}（{c.get('effect', '')}）\n"
            cases_text += f"""
### 案例 {i}（相关度: {score:.0%} · 来源: {source} {cite}）
- 标题: {title}
- 设备类型: {device_type}
- 故障码: {fault_code}
{sev_line}- 内容:
{content}

"""

        user_prompt = f"""## 用户问题
{question}

## 检索案例
{cases_text}

## 回答指令
1. 上述案例已由检索系统筛选，均与用户问题相关
2. 请根据问题类型选择对应的回答格式（参考系统提示中的「问题类型判断」）
3. 分数来自检索系统，不得修改
4. 严格基于案例内容回答，不添加案例中没有的信息"""

        # 发送 thinking 事件
        yield f"data: {json.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

        try:
            with tracer.trace("answer_generation", metadata={
                "question": question,
                "cases_count": len(cases),
            }) as trace_ctx:
                messages = [
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ]

                full_text = ""
                for chunk in self.llm.stream(messages):
                    token = chunk.content if hasattr(chunk, 'content') else str(chunk)
                    if token:
                        full_text += token
                        yield f"data: {json.dumps({'type': 'answer', 'content': token}, ensure_ascii=False)}\n\n"

                confidence = self._estimate_confidence(cases)
                trace_ctx.score("answer_confidence", confidence)

        except Exception as e:
            logger.error(f"[AnswerGenerator] 流式生成失败: {e}")
            yield f"data: {json.dumps({'type': 'answer', 'content': f'回答生成失败，请稍后重试。'}, ensure_ascii=False)}\n\n"

        # 发送完成信号
        if emit_done:
            yield f"data: {json.dumps({'type': 'done', 'confidence': self._estimate_confidence(cases), 'sources_count': len(cases)}, ensure_ascii=False)}\n\n"

    def stream_answer_multi(self, question: str, faults: List[Dict], emit_done: bool = True):
        """
        多故障分组流式回答 - 按故障分节生成（专家模式多故障专用）

        Args:
            question: 用户原始问题
            faults: [{"name": "子查询/故障名", "cases": [case dict]}]

        Yields:
            str: SSE 格式的消息片段（与 stream_answer 协议一致）
        """
        # 非技术问题 → 直接返回
        if not self._is_technical_query(question):
            answer = self._answer_non_technical(question)
            yield f"data: {json.dumps({'type': 'answer', 'content': answer}, ensure_ascii=False)}\n\n"
            if emit_done:
                yield f"data: {json.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return

        # 没有任何案例或相关度过低 → 视为无匹配
        all_cases = [c for f in faults for c in f.get("cases", [])]
        max_score = max((c.get("score", 0) for c in all_cases), default=0)
        if not all_cases or max_score < self.SCORE_THRESHOLD:
            answer = "未检索到与该问题相关的历史案例。请尝试使用更具体的设备型号或故障描述重新提问。"
            yield f"data: {json.dumps({'type': 'answer', 'content': answer}, ensure_ascii=False)}\n\n"
            if emit_done:
                yield f"data: {json.dumps({'type': 'done', 'confidence': 0, 'sources_count': 0}, ensure_ascii=False)}\n\n"
            return

        # 构建按故障分组的案例文本（每个故障独立小节，缺案例的故障显式标注）
        faults_text = ""
        for i, f in enumerate(faults, 1):
            name = f.get("name", f"故障{i}")
            cases = f.get("cases", [])
            faults_text += f"\n## 故障{i}: {name}\n"
            if not cases:
                faults_text += "（该故障未检索到案例）\n"
                continue
            for j, c in enumerate(cases[:5], 1):
                title = c.get("title", "")
                content = c.get("content", "")[:1500]
                score = c.get("score", 0)
                device_type = c.get("device_type", "")
                fault_code = c.get("fault_code", "")
                faults_text += f"""
### 案例 {j}（相关度: {score:.0%}）
- 标题: {title}
- 设备类型: {device_type}
- 故障码: {fault_code}
- 内容:
{content}
"""

        user_prompt = f"""## 用户问题
{question}

## 按故障分组的检索案例
{faults_text}

## 回答指令
1. 按上述"按故障分组的检索案例"输出各故障小节，每个故障的小节只引用该故障自己的案例
2. 有故障无案例时，必须显式说明未检索到案例
3. 严格基于案例内容回答，不添加案例中没有的信息"""

        yield f"data: {json.dumps({'type': 'thinking'}, ensure_ascii=False)}\n\n"

        try:
            with tracer.trace("answer_generation_multi", metadata={
                "question": question,
                "faults_count": len(faults),
            }) as trace_ctx:
                messages = [
                    SystemMessage(content=self.MULTI_FAULT_PROMPT),
                    HumanMessage(content=user_prompt),
                ]
                for chunk in self.llm.stream(messages):
                    token = chunk.content if hasattr(chunk, 'content') else str(chunk)
                    if token:
                        yield f"data: {json.dumps({'type': 'answer', 'content': token}, ensure_ascii=False)}\n\n"
                confidence = self._estimate_confidence(all_cases)
                trace_ctx.score("answer_confidence", confidence)
        except Exception as e:
            logger.error(f"[AnswerGenerator] 多故障流式生成失败: {e}")
            yield f"data: {json.dumps({'type': 'answer', 'content': '回答生成失败，请稍后重试。'}, ensure_ascii=False)}\n\n"

        # 发送完成信号
        if emit_done:
            yield f"data: {json.dumps({'type': 'done', 'confidence': self._estimate_confidence(all_cases), 'sources_count': len(all_cases)}, ensure_ascii=False)}\n\n"



    def _generate_case_summary(self, case: Dict) -> str:
        """生成案例摘要"""
        title = case.get("title", "")
        content = case.get("content", "")
        lines = content.split("\n")
        summary_parts = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 20:
                summary_parts.append(line[:80])
                if len(summary_parts) >= 2:
                    break
        if not summary_parts:
            summary_parts.append(content[:100])
        return " | ".join(summary_parts)

    def _estimate_confidence(self, cases: List[Dict]) -> float:
        """估算回答匹配度（基于检索案例与问题的相关度）"""
        if not cases:
            return 0.0
        scores = [c.get("score", 0) for c in cases]
        max_score = max(scores)
        avg_score = sum(scores) / len(scores)
        count_factor = min(len(cases) / 3.0, 1.0)
        base_confidence = (max_score * 0.6 + avg_score * 0.4)
        confidence = min(base_confidence * (0.5 + count_factor * 0.5), 1.0)
        return round(confidence, 2)


answer_generator = AnswerGenerator()
