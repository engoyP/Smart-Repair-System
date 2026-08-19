"""TicketUnderstandingAgent - 工单理解智能体

功能：
- 标准化：将口语化故障描述转为结构化字段（故障码、故障现象、根本原因、解决方案）
- 分类：确定设备类型、故障分类标签
- 校验：检查工单信息完整性，评估整体质量
- 输出置信度评分，辅助人工审核

集成 LangFuse 追踪与 Redis 缓存。
"""
import json
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from loguru import logger
import time

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.config import settings
from app.core.langfuse_tracer import tracer
from app.core.cache_service import cache_service


@dataclass
class TicketAnalysisResult:
    """工单分析结果"""
    # 标准化字段
    standardized_fault_code: Optional[str] = None
    standardized_fault_phenomenon: Optional[str] = None
    standardized_root_cause: Optional[str] = None
    standardized_solution_steps: Optional[str] = None

    # 分类字段
    device_type: Optional[str] = None
    fault_category: Optional[str] = None
    tags: list = field(default_factory=list)
    severity: Optional[str] = None  # LOW / MEDIUM / HIGH / CRITICAL

    # 校验结果
    is_complete: bool = False
    completeness_score: float = 0.0  # 信息完整度 0-1
    missing_fields: list = field(default_factory=list)
    validation_notes: str = ""

    # 综合置信度
    confidence: float = 0.0  # 综合置信度 0-1

    # 原始分析
    raw_reasoning: str = ""
    suggested_actions: list = field(default_factory=list)


