"""GuidedRepairAgent - 追踪维修引导 Agent

功能：
- 逐步引导维修员排查故障
- 每步基于知识库检索 + 用户反馈动态调整诊断方向
- 返回结构化选项供维修员选择执行
"""
import json
import time
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from loguru import logger

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage
from app.core.config import settings
from app.core.langfuse_tracer import tracer


# ============================================================
# 会话内无关消息拦截（追踪维修对话中的闲聊/非维修内容）
# ============================================================
_REPAIR_RELATED_KEYWORDS = (
    # 设备
    "注塑机", "数控", "机床", "液压", "传送带", "空压机", "压缩机", "变压器", "电机",
    "电动机", "锅炉", "制冷", "机器人", "PLC", "传感器", "继电器", "变频器", "伺服",
    "驱动器", "主轴", "刀库", "轴承", "齿轮", "油泵", "水泵", "气泵", "马达", "气缸",
    "油缸", "阀门", "开关", "电源", "线路", "电路", "主板", "屏幕", "电池", "设备",
    "机组", "机器", "装置", "密封圈", "滤芯", "皮带", "链条",
    # 故障现象
    "温度", "压力", "电压", "电流", "报警", "异响", "振动", "漏油", "漏水", "死机",
    "黑屏", "不转", "不启动", "跳闸", "过热", "过载", "堵塞", "卡死", "断电", "短路",
    "故障", "坏了", "异常", "无响应", "停机", "不工作", "松动", "磨损", "烧毁", "冒烟",
    "异味", "抖动", "卡顿", "闪退", "失灵", "渗油", "红灯",
    # 排查反馈
    "检查", "正常", "更换", "清理", "调整", "测试", "开机", "重启", "好了", "解决",
    "试机", "运行", "恢复", "排除", "确认", "测量", "紧固", "校正", "运转", "复位",
    "清洗", "加油", "换油", "拆卸", "安装",
)

# 简短应答词：排查过程中的跟进性回复，放行避免打断节奏
_SHORT_ACK_WORDS = (
    "嗯", "好", "好的", "行", "可以", "继续", "然后", "下一步", "接下来", "对",
    "是的", "ok", "OK", "试过了", "查了", "拆了", "装了", "换了", "清了", "加了",
    "检查了",
)

_IRRELEVANT_REPLY = ("这条消息和设备维修无关，我先不继续排查。\n"
                     "如果是设备故障，请描述具体的设备和故障现象，例如："
                     "注塑机温度过高、空压机不启动、PLC 报错。")


def _is_repair_irrelevant(message: str) -> bool:
    """判断追踪维修会话内的消息是否与设备维修无关（闲聊拦截）"""
    text = (message or "").strip()
    if not text:
        return True
    if any(kw in text for kw in _REPAIR_RELATED_KEYWORDS):
        return False
    if len(text) <= 4 and any(kw in text for kw in _SHORT_ACK_WORDS):
        return False
    return True


@dataclass
class RepairOption:
    """维修排查选项"""
    id: str = ""
    cause: str = ""
    diagnostic_action: str = ""
    reference_case: str = ""  # 参考案例标题


@dataclass
class GuidedRepairStep:
    """单步引导结果"""
    session_id: str = ""
    step: int = 0
    message: str = ""
    options: List[RepairOption] = field(default_factory=list)
    status: str = "awaiting_action"  # awaiting_action / completed
    summary: str = ""


