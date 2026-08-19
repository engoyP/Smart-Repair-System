"""历史工单 PDF 导入：LangGraph 流水线

对每份 PDF 运行：
    parse（pdfplumber 提取文本，扫描件 RapidOCR 回退）
        → extract（DeepSeek 按系统工单 JSON Schema 结构化抽取）
        → validate（工单号唯一性 / 设备匹配 / 维修员与上报人匹配）
        → save_draft（写入 WorkOrderImportItem，待人工确认）

人工确认后才写入 work_orders 并收录知识库（确认之前的抽取结果不会污染生产数据）。
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional, Dict, List, TypedDict

from loguru import logger
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.work_order_import import WorkOrderImportBatch, WorkOrderImportItem
from app.models.work_order import WorkOrder
from app.models.device import Device
from app.models.user import User


# ============================================================
# 状态定义
# ============================================================
class ImportState(TypedDict, total=False):
    pdf_path: str          # 当前 PDF 文件路径
    file_name: str         # 原始文件名
    batch_id: int          # 导入批次 id
    text: str              # 解析出的全文
    extracted: dict        # LLM 抽取的系统工单字段
    warnings: List[str]    # 校验警告
    error: str             # 失败原因（非空则终止到 save_error）
    item_id: int           # 写入的待确认记录 id


# ============================================================
# PDF 解析
# ============================================================
_OCR = None  # 懒加载单例


def _get_ocr():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def _extract_pdf_text(pdf_path: str) -> str:
    """提取 PDF 文本：文本页直接抽取；无文本页（扫描件）用 RapidOCR 识别"""
    import pdfplumber
    parts: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages):
            text = (page.extract_text() or "").strip()
            if not text:
                # 扫描件：图片页 OCR 回退
                try:
                    ocr = _get_ocr()
                    img = page.to_image(resolution=200).original
                    result, _ = ocr(img)
                    if result:
                        text = "\n".join(line[1] for line in result)
                except Exception as e:
                    logger.warning(f"[WOImport] 第{idx + 1}页 OCR 失败: {e}")
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def parse_node(state: ImportState) -> dict:
    try:
        text = _extract_pdf_text(state.get("pdf_path") or "")
    except Exception as e:
        logger.error(f"[WOImport] PDF 解析失败 {state.get('file_name')}: {e}")
        return {"error": f"PDF 解析失败: {e}"}
    if not text or len(text.strip()) < 20:
        return {"error": "PDF 未识别到有效文本（可能是加密/纯图片且 OCR 不可用）"}
    return {"text": text[:12000]}  # 截断超长文本，控制 token


# ============================================================
# DeepSeek 结构化抽取
# ============================================================
_llm: Optional[ChatOpenAI] = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_MODEL,
            temperature=0.1,
            streaming=False,
        )
    return _llm


_EXTRACT_SYSTEM_PROMPT = """你是工厂设备维修历史工单的整理专家。请把一份历史工单 PDF 的内容转换成系统标准工单字段。

## 目标字段（严格 JSON，字段缺失时填空字符串，无法判断的用 null）
{
  "work_order_no": "工单号，如 WO-2021-001；找不到则为空",
  "device_code": "设备编码",
  "device_name": "设备名称",
  "fault_code": "故障码（6位数字，多个用逗号分隔；没有则为空）",
  "fault_description": "故障描述（必填，简洁概括故障内容）",
  "fault_category": "故障大类（如 温度异常/机械故障/电气故障）",
  "fault_phenomenon": "故障现象补充描述",
  "root_cause_category": "根本原因大类",
  "root_cause": "根本原因详细说明",
  "solution_steps": "解决/维修步骤（分条列出）",
  "repair_result": "维修结果：PERMANENT_FIX(彻底修复)/TEMPORARY_FIX(临时处理)/UNABLE_FIX(无法修复)，不确定则 null",
  "work_hours": 工时数字（小时，无则为 null）,
  "used_parts": [{"name": "备件名", "count": 数量}],
  "priority": "LOW/MEDIUM/HIGH/CRITICAL",
  "location": "设备位置",
  "start_time": "报修时间 YYYY-MM-DD HH:MM",
  "end_time": "完工时间 YYYY-MM-DD HH:MM",
  "reporter_name": "报修人姓名",
  "technician_name": "维修人姓名",
  "tags": ["标签1", "标签2"]
}