class TicketUnderstandingAgent:
    """
    工单理解智能体

    对工单执行三步处理：
    1. 标准化 - 从故障描述中提取/生成规范的故障码、现象、根因、方案
    2. 分类 - 确定设备类型、故障分类标签、紧急程度
    3. 校验 - 检查信息完整性，给出置信度评分

    置信度评分：由"信息完整度 + 描述清晰度 + 分类确定性"综合得出，
    仅作为人工审核的参考，工单最终一律人工审核。
    """

    def __init__(self):
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

    def analyze(self, work_order_data: Dict[str, Any]) -> TicketAnalysisResult:
        """
        分析工单，执行标准化、分类、校验

        Args:
            work_order_data: 工单原始数据，至少包含 fault_description，
                             可选 fault_code, fault_phenomenon, root_cause, solution_steps

        Returns:
            TicketAnalysisResult 包含分析结果和置信度
        """
        fault_description = work_order_data.get("fault_description", "")
        original_fault_code = work_order_data.get("fault_code", "")
        original_phenomenon = work_order_data.get("fault_phenomenon", "")
        original_root_cause = work_order_data.get("root_cause", "")
        original_solution = work_order_data.get("solution_steps", "")

        if not fault_description:
            return TicketAnalysisResult(
                validation_notes="工单缺少故障描述，无法进行分析",
                missing_fields=["fault_description"],
                confidence=0.0,
            )

        # 构建 LLM Prompt
        result = self._invoke_analysis(
            fault_description=fault_description,
            fault_code=original_fault_code or "（未填写）",
            fault_phenomenon=original_phenomenon or "（未填写）",
            root_cause=original_root_cause or "（未填写）",
            solution_steps=original_solution or "（未填写）",
        )

        logger.info(
            f"[TicketAgent] 分析完成 | 置信度={result.confidence:.2f} "
            f"| 完整度={result.completeness_score:.2f}"
        )
        return result

    def _invoke_analysis(
        self,
        fault_description: str,
        fault_code: str,
        fault_phenomenon: str,
        root_cause: str,
        solution_steps: str,
    ) -> TicketAnalysisResult:
        """调用 LLM 进行工单分析（带 LangFuse 追踪）"""

        system_prompt = """你是一个设备维修工单标准化专家。你的任务是对工单进行标准化、分类和校验。

## 任务步骤

### 1. 标准化
- 根据故障描述，补全/修正故障码。如果涉及多个部件/系统，可返回多个故障码，用逗号分隔（如 MOTOR_VIB_001,ELEC_PWR_002）。
- 如果故障现象为空，从故障描述中提炼（50-200字）
- 如果根本原因为空且可推断，给出可能的根本原因
- 如果解决方案为空且可推断，给出建议的维修步骤

### 2. 分类
- **device_type**: 设备类型（如：电机、注塑机、冲床、CNC、传送带、锅炉、空压机等）
- **fault_category**: 故障大类（机械故障/电气故障/液压故障/控制系统/操作失误/磨损老化/其他）
- **tags**: 3-5个关键词标签（从描述中提取）
- **severity**: 紧急程度（LOW=轻微/MEDIUM=中等/HIGH=严重/CRITICAL=紧急停机）

### 3. 校验
- **completeness_score**: 信息完整度 0-1（故障描述质量 + 各字段填充率）
- **missing_fields**: 缺失的关键字段列表
- **validation_notes**: 校验说明（20-80字）

### 4. 置信度
根据信息完整度、描述清晰度、分类确定性综合给出 0-1 的置信度（作为人工审核的参考）：
- 0.8-1.0: 信息完整，分类明确
- 0.5-0.79: 信息基本可用
- 0.0-0.49: 信息严重不足

## 返回格式（严格 JSON，不要包含代码块标记）：
{
  "standardized_fault_code": "MOTOR_VIB_001",
  "standardized_fault_phenomenon": "主电机启动后出现周期性异响...",
  "standardized_root_cause": "轴承内圈磨损导致径向间隙增大...",
  "standardized_solution_steps": "1. 停机检查轴承状态\\n2. 测量振动值...",
  "device_type": "电机",
  "fault_category": "机械故障",
  "tags": ["振动", "轴承", "电机", "异响"],
  "severity": "HIGH",
  "completeness_score": 0.75,
  "missing_fields": ["root_cause", "solution_steps"],
  "validation_notes": "故障描述清晰，但根因和方案为空，建议补充",
  "confidence": 0.72,
  "reasoning": "分析推理过程（50-150字）",
  "suggested_actions": ["建议测量振动频谱", "检查轴承润滑状态"]
}"""

        user_message = f"""请分析以下工单：

## 工单信息
- 故障描述：{fault_description}
- 故障码：{fault_code}
- 故障现象：{fault_phenomenon}
- 根本原因：{root_cause}
- 解决方案：{solution_steps}

请执行标准化、分类、校验，返回 JSON。"""

        try:
            logger.info(f"[TicketAgent] 准备创建 trace，tracer.enabled={tracer.enabled}, ragflow_verified={tracer._ragflow_verified}")
            with tracer.trace("ticket_agent_analyze", metadata={
                "fault_description_length": len(fault_description),
                "has_fault_code": bool(fault_code and fault_code != "（未填写）"),
            }) as trace_obj:
                logger.info("[TicketAgent] trace context 已创建")

                start = time.time()
                response = self.llm.invoke([
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                ])
                elapsed = time.time() - start

                with trace_obj.generation(
                    "ticket_llm_call",
                    model=settings.DEEPSEEK_MODEL,
                    prompt=user_message,
                    response=response.content,
                    metadata={"elapsed_s": round(elapsed, 2)},
                ):
                    pass

                content = response.content.strip()

                if content.startswith("```"):
                    lines = content.split("\n")
                    content = "\n".join(lines[1:])
                    if content.endswith("```"):
                        content = content[:-3]
                content = content.strip()

                data = json.loads(content)

                result = TicketAnalysisResult(
                    standardized_fault_code=data.get("standardized_fault_code"),
                    standardized_fault_phenomenon=data.get("standardized_fault_phenomenon"),
                    standardized_root_cause=data.get("standardized_root_cause"),
                    standardized_solution_steps=data.get("standardized_solution_steps"),
                    device_type=data.get("device_type"),
                    fault_category=data.get("fault_category"),
                    tags=data.get("tags", []),
                    severity=data.get("severity", "LOW"),
                    completeness_score=float(data.get("completeness_score", 0)),
                    missing_fields=data.get("missing_fields", []),
                    validation_notes=data.get("validation_notes", ""),
                    confidence=float(data.get("confidence", 0)),
                    raw_reasoning=data.get("reasoning", ""),
                    suggested_actions=data.get("suggested_actions", []),
                )

                trace_obj.score("confidence", result.confidence,
                            f"completeness={result.completeness_score:.2f}")

                return result

        except json.JSONDecodeError as e:
            logger.error(f"[TicketAgent] JSON 解析失败: {e}, 原始响应: {content[:200]}")
            return TicketAnalysisResult(
                validation_notes=f"LLM 响应解析失败: {str(e)}",
                confidence=0.0,
            )
        except Exception as e:
            logger.error(f"[TicketAgent] LLM 调用失败: {e}")
            return TicketAnalysisResult(
                validation_notes=f"分析服务异常: {str(e)}",
                confidence=0.0,
            )


# 全局单例
ticket_agent = TicketUnderstandingAgent()