class GuidedRepairAgent:
    """追踪维修引导 Agent"""

    SYSTEM_PROMPT = """你是一个设备维修引导专家。你的职责是逐步引导维修员排查和修复设备故障。

## 工作流程
1. 根据维修员描述的故障现象，结合检索到的历史案例，给出当前最可能的 2-3 个排查方向
2. 每个方向必须附带具体的操作指引（不是泛泛的"检查XX"，而是"用万用表测量XX端子电压，正常应为YY V"）
3. 维修员选择一个方向执行后会反馈结果，你根据反馈调整下一步诊断
4. 不要一次给出所有可能的原因，引导维修员按优先级逐步排查

## 规则
- 每步只能给 2-3 个排查方向，不要超过 3 个
- **严格引用知识库**：排查方向、测量方法、正常范围、判断标准只能来自检索到的【参考案例】中明确写到的内容；案例没有的细节（灯名、部件名、型号、数值、排查方法）一律不得补充或推断，禁止使用自己的经验与通用常识
- 优先引导排查最常见、最容易验证的原因
- 如果维修员反馈"问题解决"，立即结束并生成维修总结
- 如果检索案例中有匹配的案例，优先参考案例中的排查步骤
- 最多引导 8 步，超过后自动总结当前进展

## 输出格式（严格 JSON）
{
  "message": "根据你描述的XXX现象，结合历史案例，当前最可能的排查方向如下：",
  "options": [
    {
      "id": "A",
      "cause": "故障原因简述",
      "diagnostic_action": "具体操作步骤，包含检查方法、测量参数、正常范围、判断标准"
    }
  ],
  "status": "awaiting_action"
}

如果问题已解决，输出：
{
  "message": "问题已解决！",
  "options": [],
  "summary": "故障原因：XXX。处理方法：XXX。检查项：XXX。",
  "status": "completed"
}"""

    _SESSION_TTL = 24 * 3600  # 会话有效期 24 小时（Redis TTL），覆盖跨班次/跨天排查
    _SESSION_KEY_PREFIX = "guided_repair_session:"

    def __init__(self):
        self._llm: Optional[ChatOpenAI] = None

    def _load_session(self, session_id: str) -> Optional[Dict]:
        """从 Redis 加载会话（Redis 不可用时由 cache_service 自动降级内存缓存）"""
        try:
            from app.core.cache_service import cache_service
            return cache_service.get(f"{self._SESSION_KEY_PREFIX}{session_id}")
        except Exception as e:
            logger.warning(f"[GuidedRepair] 会话加载失败: {e}")
            return None

    def _save_session(self, session_id: str, data: Dict):
        """保存会话到 Redis（TTL 2 小时），解决重启/多进程丢失会话问题"""
        try:
            from app.core.cache_service import cache_service
            cache_service.set(f"{self._SESSION_KEY_PREFIX}{session_id}", data, ttl=self._SESSION_TTL)
        except Exception as e:
            logger.warning(f"[GuidedRepair] 会话保存失败: {e}")

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
                temperature=0.5,
                streaming=True,
                timeout=60,            # 单轮引导生成超时 60s，超时给用户可感知的失败提示
                max_retries=2,
            )
        return self._llm

    def start_session(self, description: str, device_type: str = "") -> str:
        """创建新会话，返回 session_id（会话持久化到 Redis）"""
        import uuid
        sid = str(uuid.uuid4())[:8]
        self._save_session(sid, {
            "device_type": device_type,
            "initial_symptoms": description,
            "history": [],
            "status": "diagnosing",
            "created_at": time.time(),
        })
        return sid

    def _search_knowledge(self, query: str, device_type: str = "") -> List[Dict]:
        """检索知识库，返回匹配案例"""
        try:
            from app.agents.tools import RetrievalTools
            from app.core.database import SessionLocal
            from app.core.vector_store import vector_store
            from app.core.embeddings import encode_text
            tools = RetrievalTools(
                db_session_factory=SessionLocal,
                vector_store=vector_store,
                embedding_fn=encode_text,
            )
            v_result = tools.vector_search(query, top_k=5, device_type=device_type, score_threshold=0.0)
            b_result = tools.bm25_search(query, top_k=5, device_type=device_type)

            result_sets = []
            if v_result.success:
                result_sets.append(v_result.data)
            if b_result.success:
                result_sets.append(b_result.data)

            from app.agents.tools import rrf_merge, weighted_rerank
            merged = rrf_merge(result_sets, top_n=5) if result_sets else []
            merged = [m for m in merged if not m.get("rrf_only", False) and m.get("score", 0) >= 0.15]
            cleaned_q = tools.query_extractor.extract(query, use_llm_fallback=False)
            merged = weighted_rerank(merged, query, fault_weight=0.4, device_penalty=0.15,
                                     cleaned_query=cleaned_q)
            merged.sort(key=lambda x: x.get("score", 0), reverse=True)
            return merged[:3]
        except Exception as e:
            logger.error(f"[GuidedRepair] 知识检索失败: {e}")
            return []

    def start_diagnosis(self, description: str, device_type: str = "") -> GuidedRepairStep:
        """开始诊断：检索案例 + 生成初始排查方向"""
        session_id = self.start_session(description, device_type)

        # 检索知识库
        cases = self._search_knowledge(description, device_type)

        # 构建案例文本
        cases_text = ""
        for i, c in enumerate(cases, 1):
            cases_text += f"""
### 参考案例 {i}（相关度: {c.get('score', 0):.0%}）
- 标题: {c.get('title', '')}
- 故障码: {c.get('fault_code', '')}
- 内容: {(c.get('content', '') or '')[:800]}
"""

        user_prompt = f"""## 设备故障描述
{description}
设备类型: {device_type or '未指定'}

## 检索到的历史案例（唯一知识来源：只能引用其中明确写到的内容，不得补充案例外的信息）
{cases_text if cases_text else '未检索到匹配案例。请如实告知维修员：知识库中暂无相关历史案例，建议联系资深工程师或提交新案例。'}

## 任务
请给出第一步排查方向（2-3个选项），优先参考历史案例中的排查步骤。返回 JSON。"""

        try:
            with tracer.trace("guided_repair_start", metadata={
                "description": description,
                "device_type": device_type,
                "cases_count": len(cases),
            }):
                response = self.llm.invoke([
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ])
                result = self._parse_response(response.content)

                step = GuidedRepairStep(
                    session_id=session_id,
                    step=1,
                    message=result.get("message", ""),
                    options=[RepairOption(**o) for o in result.get("options", [])],
                    status=result.get("status", "awaiting_action"),
                    summary=result.get("summary", ""),
                )

                # 记录会话（持久化到 Redis）
                session = self._load_session(session_id) or {"history": [], "status": "diagnosing"}
                session.setdefault("history", [])
                session["history"].append({
                    "step": 1,
                    "type": "diagnosis",
                    "user_input": description,
                    "ai_options": [{"id": o.id, "cause": o.cause} for o in step.options],
                    "cases_used": [c.get("title", "") for c in cases],
                })
                session["status"] = step.status
                self._save_session(session_id, session)

                return step

        except Exception as e:
            logger.error(f"[GuidedRepair] 启动诊断失败: {e}")
            return GuidedRepairStep(
                session_id=session_id,
                step=1,
                message=f"诊断启动失败: {str(e)[:100]}",
                options=[],
                status="awaiting_action",
            )

    def next_step(self, session_id: str, selected_option: str, action_taken: str,
                  device_status: str) -> GuidedRepairStep:
        """处理维修员反馈，返回下一步诊断"""
        session = self._load_session(session_id)
        if not session:
            return GuidedRepairStep(
                session_id=session_id,
                step=0,
                message="会话不存在或已过期，请重新开始。",
                options=[],
                status="completed",
            )

        step_num = len(session["history"]) + 1
        if step_num > 8:
            return GuidedRepairStep(
                session_id=session_id,
                step=step_num,
                message="已达到最大排查步骤（8步）。建议根据已完成排查的情况联系资深工程师进一步分析。",
                options=[],
                summary=self._generate_final_summary(session),
                status="completed",
            )

        # 检测是否已解决
        solved_keywords = ["解决", "正常", "恢复", "好了", "可以", "完成", "ok", "没问题", "修复"]
        is_solved = any(kw in device_status for kw in solved_keywords) or any(kw in action_taken for kw in solved_keywords)

        if is_solved:
            summary = self._generate_success_summary(session, selected_option, action_taken, device_status)
            session["history"].append({
                "step": step_num,
                "type": "result",
                "selected_option": selected_option,
                "action_taken": action_taken,
                "device_status": device_status,
                "resolved": True,
            })
            session["status"] = "completed"
            self._save_session(session_id, session)
            return GuidedRepairStep(
                session_id=session_id,
                step=step_num,
                message="问题已解决！以下是维修总结：",
                options=[],
                summary=summary,
                status="completed",
            )

        # 检索知识库获取新方向
        search_query = f"{session['initial_symptoms']} {device_status}"
        cases = self._search_knowledge(search_query, session.get("device_type", ""))

        # 构建对话历史
        history_text = ""
        for h in session["history"]:
            if h.get("type") == "diagnosis":
                history_text += f"步骤{h['step']}: 用户描述「{h['user_input']}」→ AI 给出选项: {', '.join(o['cause'] for o in h.get('ai_options', []))}\n"
            else:
                history_text += f"步骤{h['step']}: 选择「{h.get('selected_option', '')}」→ 执行: {h.get('action_taken', '')} → 设备状态: {h.get('device_status', '')}\n"

        cases_text = ""
        for i, c in enumerate(cases, 1):
            cases_text += f"### 参考案例 {i}: {c.get('title', '')}\n{(c.get('content', '') or '')[:600]}\n\n"

        user_prompt = f"""## 设备信息
初始故障: {session['initial_symptoms']}
设备类型: {session.get('device_type', '未指定')}

## 排查历史
{history_text}

## 当前操作反馈
维修员选择了「{selected_option}」，执行了: {action_taken}
执行后设备状态: {device_status}

## 检索到的匹配案例（唯一知识来源：只能引用其中明确写到的内容，不得补充案例外的信息）
{cases_text if cases_text else '未检索到匹配案例。请如实告知维修员：知识库中暂无相关历史案例，建议联系资深工程师或提交新案例。不得自行编造排查步骤。'}

## 任务
根据以上信息，设备问题尚未解决，请给出下一步排查方向（2-3个选项）。结合历史案例和当前设备状态调整方向。返回 JSON。"""

        try:
            with tracer.trace("guided_repair_step", metadata={
                "session_id": session_id,
                "step": step_num,
                "selected_option": selected_option,
            }):
                response = self.llm.invoke([
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ])
                result = self._parse_response(response.content)

                step = GuidedRepairStep(
                    session_id=session_id,
                    step=step_num,
                    message=result.get("message", ""),
                    options=[RepairOption(**o) for o in result.get("options", [])],
                    status=result.get("status", "awaiting_action"),
                    summary=result.get("summary", ""),
                )

                session["history"].append({
                    "step": step_num,
                    "type": "result",
                    "selected_option": selected_option,
                    "action_taken": action_taken,
                    "device_status": device_status,
                    "resolved": False,
                    "ai_options": [{"id": o.id, "cause": o.cause} for o in step.options],
                })
                session["status"] = step.status
                self._save_session(session_id, session)

                return step

        except Exception as e:
            logger.error(f"[GuidedRepair] 步骤生成失败: {e}")
            return GuidedRepairStep(
                session_id=session_id,
                step=step_num,
                message=f"步骤生成失败: {str(e)[:100]}",
                options=[],
                status="awaiting_action",
            )

    def _parse_response(self, content: str) -> dict:
        """解析 LLM 返回的 JSON"""
        try:
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
            return json.loads(text)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[GuidedRepair] JSON 解析失败: {e}, raw: {content[:300]}")
            return {"message": content[:500], "options": [], "status": "awaiting_action"}

    def _generate_success_summary(self, session: dict, selected_option: str,
                                   action_taken: str, device_status: str) -> str:
        """生成维修成功总结"""
        lines = [f"**故障现象**: {session['initial_symptoms']}", ""]
        lines.append(f"**排查步骤**: 共 {len(session['history']) + 1} 步")
        for i, h in enumerate(session["history"]):
            if h.get("type") == "diagnosis":
                lines.append(f"  步骤{i+1}: 初始诊断 -> AI 给出排查方向")
            else:
                opt = h.get("selected_option", "")
                act = h.get("action_taken", "")
                lines.append(f"  步骤{i+1}: 选择「{opt}」-> {act}")
        lines.append(f"  最终步骤: 选择「{selected_option}」-> {action_taken}")
        lines.append("")
        lines.append(f"**处理结果**: {device_status}")
        lines.append("")
        lines.append(f"**最终原因**: {selected_option}")
        return "\n".join(lines)

    def _generate_final_summary(self, session: dict) -> str:
        """生成未解决时的最终总结"""
        lines = [f"**故障现象**: {session['initial_symptoms']}", ""]
        lines.append("**已排查项目**:")
        for i, h in enumerate(session["history"]):
            if h.get("type") == "result":
                lines.append(f"  - {h.get('selected_option', '')}: {h.get('action_taken', '')}")
        lines.append("")
        lines.append("**建议**: 已达最大排查步数，建议联系资深工程师进一步分析。")
        return "\n".join(lines)


    # === 对话式追踪（纯聊天，无选项卡片） ===

    CHAT_SYSTEM_PROMPT = """你是一个设备维修引导专家。你的职责是通过**多轮对话**逐步引导维修员排查和修复设备故障。

## 核心原则（必须严格遵守）
1. 你与"问答模式"完全不同！问答模式是一次性给出完整分析。你的工作是**一步一步引导**，每轮对话只说一件事。
2. **必须严格基于知识库案例回答，禁止任何自由发挥**：
   - 【分析】和【操作】只能引用"知识库参考"中【参考案例】明确写到的内容（故障现象、原因、排查步骤、测量方法、判断标准），其余任何细节（灯名、部件名、型号、数值、排查方法）一律不得补充、推断或想象，不得使用自己的经验与通用常识。
   - 案例内容不足时，只能基于案例已有内容组织回答；确实没有对应内容时如实说明"知识库案例未覆盖该细节"。
   - 如果知识库参考为"未检索到匹配案例"，你必须如实告知维修员"知识库中暂无相关历史案例，建议联系资深工程师或提交新案例"，不得自行编造排查步骤或使用通用经验。

## 首次对话（维修员刚描述故障现象时）
1. 用 1-2 句话确认你理解了故障现象
2. **先做分析**：解释为什么你怀疑这个方向，结合故障现象和检索案例说明推理依据
3. 给出**唯一一个**最先应该检查的方向
4. 附上具体操作指引（测哪里、怎么测、正常值是多少、异常时说明什么）
5. **严禁**列出"可能原因 1、2、3"或"排查方向 1、2、3"
6. **严禁**在一个回复中给出完整排查流程

## 后续对话（维修员反馈了检查结果）
1. **先分析反馈**：解读维修员的操作结果说明了什么（正常/异常分别代表什么）
2. 根据反馈和推理，给出**唯一一个**下一步检查方向
3. **不要再重复已经排除的方向**
4. 不要在新回复中重新列举之前的故障原因

## 每次回复的格式
你的每次回复都应包含以下两部分：
【分析】解释当前步骤的推理逻辑（1-2句），让维修员理解"为什么查这个"
【操作】给出具体的一个排查步骤，附带检查方法和判断标准

## 问题解决时
- 明确说"问题已解决！"，用 2-3 句话总结故障原因和处理方法即可
- 不需要重新写完整的"问题分析-可能原因-排查方向-处理方案-预防建议"

## 最多 8 步
超过 8 步还没解决，就说"建议将目前排查情况提交给资深工程师进一步分析"

## 回答风格
- 像一位有经验的老师傅在带徒弟，口语化但专业
- 不要说"根据检索案例"，不要说"相关度 XX%"
- 不要带置信度、分数等指标

## 反面示例（绝对禁止的回复格式）
"1. 问题分析：... 2. 可能原因：(1) ... (2) ... 3. 排查方向：... 4. 处理方案：... 5. 预防建议：..."
这是问答模式的格式，追踪模式下绝对不能用！"""

    def chat(self, session_id: str, message: str, device_type: str = "") -> str:
        """对话式追踪：用户发消息，AI 流式回复"""
        # 无关消息拦截：闲聊/与维修无关的内容不进入排查对话
        if _is_repair_irrelevant(message):
            yield AIMessageChunk(content=_IRRELEVANT_REPLY)
            return
        # 获取或创建会话（Redis 持久化）
        session = self._load_session(session_id)
        is_new = session is None
        if is_new:
            session = {
                "device_type": device_type,
                "initial_symptoms": message,
                "chat_history": [],
                "status": "diagnosing",
                "created_at": time.time(),
                "step_count": 0,
            }
        session["step_count"] += 1

        # 检索知识库
        search_query = f"{session['initial_symptoms']} {message}"
        cases = self._search_knowledge(search_query, session.get("device_type", ""))

        # 构建案例文本（缩短内容，只取关键信息，避免 LLM 复制完整流程）
        cases_text = ""
        for i, c in enumerate(cases, 1):
            content = (c.get('content', '') or '')[:600]
            cases_text += f"\n【参考案例{i}】{c.get('title', '')}\n故障原因: （从案例中提取）\n处理要点: {content}\n"

        # 构建对话历史
        history_text = ""
        for h in session.get("chat_history", []):
            history_text += f"\n维修员: {h['user']}\n你: {h['ai']}\n"

        # 首次对话 vs 后续对话使用不同的 prompt
        if is_new:
            user_prompt = f"""## 维修员描述
{message}
设备类型: {device_type or '未指定'}

## 知识库参考（唯一知识来源：只能引用其中明确写到的内容，不得补充案例外的信息）
{cases_text if cases_text else '未检索到匹配案例。请如实告知维修员：知识库中暂无相关历史案例，建议联系资深工程师或提交新案例。不得自行编造排查步骤。'}

## 任务
这是**首次对话**。维修员刚描述了故障现象。请：
1. 用 1-2 句话确认你理解了问题
2. 给出第一个具体的排查步骤（只说一步）
3. 不要列"可能原因"清单，不要给完整排查流程"""
        else:
            user_prompt = f"""## 维修员反馈
{message}

## 对话历史
{history_text}

## 知识库参考（唯一知识来源：只能引用其中明确写到的内容，不得补充案例外的信息）
{cases_text if cases_text else '未检索到匹配案例。请如实告知维修员：知识库中暂无相关历史案例，建议联系资深工程师或提交新案例。不得自行编造排查步骤。'}

## 当前是第 {session['step_count']} 步
根据维修员的反馈，给出下一步排查方向（只给一步）。
如果反馈表明问题已解决（提到"解决了"/"正常了"/"修好了"等），请表示问题已解决并简短总结。
注意：不要重复之前已经排查过的方向。"""

        messages = [
            SystemMessage(content=self.CHAT_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        # 记录用户消息
        session["chat_history"].append({"user": message, "ai": ""})

        try:
            for chunk in self.llm.stream(messages):
                yield chunk
        finally:
            self._save_session(session_id, session)

    async def achat(self, session_id: str, message: str, device_type: str = ""):
        """对话式追踪（异步流式，用于 SSE 端点，避免线程池死锁）"""
        # 无关消息拦截：闲聊/与维修无关的内容不进入排查对话
        if _is_repair_irrelevant(message):
            yield AIMessageChunk(content=_IRRELEVANT_REPLY)
            return
        # 获取或创建会话（Redis 持久化）
        session = self._load_session(session_id)
        is_new = session is None
        if is_new:
            session = {
                "device_type": device_type,
                "initial_symptoms": message,
                "chat_history": [],
                "status": "diagnosing",
                "created_at": time.time(),
                "step_count": 0,
                "cases": [],
            }
        session["step_count"] += 1
        session["last_user"] = message

        # 检索知识库
        search_query = f"{session['initial_symptoms']} {message}"
        cases = self._search_knowledge(search_query, session.get("device_type", ""))
        session["cases"] = cases

        # 构建案例文本（缩短内容，只取关键信息）
        cases_text = ""
        for i, c in enumerate(cases, 1):
            content = (c.get('content', '') or '')[:600]
            cases_text += f"\n【参考案例{i}】{c.get('title', '')}\n故障原因: （从案例中提取）\n处理要点: {content}\n"

        # 构建对话历史
        history_text = ""
        for h in session.get("chat_history", []):
            history_text += f"\n维修员: {h['user']}\n你: {h['ai']}\n"

        if session["step_count"] == 1:
            user_prompt = f"""## 设备故障描述
{message}
设备类型: {device_type or '未指定'}

## 知识库参考（唯一知识来源：只能引用其中明确写到的内容，不得补充案例外的信息）
{cases_text if cases_text else '未检索到匹配案例。请如实告知维修员：知识库中暂无相关历史案例，建议联系资深工程师或提交新案例。不得自行编造排查步骤。'}

## 任务
这是维修员首次描述故障现象。请根据系统提示词中的"首次对话"规则，引导维修员排查。返回时务必包含【分析】和【操作】两部分。"""
        else:
            user_prompt = f"""## 维修员反馈
{message}

## 对话历史
{history_text}

## 知识库参考（唯一知识来源：只能引用其中明确写到的内容，不得补充案例外的信息）
{cases_text if cases_text else '未检索到匹配案例。请如实告知维修员：知识库中暂无相关历史案例，建议联系资深工程师或提交新案例。不得自行编造排查步骤。'}

## 当前是第 {session['step_count']} 步
根据维修员的反馈，给出下一步排查方向（只给一步）。返回时务必包含【分析】和【操作】两部分。
如果反馈表明问题已解决（提到"解决了"/"正常了"/"修好了"等），请表示问题已解决并简短总结。
注意：不要重复之前已经排查过的方向。"""

        messages = [
            SystemMessage(content=self.CHAT_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        # 记录用户消息
        session["chat_history"].append({"user": message, "ai": ""})

        try:
            async for chunk in self.llm.astream(messages):
                yield chunk
        finally:
            self._save_session(session_id, session)

    def chat_sync(self, session_id: str, message: str, device_type: str = "") -> str:
        """对话式追踪（同步版，用于非流式调用）"""
        chunks = []
        for chunk in self.chat(session_id, message, device_type):
            if hasattr(chunk, 'content') and chunk.content:
                chunks.append(chunk.content)
        full = "".join(chunks)
        # 更新会话历史（持久化到 Redis）
        session = self._load_session(session_id)
        if session:
            session.setdefault("chat_history", [])
            if session["chat_history"]:
                session["chat_history"][-1]["ai"] = full
            self._save_session(session_id, session)
        return full


guided_repair_agent = GuidedRepairAgent()
