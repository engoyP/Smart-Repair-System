"""认证相关 API：短信验证码发送/验证、手机号登录、密码重置、钉钉扫码"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from fastapi import Depends
from loguru import logger
import random
import time
import hashlib
import urllib.parse
import uuid
from typing import Optional

from app.core.database import get_db
from app.core.config import settings
from app.core.security import create_access_token, get_current_user, get_optional_user
from app.models.user import User
from datetime import datetime

router = APIRouter()

# 内存存储验证码（生产环境应使用 Redis）
_verify_codes: dict[str, dict] = {}
CODE_EXPIRE_SECONDS = 300  # 5 分钟有效期
CODE_COOLDOWN_SECONDS = 60  # 60 秒内不可重复发送

# 钉钉扫码登录状态管理
# state -> { status: 'pending'|'scanned'|'confirmed'|'expired', user_info: dict, created_at, }
_dingtalk_scan_sessions: dict[str, dict] = {}
SCAN_EXPIRE_SECONDS = 120  # 二维码 120 秒过期（过短会导致扫码授权期间二维码刷新，PC端与手机端 state 失配）
_scan_expire_check_running = False


class SendCodeRequest(BaseModel):
    phone: str
    scene: str = "login"  # login / bind / reset_password


class LoginByCodeRequest(BaseModel):
    phone: str
    code: str


class VerifyCodeRequest(BaseModel):
    phone: str
    code: str
    scene: str = "bind"


class ResetPasswordRequest(BaseModel):
    phone: str
    code: str
    new_password: str


class RegisterRequest(BaseModel):
    phone: str
    code: str
    real_name: str
    password: str


class DingTalkRegisterRequest(BaseModel):
    """钉钉注册：支持扫码（dingtalk_userid + real_name）和账号密码（account + dt_password）"""
    dingtalk_userid: str = ""
    real_name: str = ""
    account: str = ""
    dt_password: str = ""
    password: str


class BindPhoneRequest(BaseModel):
    user_id: int
    phone: str
    code: str


class PasswordLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/send-code", summary="发送短信验证码")
def send_sms_code(req: SendCodeRequest):
    """
    发送短信验证码到手机号。

    - SMS_ENABLED=true 时调用阿里云短信服务发送真实验证码
    - SMS_ENABLED=false 时使用 Mock 模式
    scene: login(登录) / bind(绑定手机) / reset_password(重置密码)
    """
    if not req.phone or len(req.phone) < 11:
        raise HTTPException(status_code=400, detail="请输入正确的手机号")

    # 检查发送频率
    existing = _verify_codes.get(req.phone)
    if existing and time.time() - existing["ts"] < CODE_COOLDOWN_SECONDS:
        remain = int(CODE_COOLDOWN_SECONDS - (time.time() - existing["ts"]))
        raise HTTPException(status_code=429, detail=f"发送过于频繁，请 {remain} 秒后再试")

    # 生成验证码
    from app.core.sms import sms_service
    is_real_sms = sms_service._enabled

    if is_real_sms:
        code = sms_service.generate_code()
    else:
        code = "123456"  # 开发环境固定验证码

    # 存储验证码（Mock 模式使用固定验证码 123456，SMS_ENABLED=false 时）
    _verify_codes[req.phone] = {
        "code": code,
        "ts": time.time(),
        "scene": req.scene,
        "tried": 0,
    }

    # 发送短信
    sms_service.send_code(req.phone, code, req.scene)

    logger.info(f"[Auth] 验证码已发送: phone={req.phone}, scene={req.scene}")

    result = {
        "message": "验证码已发送",
        "phone": req.phone,
        "expire_seconds": CODE_EXPIRE_SECONDS,
        "sms_enabled": is_real_sms,
    }

    if not is_real_sms:
        result["code"] = code  # Mock 模式返回验证码便于调试

    return result


@router.post("/login-by-code", summary="手机号+验证码登录")
def login_by_code(req: LoginByCodeRequest, db: Session = Depends(get_db)):
    """
    手机号 + 验证码登录：
    1. 校验验证码
    2. 查找或创建用户
    3. 返回用户信息
    """
    # 验证码校验
    stored = _verify_codes.get(req.phone)
    if not stored:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    if time.time() - stored["ts"] > CODE_EXPIRE_SECONDS:
        _verify_codes.pop(req.phone, None)
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")
    if stored["code"] != req.code:
        stored["tried"] += 1
        if stored["tried"] >= 5:
            _verify_codes.pop(req.phone, None)
            raise HTTPException(status_code=400, detail="验证码错误次数过多，请重新获取")
        raise HTTPException(status_code=400, detail="验证码错误")

    # 验证通过，清理验证码
    _verify_codes.pop(req.phone, None)

    # 查找用户
    user = db.query(User).filter(User.phone == req.phone).first()
    if not user:
        # 自动创建新用户
        from app.models.user import UserRole
        user = User(
            username=req.phone,
            password_hash="phone_login",
            real_name=f"用户{req.phone[-4:]}",
            phone=req.phone,
            role=UserRole.TECHNICIAN,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"[Auth] 新用户手机登录注册: {req.phone}")

    user.last_login_at = time.strftime("%Y-%m-%d %H:%M:%S")
    db.commit()

    logger.info(f"[Auth] 手机号登录成功: {req.phone}, user={user.real_name}")
    return {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "phone": user.phone,
        "email": user.email or "",
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "department": user.department or "",
        "title": user.title or "",
        "dingtalk_userid": user.dingtalk_userid or "",
        "dingtalk_name": user.dingtalk_name or "",
        "employee_id": user.employee_id or "",
        "token": create_access_token(user.id, user.username),
    }


@router.post("/login-by-password", summary="用户名/手机号+密码登录")
def login_by_password(req: PasswordLoginRequest, db: Session = Depends(get_db)):
    """
    用户名/手机号 + 密码登录
    """
    # 支持用户名或手机号登录
    user = db.query(User).filter(
        (User.username == req.username) | (User.phone == req.username)
    ).first()
    if not user:
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    # 验证密码（主流 sha256；兼容历史 bcrypt 存储的密码，如用户管理页创建的用户）
    import hashlib
    pwd_hash = hashlib.sha256(req.password.encode()).hexdigest()
    if user.password_hash != pwd_hash:
        if user.password_hash.startswith("$2"):
            from app.api.users import pwd_context
            try:
                if not pwd_context.verify(req.password, user.password_hash):
                    raise HTTPException(status_code=400, detail="用户名或密码错误")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=400, detail="用户名或密码错误")
        else:
            raise HTTPException(status_code=400, detail="用户名或密码错误")

    user.last_login_at = time.strftime("%Y-%m-%d %H:%M:%S")
    db.commit()

    logger.info(f"[Auth] 密码登录成功: {req.username}, user={user.real_name}")
    return {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "phone": user.phone or "",
        "email": user.email or "",
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "department": user.department or "",
        "title": user.title or "",
        "dingtalk_userid": user.dingtalk_userid or "",
        "dingtalk_name": user.dingtalk_name or "",
        "employee_id": user.employee_id or "",
        "token": create_access_token(user.id, user.username),
    }


@router.post("/verify-code", summary="验证验证码（绑定手机/找回密码场景）")
def verify_code(req: VerifyCodeRequest):
    """绑定手机号或找回密码时，校验验证码是否有效"""
    stored = _verify_codes.get(req.phone)
    if not stored:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    if time.time() - stored["ts"] > CODE_EXPIRE_SECONDS:
        _verify_codes.pop(req.phone, None)
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")
    if stored["code"] != req.code:
        raise HTTPException(status_code=400, detail="验证码错误")
    if stored.get("scene") != req.scene:
        raise HTTPException(status_code=400, detail="验证码场景不匹配")
    return {"message": "验证通过", "phone": req.phone}


@router.post("/reset-password", summary="通过手机验证码重置密码")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    """
    忘记密码流程：手机号 + 验证码 → 设置新密码
    """
    # 验证码校验
    stored = _verify_codes.get(req.phone)
    if not stored:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    if stored.get("scene") != "reset_password":
        raise HTTPException(status_code=400, detail="请使用找回密码场景的验证码")
    if time.time() - stored["ts"] > CODE_EXPIRE_SECONDS:
        _verify_codes.pop(req.phone, None)
        raise HTTPException(status_code=400, detail="验证码已过期")
    if stored["code"] != req.code:
        raise HTTPException(status_code=400, detail="验证码错误")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少6位")

    _verify_codes.pop(req.phone, None)

    user = db.query(User).filter(User.phone == req.phone).first()
    if not user:
        raise HTTPException(status_code=404, detail="该手机号未绑定任何账号")

    from app.api.users import pwd_context
    user.password_hash = pwd_context.hash(req.new_password)
    db.commit()

    logger.info(f"[Auth] 密码重置成功: phone={req.phone}, user={user.real_name}")
    return {"message": "密码重置成功，请使用新密码登录"}


@router.post("/register", summary="手机号注册")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """
    手机号 + 验证码注册新用户：
    1. 校验验证码
    2. 检查手机号是否已注册
    3. 创建用户
    """
    # 验证码校验
    stored = _verify_codes.get(req.phone)
    if not stored:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    if stored.get("scene") != "register":
        raise HTTPException(status_code=400, detail="请使用注册场景的验证码")
    if time.time() - stored["ts"] > CODE_EXPIRE_SECONDS:
        _verify_codes.pop(req.phone, None)
        raise HTTPException(status_code=400, detail="验证码已过期")
    if stored["code"] != req.code:
        raise HTTPException(status_code=400, detail="验证码错误")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少6位")

    _verify_codes.pop(req.phone, None)

    # 检查手机号是否已注册
    existing = db.query(User).filter(User.phone == req.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="该手机号已注册，请直接登录")

    from app.api.users import pwd_context
    from app.models.user import UserRole
    user = User(
        username=req.phone,
        password_hash=pwd_context.hash(req.password),
        real_name=req.real_name,
        phone=req.phone,
        role=UserRole.TECHNICIAN,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"[Auth] 新用户注册成功: phone={req.phone}, name={req.real_name}")
    return {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "phone": user.phone or "",
        "email": user.email or "",
        "role": UserRole.TECHNICIAN.value,
        "department": user.department or "",
        "title": user.title or "",
        "dingtalk_userid": user.dingtalk_userid or "",
        "dingtalk_name": user.dingtalk_name or "",
        "employee_id": user.employee_id or "",
        "token": create_access_token(user.id, user.username),
        "message": "注册成功",
    }


@router.post("/register-dingtalk", summary="钉钉注册（扫码 / 账号密码）")
def register_dingtalk(req: DingTalkRegisterRequest, db: Session = Depends(get_db)):
    """
    钉钉注册，支持两种方式：
    1. 扫码注册：传 dingtalk_userid + real_name + password
    2. 账号密码注册：传 account + dt_password + password（由后端调用钉钉API验证身份）
    """
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少6位")

    from app.api.users import pwd_context
    from app.models.user import UserRole

    # 扫码注册流程
    if req.dingtalk_userid:
        # 检查是否已注册
        existing = db.query(User).filter(User.dingtalk_userid == req.dingtalk_userid).first()
        if existing:
            raise HTTPException(status_code=400, detail="该钉钉账号已注册，请直接登录")

        user = User(
            username=f"dt_{req.dingtalk_userid}",
            password_hash=pwd_context.hash(req.password),
            real_name=req.real_name,
            dingtalk_userid=req.dingtalk_userid,
            role=UserRole.TECHNICIAN,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"[Auth] 钉钉扫码注册成功: user_id={req.dingtalk_userid}, name={req.real_name}")
        return {
            "id": user.id, "username": user.username, "real_name": user.real_name,
            "phone": user.phone or "",
            "dingtalk_userid": req.dingtalk_userid, "dingtalk_name": user.dingtalk_name or "",
            "role": UserRole.TECHNICIAN.value,
            "token": create_access_token(user.id, user.username),
            "message": "钉钉注册成功",
        }

    # 账号密码注册流程
    if req.account and req.dt_password:
        # 尝试通过钉钉API验证账号密码
        verified_userid = ""
        verified_name = req.account
        try:
            from app.core.dingtalk import dingtalk
            # 尝试用账号获取用户信息来验证身份
            detail = dingtalk.get_user_detail(req.account)
            if detail:
                verified_userid = detail.get("userid", "") or req.account
                verified_name = detail.get("name", "") or req.account
        except Exception:
            # 开发/测试环境跳过验证
            logger.info(f"[Auth] 跳过钉钉密码验证（开发环境）: account={req.account}")
            verified_userid = req.account

        existing = db.query(User).filter(User.dingtalk_userid == verified_userid).first()
        if existing:
            raise HTTPException(status_code=400, detail="该钉钉账号已注册，请直接登录")

        user = User(
            username=f"dt_{verified_userid}",
            password_hash=pwd_context.hash(req.password),
            real_name=verified_name,
            dingtalk_userid=verified_userid,
            role=UserRole.TECHNICIAN,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"[Auth] 钉钉账号密码注册成功: account={req.account}, user_id={verified_userid}")
        return {
            "id": user.id, "username": user.username, "real_name": user.real_name,
            "phone": user.phone or "",
            "dingtalk_userid": verified_userid, "dingtalk_name": user.dingtalk_name or "",
            "role": UserRole.TECHNICIAN.value,
            "token": create_access_token(user.id, user.username),
            "message": "钉钉注册成功",
        }

    raise HTTPException(status_code=400, detail="请提供有效的钉钉信息")


class DingTalkScanCallbackRequest(BaseModel):
    state: str
    code: str = ""
    user_info: dict = {}


@router.post("/dingtalk/scan/generate", summary="生成钉钉扫码URL")
def generate_dingtalk_scan(
    bind_user_id: Optional[int] = Query(None, description="管理员代绑：扫码成功后绑定到该用户ID"),
    self_bind: bool = Query(False, description="当前登录用户自助绑定钉钉"),
):
    """
    生成钉钉扫码 URL。
    - 返回 state（用于前端轮询）和 url（用于渲染二维码）
    - 登录场景：不带任何参数
    - 安全设置页自助绑定：self_bind=true（当前登录用户绑定扫码的钉钉账号）
    - 用户管理页管理员代绑：bind_user_id=目标用户ID
    - 真实模式下 url 指向钉钉 OAuth2 授权页
    - Mock 模式下 url 指向本地模拟授权页
    """
    state = uuid.uuid4().hex
    _dingtalk_scan_sessions[state] = {
        "status": "pending",
        "user_info": {},
        "created_at": time.time(),
        "bind_user_id": bind_user_id,
        "self_bind": self_bind,
    }

    from app.core.dingtalk import dingtalk
    # 关键修复：is_mock 只由 settings.DINGTALK_MOCK_MODE 决定，不再根据 APP_KEY 兜底
    # 若真实模式下缺少配置，明确报错而非静默回退 Mock 导致用户困惑
    is_mock = dingtalk.mock_mode

    if not is_mock and not settings.DINGTALK_APP_KEY:
        logger.error("[DingTalk] 真实模式下 DINGTALK_APP_KEY 为空，请检查 .env 配置是否加载成功")
        raise HTTPException(status_code=500, detail="钉钉配置缺失，请检查后端 DINGTALK_APP_KEY 配置")

    if is_mock:
        # Mock 模式：使用真实 HTTP URL 指向本地模拟授权页，二维码可被手机扫码
        url = f"{settings.SERVER_PUBLIC_URL}/dingtalk/mock-auth?state={state}"
        logger.info(f"[DingTalk][Mock] 生成扫码链接: state={state}")
    else:
        # 真实模式：使用钉钉官方最新 OAuth2 扫码登录 URL
        # 参考：https://open.dingtalk.com/document/development/obtain-identity-credentials
        redirect_uri = f"{settings.SERVER_PUBLIC_URL}/api/v1/dingtalk/callback"
        if settings.DINGTALK_REDIRECT_URI and "localhost" not in settings.DINGTALK_REDIRECT_URI:
            redirect_uri = settings.DINGTALK_REDIRECT_URI

        params = {
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "client_id": settings.DINGTALK_APP_KEY,
            # 钉钉官方文档规定 scope 只支持 "openid" 或 "openid corpid"。
            # 传 "openid" 授权后可获得用户 userid（需应用同时开通成员信息读权限）；
            # 之前的 "openid profile" 不是合法 scope，会导致拿不到 userid 而回退 openId。
            "scope": "openid",
            "prompt": "consent",
            "state": state,
        }
        url = f"https://login.dingtalk.com/oauth2/auth?{urllib.parse.urlencode(params)}"
        logger.info(f"[DingTalk] 生成扫码URL (oauth2/auth): state={state}, redirect_uri={redirect_uri}")

    return {
        "state": state,
        "url": url,
        "expire_seconds": SCAN_EXPIRE_SECONDS,
        "mock_mode": is_mock,
    }


@router.post("/dingtalk/scan/callback", summary="钉钉扫码回调（前端模拟或服务端接收）")
def dingtalk_scan_callback(req: DingTalkScanCallbackRequest):
    """
    处理钉钉扫码后的用户信息回写。
    - 前端在 mock 扫码页面提交用户信息时调用
    - 真实模式下由钉钉重定向到 redirect_uri 后再通过 code 换取
    """
    session = _dingtalk_scan_sessions.get(req.state)
    if not session:
        raise HTTPException(status_code=400, detail="扫码会话不存在或已过期")

    if session["status"] == "confirmed":
        return {"status": "confirmed", "user_info": session["user_info"]}

    if session["status"] == "expired":
        raise HTTPException(status_code=400, detail="二维码已过期")

    user_info = req.user_info or {}
    if req.code and not user_info:
        # 真实模式：通过 code 换取用户信息
        try:
            from app.core.dingtalk import dingtalk
            identity = dingtalk.get_user_by_code(req.code)
            user_info = {
                "userid": identity.get("userid", ""),
                "name": identity.get("name", ""),
                "mobile": identity.get("mobile", ""),
                "union_id": identity.get("union_id", ""),
                "dept": "",
            }
            if user_info.get("userid"):
                detail = dingtalk.get_user_detail(user_info["userid"])
                if detail:
                    is_mock_detail = bool(detail.get("_mock"))
                    # dept/title 始终允许覆盖；name/mobile 仅在 detail 为真实数据时才覆盖（防止 Mock 覆盖真实 nick）
                    user_info["dept"] = detail.get("dept_name", "") or detail.get("title", "") or user_info["dept"]
                    if not is_mock_detail:
                        if detail.get("name"):
                            user_info["name"] = detail["name"]
                        if detail.get("mobile"):
                            user_info["mobile"] = detail["mobile"]
        except Exception as e:
            logger.error(f"[DingTalk] code 换取用户失败: {e}")
            user_info = {"userid": f"mock_{req.code}", "name": "钉钉用户", "dept": "", "_mock": True}

    session["user_info"] = user_info
    session["status"] = "scanned"
    logger.info(f"[DingTalk] 扫码已确认: state={req.state}, user={user_info.get('name', '')}")
    return {"status": "scanned", "user_info": user_info}


@router.get("/dingtalk/scan/status/{state}", summary="查询扫码状态")
def dingtalk_scan_status(state: str):
    """
    前端轮询扫码状态
    - pending: 等待扫码
    - scanned: 已扫码等待确认
    - confirmed: 用户已确认，登录成功
    - expired: 二维码已过期
    """
    session = _dingtalk_scan_sessions.get(state)
    if not session:
        return {"status": "not_found"}

    # 自动过期
    if session["status"] in ("pending", "scanned"):
        if time.time() - session["created_at"] > SCAN_EXPIRE_SECONDS:
            session["status"] = "expired"

    return {
        "status": session["status"],
        "user_info": session.get("user_info", {}),
        "expires_in": max(0, SCAN_EXPIRE_SECONDS - int(time.time() - session["created_at"])),
    }


def _build_login_result(user: User) -> dict:
    """构造登录成功返回体"""
    return {
        "status": "confirmed",
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "employee_id": user.employee_id or "",
        "phone": user.phone or "",
        "email": user.email or "",
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "department": user.department or "",
        "dingtalk_userid": user.dingtalk_userid or "",
        "dingtalk_name": user.dingtalk_name or "",
        "dingtalk_bound_at": user.dingtalk_bound_at.isoformat() if user.dingtalk_bound_at else None,
        "token": create_access_token(user.id, user.username),
    }


@router.post("/dingtalk/scan/confirm/{state}", summary="用户确认扫码")
def dingtalk_scan_confirm(
    state: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    扫码后用户点击"确认"。
    - 登录场景（无绑定参数）：
      已绑定系统账号：直接返回登录态
      未绑定：返回 need_bind 状态，前端引导用户选择"关联已有账号"或"新建账号"
    - 绑定场景（generate 时传了 self_bind / bind_user_id）：
      把扫码的钉钉账号绑定到目标用户，返回 status=bound
    """
    session = _dingtalk_scan_sessions.get(state)
    if not session:
        raise HTTPException(status_code=400, detail="扫码会话不存在或已过期")

    if session["status"] == "expired":
        raise HTTPException(status_code=400, detail="二维码已过期")

    user_info = session.get("user_info", {})
    if not user_info or not user_info.get("userid"):
        raise HTTPException(status_code=400, detail="请先在钉钉端完成扫码")

    dt_userid = user_info["userid"]
    dt_mobile = (user_info.get("mobile") or "").strip()
    dt_name = user_info.get("name") or ""
    dt_dept = user_info.get("dept") or ""
    dt_union_id = user_info.get("union_id") or ""

    # 修复：应用缺通讯录权限时，扫码拿到的是 openId（含字母），不是真实企业 userId。
    # 若有 unionId，则反查真实 userId 后再绑定，避免把 openId 存进 dingtalk_userid。
    if dt_union_id and dt_userid and not str(dt_userid).isdigit():
        from app.core.dingtalk import dingtalk
        resolved_userid = dingtalk._get_userid_by_unionid(dt_union_id)
        if resolved_userid:
            logger.info(
                f"[Auth] 扫码 userid 疑似 openId，已用 unionId 反查为真实 userId: "
                f"{dt_userid} -> {resolved_userid}"
            )
            dt_userid = resolved_userid
            user_info["userid"] = resolved_userid
        else:
            logger.warning(
                f"[Auth] 扫码拿到疑似 openId 且 unionId 反查失败（应用可能缺成员信息读权限），"
                f"将按原值绑定: userid={dt_userid} union_id={dt_union_id}"
            )

    # ========== 绑定模式：安全设置页自助绑定 / 用户管理页管理员代绑 ==========
    bind_user_id = session.get("bind_user_id")
    self_bind = session.get("self_bind")
    if self_bind or bind_user_id:
        if not current_user:
            raise HTTPException(status_code=401, detail="请先登录系统后再扫码绑定钉钉")
        # 防止应用权限不足时 SDK 降级为 Mock 假身份，导致把假 userid 绑进系统。
        # 注意：仅当 userid 本身是 mock 值才算失败；真实扫码但用户详情降级时 userid 仍是真实的。
        if str(dt_userid).startswith("mock_"):
            raise HTTPException(
                status_code=400,
                detail="未获取到真实钉钉身份（应用权限不足）。请先在钉钉开放平台为该应用开通「通讯录个人信息读权限」（Contact.User.Read / qyapi_get_member）并发布新版本，再重新扫码绑定。",
            )
        if bind_user_id:
            from app.models.user import UserRole
            if current_user.role not in (UserRole.SUPERVISOR.value, UserRole.ADMIN.value):
                raise HTTPException(status_code=403, detail="仅主管或管理员可代绑钉钉")
            target = db.query(User).filter(User.id == bind_user_id).first()
            if not target:
                raise HTTPException(status_code=404, detail="目标用户不存在")
        else:
            target = current_user
        existing = (
            db.query(User)
            .filter(User.dingtalk_userid == dt_userid, User.id != target.id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"该钉钉账号已被用户「{existing.real_name}」绑定，请先解绑后再操作",
            )
        target.dingtalk_userid = dt_userid
        target.dingtalk_bound_at = datetime.now()
        if dt_union_id:
            target.dingtalk_union_id = dt_union_id
        if dt_name:
            target.dingtalk_name = dt_name  # 持久化钉钉昵称（权限开通后扫码可拿到）
        if not target.real_name and dt_name:
            target.real_name = dt_name
        if not target.phone and dt_mobile:
            target.phone = dt_mobile
        db.commit()
        session["status"] = "confirmed"
        logger.info(
            f"[Auth] 钉钉扫码绑定成功: target_user={target.id}({target.real_name}), "
            f"dingtalk_userid={dt_userid}, dingtalk_name={target.dingtalk_name}, operator={current_user.id}, "
            f"mode={'self' if self_bind else 'admin'}"
        )
        return {
            "status": "bound",
            "user_id": target.id,
            "real_name": target.real_name or target.username,
            "dingtalk_userid": dt_userid,
            "dingtalk_name": target.dingtalk_name or dt_name,
            "dingtalk_bound_at": target.dingtalk_bound_at.isoformat(),
        }

    user = db.query(User).filter(User.dingtalk_userid == dt_userid).first()

    if user:
        # 已绑定，直接返回登录态
        session["status"] = "confirmed"
        user.last_login_at = datetime.now()
        db.commit()
        logger.info(f"[Auth] 钉钉扫码登录成功(已绑定): user={user.id}")
        return _build_login_result(user)

    # 未绑定 → 尝试通过手机号自动匹配绑定（免手动操作）
    auto_bound = False
    if dt_mobile:
        matched_users = (
            db.query(User)
            .filter(User.phone == dt_mobile, User.dingtalk_userid.is_(None))
            .all()
        )
        if len(matched_users) == 1:
            user = matched_users[0]
            user.dingtalk_userid = dt_userid
            user.dingtalk_bound_at = datetime.now()
            if dt_union_id:
                user.dingtalk_union_id = dt_union_id
            # 补全缺失信息（从钉钉同步）
            if not user.real_name and dt_name:
                user.real_name = dt_name
            if not user.department and dt_dept:
                user.department = dt_dept
            user.last_login_at = datetime.now()
            db.commit()
            session["status"] = "confirmed"
            auto_bound = True
            logger.info(
                f"[Auth] 钉钉扫码自动绑定成功: phone={dt_mobile} -> user={user.id}({user.username})"
            )
            return _build_login_result(user)
        elif len(matched_users) > 1:
            logger.warning(
                f"[Auth] 钉钉手机号匹配到多个系统账号，跳过自动绑定: phone={dt_mobile}, count={len(matched_users)}"
            )

    # 未绑定且无法自动匹配，返回 need_bind，前端弹窗让用户选择"关联已有账号"或"新建账号"
    session["status"] = "need_bind"
    logger.info(
        f"[Auth] 钉钉扫码未绑定系统账号: dingtalk_userid={dt_userid}, phone={dt_mobile}, auto_bound_tried={bool(dt_mobile)}"
    )
    return {
        "status": "need_bind",
        "dingtalk_userid": dt_userid,
        "dingtalk_name": dt_name,
        "dingtalk_mobile": dt_mobile,
        "dingtalk_dept": dt_dept,
        "state": state,
    }


class DingTalkBindByCredentialRequest(BaseModel):
    state: str
    username: str  # 用户名或工号
    password: str


@router.post("/dingtalk/bind-by-credential", summary="钉钉登录时关联已有系统账号")
def dingtalk_bind_by_credential(req: DingTalkBindByCredentialRequest, db: Session = Depends(get_db)):
    """钉钉扫码后未绑定，用户输入系统账号密码完成关联"""
    session = _dingtalk_scan_sessions.get(req.state)
    if not session or session.get("status") != "need_bind":
        raise HTTPException(status_code=400, detail="请先完成钉钉扫码")

    user_info = session.get("user_info", {})
    dt_userid = user_info.get("userid")
    if not dt_userid:
        raise HTTPException(status_code=400, detail="钉钉用户信息缺失")

    # 按用户名/工号查找系统账号；查不到时支持按姓名查找（用户直觉输入姓名）
    candidates = db.query(User).filter(
        (User.username == req.username) | (User.employee_id == req.username)
    ).all()
    if not candidates:
        candidates = db.query(User).filter(User.real_name == req.username).all()
    if not candidates:
        raise HTTPException(status_code=400, detail="系统账号不存在（请输入用户名、工号或姓名）")
    if len(candidates) > 1:
        raise HTTPException(status_code=400, detail="该姓名匹配到多个账号，请改用用户名或工号")
    user = candidates[0]
    if not user.is_active:
        raise HTTPException(status_code=400, detail="账号已被禁用，请联系管理员")

    # 校验密码（主流 sha256，兼容历史 bcrypt 存储的密码）
    from app.api.users import pwd_context
    if not user.password_hash or user.password_hash == "dingtalk_scan":
        raise HTTPException(status_code=400, detail="该账号未设置密码，请使用新建账号或联系管理员重置密码")
    sha_ok = user.password_hash == hashlib.sha256(req.password.encode()).hexdigest()
    bcrypt_ok = False
    if not sha_ok and user.password_hash.startswith("$2"):
        try:
            bcrypt_ok = pwd_context.verify(req.password, user.password_hash)
        except Exception:
            bcrypt_ok = False
    if not (sha_ok or bcrypt_ok):
        raise HTTPException(status_code=400, detail="密码错误")

    # 冲突检测：该钉钉账号是否已被其他用户绑定
    existing_dt = db.query(User).filter(
        User.dingtalk_userid == dt_userid, User.id != user.id
    ).first()
    if existing_dt:
        raise HTTPException(
            status_code=400,
            detail=f"该钉钉账号已被用户「{existing_dt.real_name}」绑定，请联系管理员"
        )

    # 冲突检测：该系统账号是否已绑其他钉钉
    if user.dingtalk_userid and user.dingtalk_userid != dt_userid:
        raise HTTPException(status_code=400, detail="该系统账号已绑定其他钉钉账号，请先解绑")

    # 写入绑定 + 同步钉钉信息（只覆盖空字段）
    user.dingtalk_userid = dt_userid
    user.dingtalk_bound_at = datetime.now()
    if dt_union_id:
        user.dingtalk_union_id = dt_union_id
    if not user.real_name and user_info.get("name"):
        user.real_name = user_info["name"]
    if not user.phone and user_info.get("mobile"):
        user.phone = user_info["mobile"]
    if not user.department and user_info.get("dept"):
        user.department = user_info["dept"]

    db.commit()
    db.refresh(user)
    session["status"] = "confirmed"
    logger.info(f"[Auth] 钉钉关联已有账号成功: user={user.id}, dingtalk_userid={dt_userid}")
    return _build_login_result(user)


class DingTalkCreateNewAccountRequest(BaseModel):
    state: str
    real_name: str
    password: str
    phone: str = ""


@router.post("/dingtalk/create-new-account", summary="钉钉登录时新建系统账号")
def dingtalk_create_new_account(req: DingTalkCreateNewAccountRequest, db: Session = Depends(get_db)):
    """钉钉扫码后未绑定，用户选择新建系统账号"""
    session = _dingtalk_scan_sessions.get(req.state)
    if not session or session.get("status") != "need_bind":
        raise HTTPException(status_code=400, detail="请先完成钉钉扫码")

    user_info = session.get("user_info", {})
    dt_userid = user_info.get("userid")
    if not dt_userid:
        raise HTTPException(status_code=400, detail="钉钉用户信息缺失")

    # 冲突检测
    existing = db.query(User).filter(User.dingtalk_userid == dt_userid).first()
    if existing:
        raise HTTPException(status_code=400, detail="该钉钉账号已关联系统账号，请直接登录")

    from app.api.users import pwd_context
    from app.models.user import UserRole

    # 生成唯一用户名
    base_username = f"dt_{dt_userid}"
    username = base_username
    suffix = 1
    while db.query(User).filter(User.username == username).first():
        username = f"{base_username}_{suffix}"
        suffix += 1

    user = User(
        username=username,
        password_hash=pwd_context.hash(req.password),
        real_name=req.real_name or user_info.get("name", f"钉钉用户_{dt_userid[-4:]}"),
        dingtalk_userid=dt_userid,
        dingtalk_bound_at=datetime.now(),
        phone=req.phone or user_info.get("mobile", ""),
        department=user_info.get("dept", ""),
        role=UserRole.TECHNICIAN,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    session["status"] = "confirmed"
    logger.info(f"[Auth] 钉钉登录新建账号: user={user.id}, dingtalk_userid={dt_userid}")
    return _build_login_result(user)


@router.post("/dingtalk/unbind", summary="解绑当前账号的钉钉")
def dingtalk_unbind(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """已登录用户解绑自己的钉钉账号"""
    if not current_user.dingtalk_userid:
        raise HTTPException(status_code=400, detail="当前账号未绑定钉钉")

    current_user.dingtalk_userid = None
    current_user.dingtalk_bound_at = None
    db.commit()
    logger.info(f"[Auth] 用户解绑钉钉: user={current_user.id}")
    return {"message": "解绑成功"}


@router.post("/bind-phone", summary="绑定手机号")
def bind_phone(req: BindPhoneRequest, db: Session = Depends(get_db)):
    """已登录用户绑定手机号"""
    stored = _verify_codes.get(req.phone)
    if not stored:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    if stored.get("scene") != "bind":
        raise HTTPException(status_code=400, detail="请使用绑定手机的验证码")
    if time.time() - stored["ts"] > CODE_EXPIRE_SECONDS:
        _verify_codes.pop(req.phone, None)
        raise HTTPException(status_code=400, detail="验证码已过期")
    if stored["code"] != req.code:
        raise HTTPException(status_code=400, detail="验证码错误")

    _verify_codes.pop(req.phone, None)

    # 检查手机号是否已被其他账号绑定
    existing = db.query(User).filter(User.phone == req.phone, User.id != req.user_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="该手机号已被其他账号绑定")

    user = db.query(User).filter(User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.phone = req.phone
    db.commit()

    logger.info(f"[Auth] 手机号绑定成功: user={user.real_name}, phone={req.phone}")
    return {"message": "手机号绑定成功", "phone": req.phone}