## 要求
- 只输出 JSON，不要任何解释文字或 Markdown 代码块
- 忠实于原文，不要编造原文没有的信息；原文没有的字段填 null 或空
- 维修步骤若原文有多条，完整保留
"""


def _extract_work_order(text: str) -> Dict:
    """调用 DeepSeek 抽取工单字段，失败重试 1 次"""
    for attempt in (1, 2):
        try:
            resp = _get_llm().invoke([
                SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content=text),
            ])
            content = resp.content.strip()
            if content.startswith("```"):
                content = "\n".join(content.split("\n")[1:])
                if content.endswith("```"):
                    content = content[:-3]
            data = json.loads(content)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.warning(f"[WOImport] 抽取失败(第{attempt}次): {e}")
            time.sleep(1)
    return {}


def extract_node(state: ImportState) -> dict:
    text = state.get("text") or ""
    if not text:
        return {"error": "无文本可抽取"}
    data = _extract_work_order(text)
    if not data:
        return {"error": "LLM 结构化抽取失败（返回空）"}
    # OCR 常见误识修正：W0- → WO-
    wo_no = str(data.get("work_order_no") or "").strip()
    if re.match(r"W[0O]-?\d", wo_no) and not wo_no.upper().startswith("WO-"):
        data["work_order_no"] = "WO" + wo_no[2:]
    return {"extracted": data}


# ============================================================
# 校验（工单号唯一 / 设备 / 用户匹配）
# ============================================================
def validate_node(state: ImportState) -> dict:
    extracted = dict(state.get("extracted") or {})
    warnings: List[str] = []
    db = SessionLocal()
    try:
        # 1. 工单号唯一性
        wo_no = (extracted.get("work_order_no") or "").strip()
        if wo_no:
            exists = db.query(WorkOrder).filter(WorkOrder.work_order_no == wo_no).first()
            if exists:
                warnings.append(f"工单号 {wo_no} 已存在")
        else:
            warnings.append("未识别到工单号，确认时将自动生成")

        # 2. 设备匹配
        device_code = (extracted.get("device_code") or "").strip()
        if device_code:
            dev = db.query(Device).filter(Device.device_code == device_code).first()
            if dev:
                extracted["device_id"] = dev.id
            else:
                warnings.append(f"设备编码 {device_code} 未在设备库找到")
        else:
            warnings.append("未识别到设备编码")

        # 3. 维修员 / 报修人匹配
        for key, label in (("technician_name", "维修员"), ("reporter_name", "报修人")):
            name = (extracted.get(key) or "").strip()
            if name:
                u = db.query(User).filter(User.real_name == name).first()
                if u:
                    extracted[f"{key.replace('_name', '')}_id"] = u.id  # technician_id / reporter_id
                else:
                    warnings.append(f"{label}「{name}」未匹配到系统用户")
    finally:
        db.close()
    return {"extracted": extracted, "warnings": warnings}


# ============================================================
# 保存草稿（写入待确认记录）
# ============================================================
def save_draft_node(state: ImportState) -> dict:
    db = SessionLocal()
    try:
        item = WorkOrderImportItem(
            batch_id=state.get("batch_id"),
            file_name=state.get("file_name") or "",
            file_path=state.get("pdf_path"),
            status="PENDING",
            extracted_text=(state.get("text") or "")[:4000],
            extracted_data=state.get("extracted") or {},
            validate_warnings=state.get("warnings") or [],
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        logger.info(f"[WOImport] 待确认记录 #{item.id}: {item.file_name}")
        return {"item_id": item.id}
    finally:
        db.close()


def save_error_node(state: ImportState) -> dict:
    db = SessionLocal()
    try:
        item = WorkOrderImportItem(
            batch_id=state.get("batch_id"),
            file_name=state.get("file_name") or "",
            file_path=state.get("pdf_path"),
            status="ERROR",
            error_message=state.get("error") or "未知错误",
            extracted_text=(state.get("text") or "")[:4000],
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return {"item_id": item.id}
    finally:
        db.close()


# ============================================================
# 图构建
# ============================================================
def _parse_success(state: ImportState) -> str:
    return "extract" if not state.get("error") else "save_error"


def _extract_success(state: ImportState) -> str:
    return "validate" if state.get("extracted") else "save_error"


def build_import_graph():
    graph = StateGraph(ImportState)
    graph.add_node("parse", parse_node)
    graph.add_node("extract", extract_node)
    graph.add_node("validate", validate_node)
    graph.add_node("save_draft", save_draft_node)
    graph.add_node("save_error", save_error_node)

    graph.set_entry_point("parse")
    graph.add_conditional_edges("parse", _parse_success, {"extract": "extract", "save_error": "save_error"})
    graph.add_conditional_edges("extract", _extract_success, {"validate": "validate", "save_error": "save_error"})
    graph.add_edge("validate", "save_draft")
    graph.add_edge("save_draft", END)
    graph.add_edge("save_error", END)
    return graph.compile()


WO_IMPORT_GRAPH = build_import_graph()


def invoke_import_pdf(pdf_path: str, file_name: str, batch_id: int) -> dict:
    """对单份 PDF 运行导入流水线，返回处理结果"""
    start = time.time()
    state = {
        "pdf_path": pdf_path,
        "file_name": file_name,
        "batch_id": batch_id,
    }
    result = WO_IMPORT_GRAPH.invoke(state)
    elapsed = round(time.time() - start, 1)
    if result.get("error"):
        return {"file_name": file_name, "status": "ERROR", "message": result["error"], "elapsed": elapsed}
    return {
        "file_name": file_name,
        "status": "PENDING",
        "item_id": result.get("item_id"),
        "message": "抽取完成，待人工确认",
        "elapsed": elapsed,
    }
