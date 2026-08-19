"""钉钉 H5 相关 API"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.sql import cast
from sqlalchemy.types import Date as SA_Date
from typing import Optional, List, Dict, Any
from loguru import logger
from datetime import datetime, date, timedelta
import uuid
import time
import json
import re

from app.core.database import get_db
from app.core.dingtalk import dingtalk
from app.core.config import settings
from app.core.notification import notification_service
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.user import User, UserRole
from app.agents.ticket_agent import ticket_agent
from app.agents.inventory_tools import query_inventory

# ------------------------------------------------------------
# Phase 2.1 新增：Stream / HTTP 回调双模式 OA 审批同步
# ------------------------------------------------------------
from app.core import dingtalk_oa_config as OA_CFG  # noqa: E402
from app.core import dingtalk_oa_sync  # noqa: E402
from app.core import dingtalk_stream  # noqa: E402

router = APIRouter()


# ============================================================
# [STARTUP] 应用启动时：1) 启动 Stream 客户端  2) 挂 APScheduler 定时任务
# 注：FastAPI 启动钩子在 main.py 中注册，这里提供一个 ensure_running()
# 供 main.py 调用，避免循环导入。
# ============================================================
_scheduler_started = False


def ensure_oa_services_started(app) -> None:
    """在 FastAPI startup 中调用。启动 Stream 客户端 + APScheduler 定时任务（如果尚未启动）。

    app: FastAPI 实例，用于注册 lifespan。
    """
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    # 1. Stream 客户端
    dingtalk_stream.start_stream_in_background()

    # 2. APScheduler：每天 01:00 同步过去 3 天的 OA 审批单（兜底，防止漏事件）
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception:
        logger.info("[OA-Sync] 未安装 apscheduler，跳过内置兜底定时任务。"
                    "可自行用系统 cron 调用 POST /dingtalk/schedule/sync-oa-leaves 接口。")
        return

    try:
        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

        def _job_sync_recent_3days():
            logger.info("[OA-Sync][Cron] 每天 01:00 启动兜底同步（近 3 天审批单）")
            try:
                sync_recent_oa_leaves(days=3)
            except Exception as e:
                logger.exception(f"[OA-Sync][Cron] 兜底同步失败: {e}")

        scheduler.add_job(
            _job_sync_recent_3days,
            "cron",
            hour=1,
            minute=0,
            id="oa_leaves_daily_sync",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("[OA-Sync] APScheduler 兜底同步任务已注册：每天 01:00 跑一次（近 3 天）")

        # app shutdown 时停 scheduler 和 stream
        @app.on_event("shutdown")
        async def _shutdown():
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass
            dingtalk_stream.stop_stream_background()

    except Exception as e:
        logger.exception(f"[OA-Sync] APScheduler 初始化失败（不影响主功能）: {e}")



# ==================== 钉钉 OAuth2 扫码回调 ====================

@router.get("/callback", summary="钉钉 OAuth2 扫码登录回调")
def dingtalk_oauth_callback(
    code: Optional[str] = Query(None, description="钉钉旧版返回的授权码"),
    authCode: Optional[str] = Query(None, description="钉钉新版返回的授权码"),
    state: str = Query(..., description="前端生成的 state，用于关联扫码会话"),
):
    """
    钉钉 OAuth2 扫码登录的回调地址。
    - 兼容新旧两版钉钉返回参数：新版返回 authCode，旧版返回 code
    - 流程：
      1. 用户在 PC 端看到二维码 → 钉钉 APP 扫码
      2. 钉钉重定向到此 URL，携带 (auth)Code 和 state
      3. 后端用 code 换取用户信息
      4. 更新扫码会话状态为 scanned
      5. 返回"扫码成功"页面，前端轮询检测到状态变化后自动完成登录
    """
    # 兼容新旧两版参数名
    actual_code = authCode or code
    if not actual_code:
        logger.error(f"[DingTalk][Callback] 缺少授权码参数: authCode={authCode}, code={code}, state={state}")
        return HTMLResponse(content="""
        <html><head><meta charset="utf-8"><title>登录失败</title>
        <style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#f5f6f8}
        .box{text-align:center;background:#fff;padding:40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}
        .icon{font-size:48px;margin-bottom:16px}.title{font-size:18px;color:#F53F3F;margin-bottom:8px}
        .msg{font-size:14px;color:#86909C}</style></head>
        <body><div class="box"><div class="icon">❌</div><div class="title">授权参数缺失</div>
        <div class="msg">请返回页面重新扫码</div></div></body></html>""")
    # 动态导入 auth 模块的扫码会话存储，避免循环依赖
    from app.api.auth import _dingtalk_scan_sessions, SCAN_EXPIRE_SECONDS

    session = _dingtalk_scan_sessions.get(state)
    if not session:
        logger.warning(f"[DingTalk][Callback] 无效的 state: {state}")
        return HTMLResponse(content="""
        <html><head><meta charset="utf-8"><title>扫码登录</title>
        <style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#f5f6f8}
        .box{text-align:center;background:#fff;padding:40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}
        .icon{font-size:48px;margin-bottom:16px}.title{font-size:18px;color:#F53F3F;margin-bottom:8px}
        .msg{font-size:14px;color:#86909C}</style></head>
        <body><div class="box"><div class="icon">⏰</div><div class="title">二维码已过期</div>
        <div class="msg">请返回页面重新生成二维码</div></div></body></html>""")

    if session.get("status") == "expired" or time.time() - session.get("created_at", 0) > SCAN_EXPIRE_SECONDS:
        session["status"] = "expired"
        return HTMLResponse(content="""
        <html><head><meta charset="utf-8"><title>扫码登录</title>
        <style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#f5f6f8}
        .box{text-align:center;background:#fff;padding:40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}
        .icon{font-size:48px;margin-bottom:16px}.title{font-size:18px;color:#F53F3F;margin-bottom:8px}
        .msg{font-size:14px;color:#86909C}</style></head>
        <body><div class="box"><div class="icon">⏰</div><div class="title">二维码已过期</div>
        <div class="msg">请返回页面重新生成二维码</div></div></body></html>""")

    try:
        # 用 code 换取钉钉用户信息（OAuth2 扫码登录专用）
        identity = dingtalk.get_user_by_scan_code(actual_code)
        user_info = {
            "userid": identity.get("userid", ""),
            "name": identity.get("name", ""),
            "mobile": identity.get("mobile", ""),
            "union_id": identity.get("union_id", ""),
            "dept": "",
        }
        # 尝试获取更多用户详情。
        # 注意：若应用缺少 Contact.User.Read 权限，get_user_detail 会临时降级为 Mock 数据。
        # Mock 数据的 name/mobile（如"用户_iEiE"）必须禁止覆盖已从扫码拿到的真实 nick/手机号。
        # 只有 dept/title 这类本身就拿不到真实值的字段允许用 Mock 兜底。
        if user_info.get("userid"):
            try:
                detail = dingtalk.get_user_detail(user_info["userid"])
                if detail:
                    is_mock_detail = bool(detail.get("_mock"))
                    # dept/title 始终允许覆盖（真实扫码流程拿不到，Mock 也比空值强）
                    user_info["dept"] = detail.get("dept_name", "") or detail.get("title", "") or user_info["dept"]
                    if not is_mock_detail:
                        # 只有拿到真实详情时才覆盖 name / mobile，否则保留扫码 nick / 手机号
                        if detail.get("name"):
                            user_info["name"] = detail["name"]
                        if detail.get("mobile"):
                            user_info["mobile"] = detail["mobile"]
            except Exception as e:
                logger.warning(f"[DingTalk][Callback] 获取用户详情失败: {e}")

        session["user_info"] = user_info
        session["status"] = "scanned"
        logger.info(f"[DingTalk][Callback] 扫码成功: state={state}, user={user_info.get('name', '')}")

        return HTMLResponse(content=f"""
        <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>扫码成功</title>
        <style>body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#f5f6f8}}
        .box{{text-align:center;background:#fff;padding:40px 48px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}}
        .icon{{width:64px;height:64px;background:#00B42A;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 20px;font-size:32px;color:#fff}}
        .title{{font-size:20px;font-weight:600;color:#1D2129;margin-bottom:8px}}
        .user{{font-size:16px;color:#165DFF;font-weight:500;margin-bottom:4px}}
        .sub{{font-size:13px;color:#86909C}}</style></head>
        <body><div class="box"><div class="icon">✓</div><div class="title">扫码成功</div>
        <div class="user">{user_info.get("name", "钉钉用户")}</div>
        <div class="sub">请返回电脑端页面继续操作</div></div></body></html>""")

    except Exception as e:
        logger.error(f"[DingTalk][Callback] 扫码处理失败: {e}")
        return HTMLResponse(content=f"""
        <html><head><meta charset="utf-8"><title>登录失败</title>
        <style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;background:#f5f6f8}}
        .box{{text-align:center;background:#fff;padding:40px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.08)}}
        .icon{{font-size:48px;margin-bottom:16px}}.title{{font-size:18px;color:#F53F3F;margin-bottom:8px}}
        .msg{{font-size:14px;color:#86909C;max-width:300px}}</style></head>
        <body><div class="box"><div class="icon">❌</div><div class="title">登录失败</div>
        <div class="msg">钉钉授权失败，请返回页面重试<br/><br/><small>{str(e)[:200]}</small></div></div></body></html>""")


class DingTalkLoginRequest(BaseModel):
    code: str


class DingTalkLoginResponse(BaseModel):
    userid: str
    name: str
    mobile: Optional[str] = ""
    avatar: Optional[str] = ""
    title: Optional[str] = ""
    department: Optional[str] = ""
    role: str = "TECHNICIAN"
    token: str = ""


class MobileReportRequest(BaseModel):
    """移动端极简上报"""
    device_code: Optional[str] = None
    fault_description: str
    media: Optional[List[str]] = None
    location: Optional[str] = None
    reporter_id: Optional[int] = None
    priority: str = "MEDIUM"


class CompletionReportRequest(BaseModel):
    """维修完成报告"""
    work_hours: float = 0.0
    used_parts: Optional[List[dict]] = None
    solution_desc: str = ""
    completion_photos: Optional[List[str]] = None


class ContactSyncResponse(BaseModel):
    total_departments: int
    total_users: int
    synced_users: int
    message: str


# ==================== 钉钉登录 ====================

@router.post("/login", response_model=DingTalkLoginResponse, summary="钉钉免登")
def dingtalk_login(req: DingTalkLoginRequest, db: Session = Depends(get_db)):
    """
    钉钉 H5 免登完整流程:
    1. 前端 dd.runtime.permission.requestAuthCode 获取 code
    2. 后端 code → 钉钉 userid + 用户信息
    3. 查找或创建本地用户，绑定 dingtalk_userid
    4. 返回用户角色信息
    """
    try:
        identity = dingtalk.get_user_by_code(req.code)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"钉钉认证失败: {str(e)}")

    dingtalk_userid = identity.get("userid", "")

    user = db.query(User).filter(User.dingtalk_userid == dingtalk_userid).first()
    if not user:
        user = db.query(User).filter(User.username == dingtalk_userid).first()

    if not user:
        try:
            detail = dingtalk.get_user_detail(dingtalk_userid)
        except Exception:
            detail = {"name": identity.get("name", dingtalk_userid), "mobile": ""}

        title = detail.get("title", "")
        dept_name = detail.get("dept_name", "")
        role = _infer_role(dept_name, title, dingtalk_userid)

        user = User(
            username=dingtalk_userid,
            password_hash="dingtalk_oauth",
            real_name=detail.get("name", dingtalk_userid),
            email=f"{dingtalk_userid}@dingtalk.local",
            phone=detail.get("mobile", ""),
            role=role,
            dingtalk_userid=dingtalk_userid,
            department=dept_name,
            title=title,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"[DingTalk] 新建用户: {user.real_name} ({dingtalk_userid}), 角色={role}")
    else:
        if not user.dingtalk_userid:
            user.dingtalk_userid = dingtalk_userid
        if user.department is None:
            try:
                detail = dingtalk.get_user_detail(dingtalk_userid)
                user.department = detail.get("dept_name", "")
                user.title = detail.get("title", "")
            except Exception:
                pass
        db.commit()

    user.last_login_at = datetime.utcnow()
    db.commit()

    logger.info(f"[DingTalk] 用户登录: {user.real_name} ({dingtalk_userid}), 角色={user.role}")

    return DingTalkLoginResponse(
        userid=dingtalk_userid,
        name=user.real_name,
        mobile=user.phone or "",
        avatar=identity.get("avatar", ""),
        title=user.title or "",
        department=user.department or "",
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        token="todo-jwt-token",
    )


def _infer_role(dept_name: str, title: str, userid: str) -> str:
    """根据部门/职位信息推断角色"""
    if "维修" in dept_name or "技术" in dept_name or "工程师" in title or "电工" in title:
        return UserRole.TECHNICIAN.value
    if "点检" in title or "操作" in title or "运行" in dept_name:
        return UserRole.WORKER.value
    if "主管" in title or "经理" in title or "管理" in dept_name:
        return UserRole.SUPERVISOR.value
    if userid.startswith("mock_admin"):
        return UserRole.ADMIN.value
    return UserRole.TECHNICIAN.value


# ==================== 通讯录同步 ====================

@router.post("/sync-contacts", response_model=ContactSyncResponse, summary="同步钉钉通讯录")
def sync_contacts(db: Session = Depends(get_db)):
    """
    从钉钉拉取部门+用户列表，upsert 到本地 users 表
    - 按 dingtalk_userid 匹配
    - 自动推断角色
    """
    sync_result = dingtalk.sync_contacts()
    departments = sync_result["departments"]
    users = sync_result["users"]

    synced = 0
    for u in users:
        dt_userid = u.get("userid", "")
        name = u.get("name", "")
        mobile = u.get("mobile", "")
        title = u.get("title", "")
        dept_name = u.get("dept_name", "")
        active = u.get("active", True)

        local_user = db.query(User).filter(User.dingtalk_userid == dt_userid).first()
        if not local_user:
            local_user = db.query(User).filter(User.username == dt_userid).first()

        if local_user:
            if local_user.real_name != name and name:
                local_user.real_name = name
            if mobile:
                local_user.phone = mobile
            if title:
                local_user.title = title
            if dept_name:
                local_user.department = dept_name
            local_user.is_active = active
            synced += 1
        else:
            role = _infer_role(dept_name, title, dt_userid)
            new_user = User(
                username=dt_userid,
                password_hash="dingtalk_oauth",
                real_name=name or dt_userid,
                email=f"{dt_userid}@dingtalk.local",
                phone=mobile,
                role=role,
                dingtalk_userid=dt_userid,
                department=dept_name,
                title=title,
                is_active=active,
            )
            db.add(new_user)
            synced += 1

    db.commit()

    logger.info(f"[DingTalk] 通讯录同步完成: {len(users)} 用户, {synced} 已同步")
    return ContactSyncResponse(
        total_departments=len(departments),
        total_users=len(users),
        synced_users=synced,
        message=f"同步成功：{len(departments)} 个部门，{synced}/{len(users)} 个用户已更新",
    )


@router.get("/departments", summary="获取部门列表")
def list_departments():
    """获取钉钉部门列表（Mock/真实）"""
    return dingtalk.get_department_list()


@router.get("/contacts", summary="获取用户列表")
def list_contacts(dept_id: int = Query(0, description="部门ID，0为全部")):
    """获取钉钉用户列表"""
    return dingtalk.get_user_list(dept_id)


# ==================== 移动端极简上报 ====================

@router.post("/report", summary="移动端极简上报")
def mobile_report(req: MobileReportRequest, db: Session = Depends(get_db)):
    """
    工作人员通过移动端扫码/拍照/语音上报故障
    - 自动生成工单编号
    - 触发 AI 分析和派工
    - 返回工单状态
    """
    today = datetime.now().strftime("%Y%m%d")
    count = db.query(WorkOrder).filter(
        WorkOrder.work_order_no.like(f"WO-{today}-%")
    ).count()
    wo_no = f"WO-{today}-{count + 1:03d}"

    work_order = WorkOrder(
        work_order_no=wo_no,
        device_code=req.device_code,
        fault_description=req.fault_description,
        fault_media=req.media,
        location=req.location,
        reporter_id=req.reporter_id,
        priority=req.priority,
        status=WorkOrderStatus.SUBMITTED,
    )
    db.add(work_order)
    db.commit()
    db.refresh(work_order)

    return {
        "work_order_id": work_order.id,
        "work_order_no": wo_no,
        "status": work_order.status.value,
        "message": "上报成功",
    }


# ==================== 维修人员端 ====================

@router.get("/tech/queue", summary="维修人员工单队列")
def tech_queue(
    userid: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(10),
    db: Session = Depends(get_db),
):
    """获取当前维修人员的待处理工单列表"""
    user = db.query(User).filter(
        (User.username == userid) | (User.dingtalk_userid == userid)
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    query = db.query(WorkOrder).filter(
        WorkOrder.assignee_id == user.id,
        WorkOrder.status.in_([
            WorkOrderStatus.ASSIGNED,
            WorkOrderStatus.IN_PROGRESS,
        ]),
    ).order_by(WorkOrder.priority.desc(), WorkOrder.created_at.desc())

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "items": [{
            "id": wo.id,
            "work_order_no": wo.work_order_no,
            "device_code": wo.device_code,
            "fault_description": wo.fault_description[:80],
            "priority": wo.priority,
            "location": wo.location,
            "status": wo.status.value if hasattr(wo.status, "value") else str(wo.status),
            "created_at": wo.created_at.isoformat() if wo.created_at else None,
        } for wo in items],
        "page": page,
        "page_size": page_size,
    }


@router.get("/tech/detail/{work_order_id}", summary="维修人员工单详情")
def tech_detail(work_order_id: int, db: Session = Depends(get_db)):
    """获取工单完整详情（含分析结果、库存关联）"""
    wo = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")

    inventory = {}
    analysis = wo.analysis_result if isinstance(wo.analysis_result, dict) else {}
    device_type = analysis.get("device_type", "")
    if device_type or wo.fault_code:
        try:
            inventory = query_inventory(db, device_type=device_type, fault_code=wo.fault_code)
        except Exception:
            pass

    return {
        "id": wo.id,
        "work_order_no": wo.work_order_no,
        "device_code": wo.device_code,
        "device_id": wo.device_id,
        "fault_code": wo.fault_code,
        "fault_description": wo.fault_description,
        "fault_phenomenon": wo.fault_phenomenon,
        "fault_media": wo.fault_media,
        "root_cause": wo.root_cause,
        "solution_steps": wo.solution_steps,
        "priority": wo.priority,
        "location": wo.location,
        "status": wo.status.value if hasattr(wo.status, "value") else str(wo.status),
        "confidence": wo.confidence,
        "analysis_result": wo.analysis_result,
        "dispatch_score": wo.dispatch_score,
        "completion_report": wo.completion_report,
        "inventory": inventory,
        "created_at": wo.created_at.isoformat() if wo.created_at else None,
    }


@router.post("/tech/start/{work_order_id}", summary="开始维修")
def tech_start_work(work_order_id: int, db: Session = Depends(get_db)):
    """维修人员接单，状态 → IN_PROGRESS"""
    wo = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")
    if wo.status != WorkOrderStatus.ASSIGNED:
        raise HTTPException(status_code=400, detail=f"工单状态为 {wo.status.value}，无法接单")
    wo.status = WorkOrderStatus.IN_PROGRESS
    wo.start_time = datetime.utcnow()
    db.commit()
    return {"message": "已开始维修", "status": wo.status.value}


@router.post("/tech/complete/{work_order_id}", summary="提交完成报告")
def tech_complete_work(
    work_order_id: int,
    report: CompletionReportRequest,
    db: Session = Depends(get_db),
):
    """维修完成，提交报告，状态 → COMPLETED"""
    wo = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="工单不存在")
    if wo.status != WorkOrderStatus.IN_PROGRESS:
        raise HTTPException(status_code=400, detail=f"工单状态为 {wo.status.value}，无法完成")

    wo.status = WorkOrderStatus.COMPLETED
    wo.end_time = datetime.utcnow()
    wo.completion_report = {
        "work_hours": report.work_hours,
        "used_parts": report.used_parts,
        "solution_desc": report.solution_desc,
        "completion_photos": report.completion_photos,
        "completed_at": wo.end_time.isoformat(),
    }
    if report.solution_desc:
        wo.solution_steps = report.solution_desc

    db.commit()

    try:
        assignee = db.query(User).filter(User.id == wo.assignee_id).first()
        if assignee:
            dt_userid = assignee.dingtalk_userid or str(assignee.id)
            notification_service.notify_completion(
                userid=dt_userid,
                work_order_no=wo.work_order_no,
                device=wo.device_code or "未知设备",
                summary=report.solution_desc,
                db=db,
            )
    except Exception as e:
        logger.warning(f"[Mobile] 完成通知发送失败: {e}")

    # 自动收录知识到向量库
    knowledge_synced = False
    try:
        from app.api.work_orders import _auto_publish_knowledge
        knowledge_synced = _auto_publish_knowledge(wo, db)
        db.commit()
    except Exception as e:
        logger.warning(f"[Mobile] 知识收录失败: {e}")

    logger.info(f"[Mobile] 工单 {wo.work_order_no} 维修完成，knowledge_synced={knowledge_synced}")
    return {"message": "维修完成", "status": "COMPLETED", "knowledge_synced": knowledge_synced}


# ====================================================================
# Phase 2.1: 请假流程机器人回调 + 指令解析 + 自动通知
# ====================================================================

# 假别中文 → LeaveType enum.value
_LEAVE_TYPE_MAP = {
    "年假": "ANNUAL", "年": "ANNUAL", "ANNUAL": "ANNUAL",
    "病假": "SICK", "病": "SICK", "SICK": "SICK",
    "事假": "PERSONAL", "事": "PERSONAL", "PERSONAL": "PERSONAL",
    "调休": "COMPENSATION", "补休": "COMPENSATION", "COMPENSATION": "COMPENSATION",
    "婚假": "MARRIAGE", "婚": "MARRIAGE", "MARRIAGE": "MARRIAGE",
    "产假": "MATERNITY", "孕": "MATERNITY", "MATERNITY": "MATERNITY",
    "丧假": "FUNERAL", "丧": "FUNERAL", "FUNERAL": "FUNERAL",
    "其他": "OTHER", "其它": "OTHER", "OTHER": "OTHER",
}

_SHIFT_MAP = {
    "全天": "ALL_DAY", "整天": "ALL_DAY", "all": "ALL_DAY", "ALL_DAY": "ALL_DAY",
    "上午": "MORNING", "早上": "MORNING", "MORNING": "MORNING",
    "下午": "AFTERNOON", "中午": "AFTERNOON", "AFTERNOON": "AFTERNOON",
}


def _cn_leave_type(v: str) -> str:
    for k, val in _LEAVE_TYPE_MAP.items():
        if k in v:
            return val
    return "ANNUAL"


def _cn_shift(v: str) -> str:
    for k, val in _SHIFT_MAP.items():
        if k in v:
            return val
    return "ALL_DAY"


def _parse_date_token(s: str) -> tuple[date | None, date | None]:
    """解析日期 token: 2026-08-10 / 08-10 / 2026-08-10~2026-08-12 / 明天 / 后天 / 今天"""
    import datetime as _dt
    today = date.today()
    s = s.strip()
    if s in ("今天", "今日"):
        return today, today
    if s in ("明天", "明日"):
        d = today + timedelta(days=1)
        return d, d
    if s in ("后天",):
        d = today + timedelta(days=2)
        return d, d
    if "~" in s or "-" in s and s.count("-") >= 3:
        sep = "~" if "~" in s else "-"
        # 用第一个非日期的分隔符拆分更稳妥
        for sep_c in ["~", "至", "到", "-"]:
            if sep_c in s:
                parts = re.split(r"[~至到]", s)
                if len(parts) == 2:
                    d1, _ = _parse_date_token(parts[0])
                    d2, _ = _parse_date_token(parts[1])
                    return d1, d2
    # 单日期 YYYY-MM-DD / MM-DD
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dd = date(y, mo, d)
            return dd, dd
        except Exception:
            return None, None
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})", s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        try:
            dd = date(today.year, mo, d)
            return dd, dd
        except Exception:
            return None, None
    return None, None


class RobotTextMessage(BaseModel):
    """钉钉机器人 1.0 消息格式（HTTP 回调）"""
    msgtype: Optional[str] = None
    text: Optional[Dict[str, Any]] = None
    content: Optional[Dict[str, Any]] = None
    senderId: Optional[str] = None
    senderId_list: Optional[List[str]] = None
    conversationId: Optional[str] = None
    conversationType: Optional[str] = None
    # 钉钉 stream 模式常见字段
    msgId: Optional[str] = None
    createAt: Optional[int] = None
    raw: Optional[Dict[str, Any]] = None


@router.post("/robot/callback", summary="钉钉机器人消息回调（文本指令/互动卡片回调）")
async def robot_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """钉钉机器人 Webhook：收到消息 → 解析指令 → 走对应流程。
    为了兼容各种回调形态，直接读 Request body 的 JSON。"""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    logger.debug(f"[DingTalk][Robot] 收到回调: {json.dumps(payload, ensure_ascii=False)[:300]}")

    # ---------- 1) 拿 senderId（钉钉 userid） ----------
    sender_userid = (
        payload.get("senderId")
        or payload.get("senderStaffId")
        or payload.get("userId")
        or (payload.get("sender") or {}).get("staffId")
        or (payload.get("chatbotUserId") if False else None)
    )
    if not sender_userid:
        # 有些回调里会把 userId 直接放顶级
        if isinstance(payload.get("userId"), str):
            sender_userid = payload["userId"]
    if not sender_userid:
        return JSONResponse({"errcode": 0, "errmsg": "ignore no sender"})

    # ---------- 2) 拿纯文本内容 ----------
    text = ""
    msgtype = payload.get("msgtype") or payload.get("type")
    if msgtype == "text":
        text = (payload.get("text") or {}).get("content", "")
    elif isinstance(payload.get("content"), dict):
        text = payload["content"].get("content") or payload["content"].get("text") or ""
    elif isinstance(payload.get("text"), dict):
        text = payload["text"].get("content") or ""
    # 表单互动卡片回调：callbackType = "card_callback" / outTrackId / privateData
    if payload.get("callbackType") == "card_callback" or payload.get("cardCallback"):
        return _handle_card_callback(payload, sender_userid, background_tasks, db)

    text = (text or "").strip()
    # 去掉 @机器人前缀
    if text.startswith("@"):
        parts = text.split(None, 1)
        text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        return JSONResponse({"errcode": 0, "errmsg": "ok"})

    # 异步处理：避免钉钉重试（钉钉要求 1s 内返回）
    background_tasks.add_task(_process_text_command, sender_userid, text, payload, db)
    return JSONResponse({"errcode": 0, "errmsg": "ok"})


def _handle_card_callback(payload, sender_userid, background_tasks, db):
    """互动卡片回调：批准 / 拒绝按钮点击。
    真实生产环境需处理 cardInstanceId / outTrackId 校验（用于幂等 correlation_id）。
    这里简化：识别表单输入的字段后调用对应 API。"""
    correlation_id = (
        payload.get("outTrackId")
        or payload.get("correlation_id")
        or (payload.get("privateData") or {}).get("correlation_id")
    )
    action = (payload.get("action") or {}).get("value") if isinstance(payload.get("action"), dict) else payload.get("action")
    input_values = (payload.get("formValue") or payload.get("value") or {})
    logger.info(f"[DingTalk][Robot] 卡片回调 correlation_id={correlation_id} action={action}")
    if not correlation_id:
        return JSONResponse({"errcode": 0, "errmsg": "no correlation_id"})
    background_tasks.add_task(
        _process_card_action, sender_userid, correlation_id, action, input_values, db
    )
    return JSONResponse({"errcode": 0, "errmsg": "ok"})


def _process_card_action(sender_userid: str, correlation_id: str,
                         action: str | None, inputs: Dict, db: Session):
    """互动卡片点击按钮后的异步处理：
    支持 action: approve / reject（请假审批）、accept / arrive / complete（派工工单）。
    按 correlation_id 找对应业务单据，再按当前发消息的人判断权限。
    """
    # ===== 派工工单卡片回调 =====
    if action and action.lower() in ("accept", "arrive", "complete", "接受", "到达", "完成"):
        return _process_dispatch_card_action(sender_userid, correlation_id, action, db)

    from app.models.leave_request import LeaveRequest
    from app.models.user import UserRole
    u = _find_or_create_user_by_dtuserid(db, sender_userid)
    is_sp = u.role in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value, UserRole.MANAGER.value)
    lr = db.query(LeaveRequest).filter(LeaveRequest.correlation_id == correlation_id).first()
    if not lr:
        dingtalk.send_text_notice(sender_userid, f"❌ 未找到请假申请 correlation_id={correlation_id}")
        return
    if not action:
        dingtalk.send_text_notice(sender_userid, f"ℹ️ 请假 #{lr.id} 状态：{lr.status}。请点击批准或拒绝按钮。")
        return
    # 把字段拉出来
    sub_id = None
    comment = None
    if isinstance(inputs, dict):
        sub_raw = inputs.get("substitute_user_id") or inputs.get("substitute") or inputs.get("顶岗人")
        if sub_raw is not None:
            try:
                sub_id = int(sub_raw)
            except Exception:
                sub_id = None
        comment = inputs.get("approver_comment") or inputs.get("comment") or inputs.get("备注") or None
    if action.lower() in ("approve", "批准", "同意", "ok", "yes"):
        lines = _cmd_approve_leave(u, lr.id, sub_id, comment, db)
        dingtalk.send_text_notice(sender_userid, "\n".join(lines))
        return
    if action.lower() in ("reject", "拒绝", "否决", "no"):
        reason = comment or "主管拒绝"
        lines = _cmd_reject_leave(u, lr.id, reason, db)
        dingtalk.send_text_notice(sender_userid, "\n".join(lines))
        return
    dingtalk.send_text_notice(sender_userid, f"❓ 未知卡片动作 action={action}")


def _process_dispatch_card_action(sender_userid: str, correlation_id: str,
                                   action: str, db: Session):
    """派工工单互动卡片回调：accept / arrive / complete。
    correlation_id 存的是 work_order_no（如 WO-20260804-001）。
    通过 sender_userid 找到维修员用户，复用工单流转逻辑。
    """
    from app.models.work_order import WorkOrder, WorkOrderStatus
    from app.schemas import WorkOrderTransition

    action_lower = action.lower()
    status_map = {
        "accept": WorkOrderStatus.ACCEPTED.value,
        "接受": WorkOrderStatus.ACCEPTED.value,
        "arrive": WorkOrderStatus.ARRIVED.value,
        "到达": WorkOrderStatus.ARRIVED.value,
        "complete": WorkOrderStatus.COMPLETED.value,
        "完成": WorkOrderStatus.COMPLETED.value,
    }
    to_status = status_map.get(action_lower)
    if not to_status:
        dingtalk.send_text_notice(sender_userid, f"❓ 未知派工动作: {action}")
        return

    # 按 work_order_no 找工单
    work_order = db.query(WorkOrder).filter(WorkOrder.work_order_no == correlation_id).first()
    if not work_order:
        dingtalk.send_text_notice(sender_userid, f"❌ 未找到工单: {correlation_id}")
        return

    # 按 sender_userid 找维修员用户
    u = _find_or_create_user_by_dtuserid(db, sender_userid)
    if not u:
        dingtalk.send_text_notice(sender_userid, "❌ 无法识别您的身份，请先绑定钉钉账号")
        return

    # 复用工单流转逻辑（延迟 import 避免循环依赖）
    from app.api.work_orders import _do_transition
    transition_data = WorkOrderTransition(to_status=to_status, source="DINGTALK")
    try:
        result = _do_transition(work_order.id, transition_data, db, u)
        dingtalk.send_text_notice(
            sender_userid,
            f"✅ 工单 {correlation_id} 已更新为「{to_status}」状态",
        )
        logger.info(f"[DingTalk] 派工卡片回调成功: {correlation_id} → {to_status} by {u.real_name}")
    except HTTPException as e:
        dingtalk.send_text_notice(sender_userid, f"❌ 操作失败: {e.detail}")
        logger.warning(f"[DingTalk] 派工卡片回调失败: {correlation_id} → {to_status}: {e.detail}")
    except Exception as e:
        dingtalk.send_text_notice(sender_userid, f"❌ 操作异常: {e}")
        logger.error(f"[DingTalk] 派工卡片回调异常: {correlation_id}: {e}")


def _find_or_create_user_by_dtuserid(db: Session, dt_userid: str):
    from app.models.user import User
    u = db.query(User).filter(User.dingtalk_userid == dt_userid).first()
    if u:
        return u
    # 真实模式下尝试调用钉钉用户详情
    try:
        detail = dingtalk.get_user_detail(dt_userid)
        name = detail.get("name") or dt_userid
        dept = detail.get("dept_name") or ""
        title = detail.get("title") or ""
        role = _infer_role(dept, title, dt_userid)
    except Exception:
        name = dt_userid
        role = UserRole.TECHNICIAN.value
        dept = ""
        title = ""
    u = User(
        username=dt_userid,
        password_hash="dingtalk_oauth",
        real_name=name,
        email=f"{dt_userid}@dingtalk.local",
        role=role,
        dingtalk_userid=dt_userid,
        department=dept,
        title=title,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    logger.info(f"[DingTalk][Robot] 自动创建用户 {name} ({dt_userid}) role={role}")
    return u


def _process_text_command(sender_userid: str, text: str, raw: Dict, db: Session):
    """处理纯文本指令。内部异步任务，不抛异常给钉钉 HTTP。"""
    try:
        reply_lines = _dispatch_text_command(sender_userid, text, db)
        if reply_lines:
            dingtalk.send_text_notice(sender_userid, "\n".join(reply_lines))
    except Exception as e:
        logger.exception(f"[DingTalk][Robot] 指令处理失败 text={text[:50]} err={e}")
        try:
            dingtalk.send_text_notice(sender_userid, f"⚠️ 指令处理异常：{str(e)[:80]}")
        except Exception:
            pass


def _dispatch_text_command(sender_userid: str, text: str, db: Session) -> List[str]:
    """指令核心解析。返回纯文本要回复的行列表（空则不回复）。"""
    from app.models.user import User, UserRole
    from app.models.leave_request import LeaveRequest, LeaveRequestStatus

    low = text.lower()
    u = _find_or_create_user_by_dtuserid(db, sender_userid)
    is_supervisor = u.role in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value, UserRole.MANAGER.value)

    # ---------- 帮助 ----------
    if text in ("帮助", "help", "？", "?", "菜单", "功能"):
        return [
            "✅ 机器人支持如下指令：",
            "• 请假 + 日期 + 假别 + 班次 + 理由   例：请假 2026-08-10~2026-08-12 年假 全天 家中有事",
            "• 审批进度     （查看我提交的待审批状态）",
            "• 我的请假     （查看我最近的请假记录）",
            "• 待审批 [主管专用]   （列出当前所有 PENDING 的请假）",
            "• 批准 <请假ID> [顶岗人ID] [备注]  [主管专用]",
            "• 拒绝 <请假ID> <理由>  [主管专用]",
        ]

    # ---------- 请假关键字 → 先走引导卡片 ----------
    if text.startswith("请假") or text.startswith("休假") or text.startswith("请假申请"):
        tail = text[len(text.split()[0]):].strip() if len(text.split()) > 0 else ""
        # 没有参数 → 发引导卡片
        if not tail:
            cid = "DT-" + uuid.uuid4().hex[:12].upper()
            dingtalk.send_leave_submit_guide(sender_userid, cid, submitter_name=u.real_name)
            return [f"已发送请假提交引导（申请编号 {cid}），请按卡片格式回复。"]
        # 有参数 → 直接解析提交
        return _cmd_submit_leave(u, tail, db)

    # ---------- 审批进度 / 我的请假 ----------
    if text in ("审批进度",):
        items = (
            db.query(LeaveRequest)
            .filter(LeaveRequest.requester_id == u.id)
            .filter(LeaveRequest.status.in_([
                LeaveRequestStatus.PENDING.value,
                LeaveRequestStatus.APPROVED.value,
                LeaveRequestStatus.REJECTED.value,
            ]))
            .order_by(LeaveRequest.created_at.desc())
            .limit(5).all()
        )
        if not items:
            return ["暂无请假申请。"]
        out = ["📋 我的请假审批进度："]
        for lr in items:
            ds = sorted({d.leave_date.isoformat() for d in lr.details or []})
            rng = f"{ds[0]}~{ds[-1]}" if len(ds) > 1 else ds[0] if ds else "-"
            out.append(f"• #{lr.id} [{lr.status}] {lr.leave_type} {rng} 理由：{lr.leave_reason or '-'}")
        return out

    if text in ("我的请假",):
        items = (
            db.query(LeaveRequest)
            .filter(LeaveRequest.requester_id == u.id)
            .order_by(LeaveRequest.created_at.desc())
            .limit(10).all()
        )
        if not items:
            return ["暂无请假记录。"]
        out = ["📋 我的最近请假（最近10条）："]
        for lr in items:
            ds = sorted({d.leave_date.isoformat() for d in lr.details or []})
            rng = f"{ds[0]}~{ds[-1]}" if len(ds) > 1 else ds[0] if ds else "-"
            out.append(f"• #{lr.id} [{lr.status}] {lr.leave_type} {rng}")
        return out

    # ---------- 主管专用：待审批 ----------
    if text in ("待审批", "审批列表"):
        if not is_supervisor:
            return ["⚠️ 仅主管可查看审批列表。"]
        items = (
            db.query(LeaveRequest)
            .filter(LeaveRequest.status == LeaveRequestStatus.PENDING.value)
            .order_by(LeaveRequest.created_at.asc())
            .all()
        )
        if not items:
            return ["✅ 暂无待审批请假。"]
        out = [f"⏳ 待审批请假（共{len(items)}条）："]
        for lr in items:
            ds = sorted({d.leave_date.isoformat() for d in lr.details or []})
            rng = f"{ds[0]}~{ds[-1]}" if len(ds) > 1 else ds[0] if ds else "-"
            out.append(f"• #{lr.id} {lr.requester_name} {lr.leave_type} {rng} 理由：{lr.leave_reason or '-'}")
        out.append("回复「批准 <ID> [顶岗人ID] 备注」或「拒绝 <ID> 理由」处理")
        return out

    # ---------- 主管专用：批准 ----------
    m = re.match(r"批准\s+#?(\d+)(.*)", text)
    if m:
        if not is_supervisor:
            return ["⚠️ 仅主管可批准请假。"]
        lr_id = int(m.group(1))
        rest = (m.group(2) or "").strip()
        sub_id = None
        comment = None
        tokens = rest.split()
        if tokens and tokens[0].isdigit():
            sub_id = int(tokens[0])
            comment = " ".join(tokens[1:]) or None
        else:
            comment = rest or None
        return _cmd_approve_leave(u, lr_id, sub_id, comment, db)

    # ---------- 主管专用：拒绝 ----------
    m = re.match(r"拒绝\s+#?(\d+)(.*)", text)
    if m:
        if not is_supervisor:
            return ["⚠️ 仅主管可拒绝请假。"]
        lr_id = int(m.group(1))
        reason = (m.group(2) or "").strip() or "主管拒绝，请联系主管咨询"
        return _cmd_reject_leave(u, lr_id, reason, db)

    # ---------- 未知指令 ----------
    return [
        "❓ 未能识别该指令。回复「帮助」查看支持的指令。",
        f"您的输入：{text[:40]}" + ("…" if len(text) > 40 else ""),
    ]


def _cmd_submit_leave(u, tail: str, db: Session) -> List[str]:
    """tail：「2026-08-10~2026-08-12 年假 全天 家中有事」解析 → 调 API 提交请假。"""
    from app.schemas import LeaveRequestSubmit
    from app.api.leave_requests import submit_leave_request
    from app.core.security import _create_access_token_for_user  # 仅仿真 current_user
    # 空格切 token，最多 5 段（日期/假别/班次/理由）
    tokens = tail.split(None, 3)
    if not tokens:
        return ["⚠️ 缺少日期参数，请按格式输入。例：请假 明天 年假 全天 家中有事"]
    date_tok = tokens[0]
    leave_type_raw = tokens[1] if len(tokens) > 1 else "年假"
    shift_raw = tokens[2] if len(tokens) > 2 else "全天"
    reason = tokens[3] if len(tokens) > 3 else None
    d_from, d_to = _parse_date_token(date_tok)
    if not d_from or not d_to:
        return [f"⚠️ 无法解析日期「{date_tok}」。支持 YYYY-MM-DD / 今天 / 明天 / 2026-08-10~2026-08-12"]
    leave_type = _cn_leave_type(leave_type_raw)
    shift = _cn_shift(shift_raw)

    cid = "DT-" + uuid.uuid4().hex[:12].upper()
    payload = LeaveRequestSubmit(
        requester_id=u.id,
        leave_type=leave_type,
        leave_reason=reason,
        date_from=d_from,
        date_to=d_to,
        shift_of_range=shift,
        correlation_id=cid,
    )
    try:
        # 直接调用内部函数：用当前数据库 session 和 user 对象模拟 Depends(get_current_user)
        from app.api.leave_requests import submit_leave_request as _fn
    except Exception:
        pass
    # 直接 inline 实现，避免 Depends 注入：核心代码
    from app.models.leave_request import LeaveRequest, LeaveRequestDetail, LeaveShift
    from app.api.leave_requests import _parse_details_from_submit, _validate_leave_type, _validate_shift
    from datetime import datetime as _dt
    exist = db.query(LeaveRequest).filter(LeaveRequest.correlation_id == payload.correlation_id).first()
    if not exist:
        pairs = _parse_details_from_submit(payload)
        leave_type = _validate_leave_type(payload.leave_type)
        lr = LeaveRequest(
            requester_id=u.id,
            requester_name=u.real_name or u.username,
            leave_type=leave_type,
            leave_reason=payload.leave_reason,
            status=LeaveRequestStatus.PENDING.value,
            correlation_id=payload.correlation_id,
            submitted_at=_dt.utcnow(),
        )
        db.add(lr)
        db.flush()
        for (ld, ls) in pairs:
            _validate_shift(ls)
            db.add(LeaveRequestDetail(leave_request_id=lr.id, leave_date=ld, leave_shift=ls))
        db.commit()
        db.refresh(lr)
    else:
        lr = exist

    # 异步任务通知主管（不阻塞）
    try:
        _notify_supervisors_leave_submitted(db, lr)
    except Exception as e:
        logger.warning(f"[Leave] 提交后通知主管失败: {e}")

    ds = sorted({d.leave_date.isoformat() for d in lr.details or []})
    rng = f"{ds[0]}~{ds[-1]}" if len(ds) > 1 else ds[0] if ds else "-"
    return [
        f"✅ 请假申请已提交（#{lr.id}，申请编号 {lr.correlation_id}）",
        f"• 日期：{rng}",
        f"• 假别：{lr.leave_type}",
        f"• 理由：{lr.leave_reason or '（无）'}",
        f"• 当前状态：{lr.status}，等待主管审批。",
    ]


def _cmd_approve_leave(current_user, lr_id: int, sub_id: int | None, comment: str | None, db: Session) -> List[str]:
    from app.schemas import LeaveRequestApprove
    from app.api.leave_requests import approve_leave_request as _fn
    try:
        payload = LeaveRequestApprove(substitute_user_id=sub_id, approver_comment=comment)
        resp = _fn(lr_id=lr_id, payload=payload, db=db, current_user=current_user)
    except HTTPException as e:
        return [f"❌ 批准失败：{e.detail}"]
    except Exception as e:
        logger.exception(f"[DingTalk] 批准异常 lr={lr_id}")
        return [f"❌ 批准异常：{str(e)[:80]}"]
    # 通知师傅 + 顶岗人
    try:
        _notify_leave_result(db, resp, "APPROVED")
    except Exception as e:
        logger.warning(f"[Leave] 批准后通知失败: {e}")
    return [
        f"✅ 已批准请假申请 #{resp.get('id')}",
        f"• 申请人：{resp.get('requester_name')}",
        f"• 审批人：{current_user.real_name or current_user.username}",
        (f"• 顶岗人ID：{sub_id}" if sub_id else ""),
    ]


def _cmd_reject_leave(current_user, lr_id: int, reason: str, db: Session) -> List[str]:
    from app.schemas import LeaveRequestReject
    from app.api.leave_requests import reject_leave_request as _fn
    try:
        payload = LeaveRequestReject(approver_comment=reason)
        resp = _fn(lr_id=lr_id, payload=payload, db=db, current_user=current_user)
    except HTTPException as e:
        return [f"❌ 拒绝失败：{e.detail}"]
    except Exception as e:
        logger.exception(f"[DingTalk] 拒绝异常 lr={lr_id}")
        return [f"❌ 拒绝异常：{str(e)[:80]}"]
    try:
        _notify_leave_result(db, resp, "REJECTED")
    except Exception as e:
        logger.warning(f"[Leave] 拒绝后通知失败: {e}")
    return [
        f"✅ 已拒绝请假申请 #{resp.get('id')}",
        f"• 理由：{reason}",
    ]


def _notify_supervisors_leave_submitted(db: Session, lr: "LeaveRequest"):
    """请假提交后 → 拉所有主管，每人推送一张审批卡片（含预检信息）。"""
    from app.models.user import User, UserRole
    from app.api.leave_requests import check_leave_conflicts, _details_to_json
    from app.core import sys_config as sys_conf
    import json as _json

    # 预检
    try:
        pc = check_leave_conflicts(
            requester_id=lr.requester_id,
            date_from=None, date_to=None, shift=None,
            details=_details_to_json(lr.details),
            db=db, current_user=lr.requester,
        )
    except Exception:
        pc = None
    # 顶岗候选人：当天请假日期范围内的其他维修师傅
    leave_dates = sorted({d.leave_date for d in (lr.details or [])})
    sub_candidates = []
    if pc and pc.need_substitute and leave_dates:
        dt1, dt2 = leave_dates[0], leave_dates[-1]
        users = db.query(User).filter(
            User.is_active == True,
            User.role.in_([UserRole.TECHNICIAN.value, UserRole.WORKER.value]),
            User.id != lr.requester_id,
        ).all()
        for u in users:
            sub_candidates.append({"id": u.id, "name": u.real_name or u.username})
    # 日期范围文本
    d_iso = sorted({d.isoformat() for d in leave_dates})
    rng = f"{d_iso[0]} ~ {d_iso[-1]}" if len(d_iso) > 1 else d_iso[0] if d_iso else "-"
    shifts = list({d.leave_shift for d in (lr.details or [])})
    shift_txt = "/".join(shifts) if shifts else "全天"
    shift_cn_map = {"ALL_DAY": "全天", "MORNING": "上午", "AFTERNOON": "下午"}
    shift_txt = "/".join([shift_cn_map.get(s, s) for s in shifts]) if shifts else "全天"

    supervisors = db.query(User).filter(
        User.is_active == True,
        User.role.in_([UserRole.SUPERVISOR.value, UserRole.ADMIN.value, UserRole.MANAGER.value]),
    ).all()
    for sp in supervisors:
        if not sp.dingtalk_userid:
            continue
        try:
            dingtalk.send_leave_approval_card(
                approver_userid=sp.dingtalk_userid,
                lr_id=lr.id,
                correlation_id=lr.correlation_id,
                requester_name=lr.requester_name,
                leave_type=lr.leave_type,
                leave_reason=lr.leave_reason or "",
                date_range_text=rng,
                shift_text=shift_txt,
                pending_work_orders=(pc.pending_work_orders if pc else None),
                on_duty_after=(pc.daily_on_duty_after if pc else None),
                min_guard_count=(pc.min_guard_count if pc else sys_conf.get(db, "min_guard_count", 2)),
                need_substitute=(pc.need_substitute if pc else False),
                substitute_candidates=sub_candidates,
            )
        except Exception as e:
            logger.warning(f"[Leave] 推审批卡片失败给 {sp.dingtalk_userid}: {e}")


def _notify_leave_result(db: Session, resp: Dict, status: str):
    """批准/拒绝后 → 通知师傅本人；批准后若有顶岗人，通知顶岗人。"""
    from app.models.user import User
    lr_id = resp.get("id")
    requester_id = resp.get("requester_id")
    requester_name = resp.get("requester_name")
    leave_type = resp.get("leave_type")
    approver_id = resp.get("approver_id")
    sub_id = resp.get("substitute_user_id")
    approver_comment = resp.get("approver_comment") or ""
    approver_name = ""
    if approver_id:
        au = db.query(User).filter(User.id == approver_id).first()
        approver_name = au.real_name or au.username if au else ""
    sub_name = ""
    if sub_id:
        su = db.query(User).filter(User.id == sub_id).first()
        sub_name = su.real_name or su.username if su else str(sub_id)
    # 日期范围文本
    d_iso = sorted({d["leave_date"].isoformat() if hasattr(d["leave_date"], "isoformat") else str(d["leave_date"]) for d in (resp.get("details") or [])})
    rng = f"{d_iso[0]} ~ {d_iso[-1]}" if len(d_iso) > 1 else d_iso[0] if d_iso else "-"
    # 通知师傅本人
    if requester_id:
        u = db.query(User).filter(User.id == requester_id).first()
        if u and u.dingtalk_userid:
            dingtalk.send_leave_result_notice(
                userid=u.dingtalk_userid,
                requester_name=requester_name,
                leave_type=leave_type,
                date_range_text=rng,
                status=status,
                approver_name=approver_name,
                approver_comment=approver_comment,
                substitute_name=sub_name,
            )
    # 通知顶岗人
    if status == "APPROVED" and sub_id:
        su = db.query(User).filter(User.id == sub_id).first()
        if su and su.dingtalk_userid:
            dingtalk.send_leave_result_notice(
                userid=su.dingtalk_userid,
                requester_name=f"{requester_name}请假，您被指定为顶岗人",
                leave_type=leave_type,
                date_range_text=rng,
                status="APPROVED",
                approver_name=approver_name,
                approver_comment=approver_comment,
                substitute_name="",
            )


# ====================================================================
# Day4 定时任务入口：留接口供外部调度 / 也可以 FastAPI 启动时挂 APScheduler
# ====================================================================

class ScheduleRunResult(BaseModel):
    pushed: int = 0
    urgent: int = 0
    detail: List[Any] = []


@router.post("/schedule/leave-daily-9am", response_model=ScheduleRunResult,
             summary="[定时调用] 每天9点给主管推送待审批汇总卡片")
def leave_daily_9am_task(token: str = Query(..., description="内部调度 token，防止被乱调用"),
                         db: Session = Depends(get_db)):
    """每天 9:00 触发。外部 cron/APScheduler 调此接口即可（需带 settings.SCHEDULER_TOKEN）。"""
    from app.models.user import User, UserRole
    from app.models.leave_request import LeaveRequest, LeaveRequestStatus
    if token != getattr(settings, "SCHEDULER_TOKEN", "sched_token_2026"):
        raise HTTPException(status_code=403, detail="token 不正确")
    items = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.status == LeaveRequestStatus.PENDING.value)
        .order_by(LeaveRequest.created_at.asc())
        .all()
    )
    result = ScheduleRunResult()
    for it in items:
        ds = sorted({d.leave_date.isoformat() for d in it.details or []})
        rng = f"{ds[0]}~{ds[-1]}" if len(ds) > 1 else ds[0] if ds else "-"
        result.detail.append({"id": it.id, "requester_name": it.requester_name,
                              "leave_type": it.leave_type, "date_range": rng})
    supervisors = db.query(User).filter(
        User.is_active == True,
        User.role.in_([UserRole.SUPERVISOR.value, UserRole.ADMIN.value]),
    ).all()
    for sp in supervisors:
        if not sp.dingtalk_userid:
            continue
        ok = dingtalk.send_leave_pending_summary(sp.dingtalk_userid, result.detail)
        if ok:
            result.pushed += 1
    return result


@router.post("/schedule/leave-urgent-check", response_model=ScheduleRunResult,
             summary="[定时调用] 每小时检查一次：待审批超过 N 小时的加急 @ 主管")
def leave_urgent_check(token: str = Query(..., description="调度 token"),
                       db: Session = Depends(get_db)):
    from app.models.user import User, UserRole
    from app.models.leave_request import LeaveRequest, LeaveRequestStatus
    from app.core import sys_config as sys_conf
    if token != getattr(settings, "SCHEDULER_TOKEN", "sched_token_2026"):
        raise HTTPException(status_code=403, detail="token 不正确")
    timeout = sys_conf.get(db, "leave_pending_timeout_hours", 4)
    threshold = datetime.utcnow() - timedelta(hours=timeout)
    pending = (
        db.query(LeaveRequest)
        .filter(LeaveRequest.status == LeaveRequestStatus.PENDING.value)
        .filter(LeaveRequest.submitted_at < threshold)
        .all()
    )
    result = ScheduleRunResult()
    if not pending:
        result.detail.append("无加急项")
        return result
    supervisors = db.query(User).filter(
        User.is_active == True,
        User.role.in_([UserRole.SUPERVISOR.value, UserRole.ADMIN.value]),
    ).all()
    for sp in supervisors:
        if not sp.dingtalk_userid:
            continue
        ok = dingtalk.send_leave_urgent_reminder(sp.dingtalk_userid, len(pending), timeout)
        if ok:
            result.urgent += 1
    result.detail.append(f"共{len(pending)}条超过{timeout}h未处理，已通知{result.urgent}位主管")
    return result


# ============================================================
# Phase 2.1：OA 审批同步相关接口（HTTP 回调 + 手动兜底同步）
# ============================================================

class OASyncResult(BaseModel):
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    details: List[str] = []


@router.post(
    "/event/callback",
    summary="[HTTP模式] 钉钉OA事件HTTP回调入口（Stream模式可不启用）",
)
async def dingtalk_event_http_callback(request: Request):
    """
    钉钉事件订阅 HTTP 回调地址（如果你把事件订阅方式改成 HTTP，钉钉就会向这个地址发 POST）。
    Stream 模式一般不需要启用。

    流程：
      1. 第一次 URL 验证：钉钉会发 GET/POST 带 msg_signature, timestamp, nonce, encrypt
         → 这里返回解密后的明文（一般是 "success"）用于验证 URL
      2. 后续事件推送：解密 → 交给 dingtalk_oa_sync.handle_oa_event 统一处理
    """
    if not OA_CFG.HTTP_CALLBACK_TOKEN or not OA_CFG.HTTP_CALLBACK_AES_KEY:
        logger.warning(
            "[OA-Sync][HTTP-CB] 未配置 DINGTALK_EVENT_TOKEN / DINGTALK_EVENT_AES_KEY，"
            "无法解密钉钉HTTP回调事件。如需使用HTTP回调请在.env配置这两个值。"
        )
        return JSONResponse(status_code=200, content={"msg": "未启用HTTP回调模式（请使用Stream模式或配置AES）"})

    try:
        body = await request.body()
        payload = json.loads(body or "{}") if body else {}
    except Exception:
        payload = {}

    qp = request.query_params or {}
    signature = payload.get("signature") or payload.get("msg_signature") or qp.get("msg_signature") or ""
    timestamp = payload.get("timestamp") or qp.get("timestamp") or str(int(time.time()))
    nonce = payload.get("nonce") or qp.get("nonce") or ""
    encrypt = payload.get("encrypt") or ""

    if not encrypt:
        return "success"

    # 解密（钉钉旧版 AES 解密套件，环境有 dingtalk-sdk 才支持，没有就打日志忽略）
    try:
        from dingtalk.crypto import DingTalkCrypto  # type: ignore
        crypto = DingTalkCrypto(
            OA_CFG.HTTP_CALLBACK_TOKEN,
            OA_CFG.HTTP_CALLBACK_AES_KEY,
            settings.DINGTALK_APP_KEY,
        )
        plaintext = crypto.decrypt(encrypt, signature, timestamp, nonce)
    except ImportError:
        logger.warning("[OA-Sync][HTTP-CB] 未安装 dingtalk-sdk，无法解密HTTP回调事件。"
                       "建议改用Stream模式或 pip install dingtalk-sdk")
        return "success"
    except Exception as e:
        logger.warning(f"[OA-Sync][HTTP-CB] 解密失败: {e}")
        return "success"

    event: Dict[str, Any] = {}
    try:
        event = json.loads(plaintext)
    except Exception:
        event = {"EventType": "unknown", "plaintext": plaintext}

    logger.info(f"[OA-Sync][HTTP-CB] 收到事件: {json.dumps(event, ensure_ascii=False)[:600]}")
    try:
        dingtalk_oa_sync.handle_oa_event(event)
    except Exception as e:
        logger.exception(f"[OA-Sync][HTTP-CB] 处理事件失败: {e}")
    return "success"


@router.post(
    "/schedule/sync-oa-leaves",
    response_model=OASyncResult,
    summary="[手动/定时兜底] 按时间范围扫钉钉OA审批单 → 同步到系统",
)
def sync_oa_leaves_manually(
    days: int = Query(3, ge=1, le=60, description="扫最近多少天的审批单"),
    token: str = Query("", description="内部调度token（可选，防止被乱调用）"),
):
    """
    用法：
      - 你建好模板、填完 .env 的 processCode 后，可以先手动调这个接口把过去 N 天的请假单向系统同步一遍。
      - 未来每天 01:00 APScheduler 会自动跑一次（近 3 天）
    """
    scheduler_token = getattr(settings, "SCHEDULER_TOKEN", None)
    if scheduler_token and token and token != scheduler_token:
        raise HTTPException(status_code=403, detail="token 不正确")
    return sync_recent_oa_leaves(days=days)


def sync_recent_oa_leaves(days: int = 3) -> OASyncResult:
    """扫描最近 days 天钉钉OA里的请假审批单 → 逐个同步入库（内部工具函数，被 cron 和 手动接口复用）"""
    result = OASyncResult()
    if not OA_CFG.LEAVE_PROCESS_CODE:
        msg = "⚠️ 尚未配置 DINGTALK_LEAVE_PROCESS_CODE，跳过兜底同步。"
        logger.info(msg); result.details.append(msg)
        return result

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86400 * 1000
    try:
        pi_ids = dingtalk.list_process_instances_by_time(
            OA_CFG.LEAVE_PROCESS_CODE, start_ms, end_ms, size=max(50, 20 * days),
        )
    except Exception as e:
        logger.exception(f"[OA-Sync][Cron] 拉审批单列表失败: {e}")
        result.details.append(f"拉列表失败: {e}")
        return result

    result.details.append(f"扫到最近 {days} 天共 {len(pi_ids)} 条审批单")
    logger.info(f"[OA-Sync][Cron] 最近{days}天扫到 {len(pi_ids)} 条审批单，开始逐个同步")

    for pid in pi_ids:
        try:
            lr = dingtalk_oa_sync.handle_oa_event({
                "EventType": "bpms_instance_change",
                "processInstanceId": pid,
                "processCode": OA_CFG.LEAVE_PROCESS_CODE,
            })
            if lr:
                result.synced += 1
            else:
                result.skipped += 1
        except Exception as e:
            logger.exception(f"[OA-Sync][Cron] 同步审批单 {pid} 失败: {e}")
            result.failed += 1
            result.details.append(f"同步失败 pid={pid}: {e}")
    result.details.append(f"同步完成：成功{result.synced} / 跳过{result.skipped} / 失败{result.failed}")
    return result


