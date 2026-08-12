"""钉钉开放平台 SDK 封装

功能：
- 获取 access_token
- 免登 code → 用户身份
- 发送工作通知 / 群消息
- 获取用户详情
- 通讯录同步（部门+用户列表）
- OA 审批：拉审批单详情 / 按时间范围扫列表
- Mock 模式：settings.DINGTALK_MOCK_MODE=True 时全局使用模拟数据
- 临时降级：单次 API 调用失败时本次返回 mock 数据，**不修改全局 mock_mode**
"""
import time
import random
import json
import requests
from datetime import datetime
from typing import Optional, Dict, List, Any
from loguru import logger
from app.core.config import settings


class DingTalkClient:
    """钉钉 API 客户端"""

    BASE_URL = "https://oapi.dingtalk.com"
    NEW_BASE_URL = "https://api.dingtalk.com"

    MOCK_USERS = {
        "mock_worker_001": {
            "userid": "mock_worker_001",
            "name": "张师傅",
            "avatar": "",
            "mobile": "13800138001",
            "title": "设备点检员",
            "dept_name": "运维部",
            "role": "WORKER",
        },
        "mock_tech_001": {
            "userid": "mock_tech_001",
            "name": "李维修",
            "avatar": "",
            "mobile": "13800138002",
            "title": "高级工程师",
            "dept_name": "维修中心",
            "role": "TECHNICIAN",
        },
        "mock_tech_002": {
            "userid": "mock_tech_002",
            "name": "王电工",
            "avatar": "",
            "mobile": "13800138003",
            "title": "电气工程师",
            "dept_name": "维修中心",
            "role": "TECHNICIAN",
        },
        "mock_tech_003": {
            "userid": "mock_tech_003",
            "name": "刘机械",
            "avatar": "",
            "mobile": "13800138004",
            "title": "机械工程师",
            "dept_name": "维修中心",
            "role": "TECHNICIAN",
        },
    }

    def __init__(self):
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        # mock_mode 全局只由 settings 决定，**不允许运行时自动切 True**
        self._mock_mode: Optional[bool] = None
        if settings.DINGTALK_API_TOKEN:
            self._access_token = settings.DINGTALK_API_TOKEN
            self._token_expires_at = float("inf")
            logger.info("[DingTalk] 使用 API Token 直接认证")

    @property
    def mock_mode(self) -> bool:
        """全局 mock 开关：仅由 settings.DINGTALK_MOCK_MODE 决定，永久锁定。"""
        if self._mock_mode is None:
            self._mock_mode = settings.DINGTALK_MOCK_MODE
            if self._mock_mode:
                logger.warning("[DingTalk] Mock 模式已启用（.env 配置），钉钉 API 调用将返回模拟数据")
            else:
                logger.info("[DingTalk] 真实模式已启用（.env 配置）")
        return self._mock_mode

    # 禁用 setter：禁止运行期改变全局 mock_mode
    # （若 DINGTALK_MOCK_MODE 变了，需要重启后端进程才能生效）

    @property
    def app_key(self) -> str:
        return settings.DINGTALK_APP_KEY

    @property
    def app_secret(self) -> str:
        return settings.DINGTALK_APP_SECRET

    @property
    def agent_id(self) -> str:
        return settings.DINGTALK_AGENT_ID

    def _get_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        url = f"{self.BASE_URL}/gettoken"
        resp = requests.get(url, params={"appkey": self.app_key, "appsecret": self.app_secret})
        data = resp.json()

        if data.get("errcode") != 0:
            logger.error(f"[DingTalk] 获取 access_token 失败: {data}")
            raise Exception(f"钉钉认证失败: {data.get('errmsg', 'unknown')}")

        self._access_token = data["access_token"]
        self._token_expires_at = now + data.get("expires_in", 7200) - 300
        logger.info("[DingTalk] access_token 获取成功")
        return self._access_token

    def _get_headers(self) -> dict:
        token = self._get_access_token()
        return {"x-acs-dingtalk-access-token": token}

    def _mock_identity_by_code(self, code: str) -> Dict:
        worker_codes = ["w_001", "worker", "worker01", "zhang", "1", "worker_test"]
        if code.lower() in [c.lower() for c in worker_codes]:
            user = self.MOCK_USERS["mock_worker_001"].copy()
            user["_mock"] = True
            return user

        tech_codes = ["t_001", "tech", "tech01", "li", "2", "tech_test"]
        if code.lower() in [c.lower() for c in tech_codes]:
            user = self.MOCK_USERS["mock_tech_001"].copy()
            user["_mock"] = True
            return user

        tech2_codes = ["t_002", "tech02", "wang", "3"]
        if code.lower() in [c.lower() for c in tech2_codes]:
            user = self.MOCK_USERS["mock_tech_002"].copy()
            user["_mock"] = True
            return user

        tech3_codes = ["t_003", "tech03", "liu", "4"]
        if code.lower() in [c.lower() for c in tech3_codes]:
            user = self.MOCK_USERS["mock_tech_003"].copy()
            user["_mock"] = True
            return user

        if code.startswith("w"):
            user = self.MOCK_USERS["mock_worker_001"].copy()
            user["_mock"] = True
            return user
        if code.startswith("t"):
            user = self.MOCK_USERS["mock_tech_001"].copy()
            user["_mock"] = True
            return user

        user_ids = list(self.MOCK_USERS.keys())
        idx = hash(code) % len(user_ids)
        user = self.MOCK_USERS[user_ids[idx]].copy()
        user["_mock"] = True
        return user

    # ============================================================
    # 免登 code → 用户 identity（H5 微应用内使用）
    # ============================================================
    def get_user_by_code(self, code: str) -> Dict:
        if self.mock_mode:
            user = self._mock_identity_by_code(code)
            logger.info(f"[DingTalk][Mock] 免登: code={code} → {user['name']}")
            return {
                "userid": user["userid"],
                "name": user["name"],
                "avatar": user["avatar"],
                "mobile": user["mobile"],
            }

        try:
            token = self._get_access_token()
        except Exception as e:
            # 临时降级：本次返回 mock，**不改全局 mock_mode**
            logger.warning(f"[DingTalk] 获取 access_token 失败，本次降级到 Mock: {e}")
            user = self._mock_identity_by_code(code)
            return {
                "userid": user["userid"], "name": user["name"],
                "avatar": user["avatar"], "mobile": user["mobile"],
                "_mock": True,
            }

        try:
            headers = {"x-acs-dingtalk-access-token": token}
            resp = requests.get(
                f"{self.NEW_BASE_URL}/v1.0/contact/users/me",
                headers=headers,
                params={"code": code},
                timeout=10,
            )
            data = resp.json()
            if "nick" in data or "userid" in data or "openId" in data:
                userid = data.get("userid") or data.get("userId") or ""
                union_id = data.get("unionId") or ""
                # 缺通讯录权限时可能只返回 openId，用 unionId 反查真实 userId
                if not userid and union_id:
                    userid = self._get_userid_by_unionid(union_id)
                return {
                    "userid": userid or data.get("openId") or "",
                    "name": data.get("nick", ""),
                    "avatar": data.get("avatar", ""),
                    "mobile": data.get("mobile", ""),
                    "union_id": union_id,
                }
            logger.warning(f"[DingTalk] 新版 API 失败，尝试旧版: {data}")
            return self._get_user_by_code_old(code)
        except Exception as e:
            # 临时降级：本次返回 mock，**不改全局 mock_mode**
            logger.warning(f"[DingTalk] 免登失败，本次降级到 Mock: {e}")
            user = self._mock_identity_by_code(code)
            return {
                "userid": user["userid"], "name": user["name"],
                "avatar": user["avatar"], "mobile": user["mobile"],
                "_mock": True,
            }

    # ============================================================
    # OAuth2 扫码登录
    # ============================================================
    def get_user_by_scan_code(self, code: str) -> Dict:
        if self.mock_mode:
            user = self._mock_identity_by_code(code)
            logger.info(f"[DingTalk][Mock] 扫码登录: code={code} → {user['name']}")
            return {
                "userid": user["userid"],
                "name": user["name"],
                "avatar": user["avatar"],
                "mobile": user["mobile"],
            }

        # ========== 方法1：新版 OAuth2 流程 ==========
        try:
            resp = requests.post(
                f"{self.NEW_BASE_URL}/v1.0/oauth2/userAccessToken",
                json={
                    "clientId": self.app_key,
                    "clientSecret": self.app_secret,
                    "code": code,
                    "grantType": "authorization_code",
                },
                timeout=10,
            )
            data = resp.json()
            user_token = data.get("accessToken")
            if user_token:
                logger.info("[DingTalk] OAuth2 userAccessToken 换取成功")
                user_headers = {"x-acs-dingtalk-access-token": user_token}
                user_resp = requests.get(
                    f"{self.NEW_BASE_URL}/v1.0/contact/users/me",
                    headers=user_headers,
                    timeout=10,
                )
                user_data = user_resp.json()
                logger.info(f"[DingTalk] OAuth2 users/me 完整返回: {json.dumps(user_data, ensure_ascii=False)}")
                if "nick" in user_data or "userid" in user_data:
                    userid = user_data.get("userid") or user_data.get("userId") or ""
                    union_id = user_data.get("unionId") or ""
                    # 应用缺通讯录权限时 users/me 可能只返回 openId，此时用 unionId 反查真实 userId
                    if not userid and union_id:
                        userid = self._get_userid_by_unionid(union_id)
                    return {
                        "userid": userid or user_data.get("openId", ""),
                        "name": user_data.get("nick", ""),
                        "avatar": user_data.get("avatar", ""),
                        "mobile": user_data.get("mobile", ""),
                        "union_id": union_id,
                    }
                logger.warning(f"[DingTalk] 新版用户信息获取失败: {user_data}")
        except Exception as e:
            logger.warning(f"[DingTalk] OAuth2 新版流程失败: {e}")

        # ========== 方法2：旧版 OAuth2 流程 ==========
        try:
            token = self._get_access_token()
            resp = requests.post(
                f"{self.BASE_URL}/sns/getuserinfo_bycode",
                params={"access_token": token},
                json={"tmp_auth_code": code},
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode") == 0:
                user_info = data.get("user_info", {})
                logger.info(f"[DingTalk] 旧版 sns 扫码登录成功: {user_info.get('nick', '')}")
                union_id = user_info.get("unionid", "") or ""
                userid = user_info.get("userid", "") or ""
                # openid 不是真实 userId，用 unionId 反查
                if not userid and union_id:
                    userid = self._get_userid_by_unionid(union_id)
                return {
                    "userid": userid or user_info.get("openid", ""),
                    "name": user_info.get("nick", ""),
                    "avatar": "",
                    "mobile": "",
                    "union_id": union_id,
                }
            logger.warning(f"[DingTalk] 旧版 sns 扫码登录失败: {data}")
        except Exception as e:
            logger.warning(f"[DingTalk] 旧版 sns 流程失败: {e}")

        # ========== 方法3：尝试 H5 免登接口 ==========
        try:
            result = self.get_user_by_code(code)
            if result and not result.get("_mock"):
                return result
            logger.warning("[DingTalk] H5免登接口也返回Mock，抛出异常走兜底降级")
            raise Exception("H5免登接口返回Mock")
        except Exception as e:
            logger.error(f"[DingTalk] 所有扫码登录方式均失败，降级Mock: {e}")
            user = self._mock_identity_by_code(code)
            return {
                "userid": user["userid"], "name": user["name"],
                "avatar": user["avatar"], "mobile": user["mobile"],
                "_mock": True,
            }

    def _get_userid_by_unionid(self, union_id: str) -> str:
        """根据 unionId 获取真实企业 userId。

        扫码登录时若应用未返回 userid（可能拿到的是 openId），可用 unionId 调用
        /topapi/user/getbyunionid 反查真实 userId。需要「成员信息读权限」。
        """
        if not union_id:
            return ""
        try:
            token = self._get_access_token()
        except Exception as e:
            logger.warning(f"[DingTalk] 获取 token 失败，无法通过 unionId 解析 userId: {e}")
            return ""
        try:
            resp = requests.post(
                f"{self.BASE_URL}/topapi/user/getbyunionid",
                params={"access_token": token},
                json={"unionid": union_id},
                timeout=10,
            )
            data = resp.json()
            result = data.get("result") or {}
            if data.get("errcode") == 0 and result.get("userid"):
                userid = result["userid"]
                logger.info(f"[DingTalk] 通过 unionId 解析到真实 userId: {userid}")
                return userid
            logger.warning(f"[DingTalk] getbyunionid 解析失败(可能缺成员信息读权限): {data}")
        except Exception as e:
            logger.warning(f"[DingTalk] getbyunionid 异常: {e}")
        return ""

    def _get_user_by_code_old(self, code: str) -> Dict:
        """旧版免登 API"""
        token = self._get_access_token()
        resp = requests.post(
            f"{self.BASE_URL}/topapi/v2/user/getuserinfo",
            params={"access_token": token},
            json={"code": code},
        )
        data = resp.json()
        if data.get("errcode") != 0:
            raise Exception(f"免登失败: {data.get('errmsg')}")
        return data["result"]

    # ============================================================
    # 获取用户详情
    # ============================================================
    def get_user_detail(self, userid: str) -> Dict:
        if self.mock_mode:
            if userid in self.MOCK_USERS:
                user = self.MOCK_USERS[userid]
            else:
                user = self.MOCK_USERS["mock_tech_001"].copy()
                user["userid"] = userid
                user["name"] = f"用户_{userid[-4:]}"
            logger.info(f"[DingTalk][Mock] 获取用户详情: {userid} → {user['name']}")
            return {
                "userid": user["userid"],
                "name": user["name"],
                "mobile": user["mobile"],
                "avatar": user["avatar"],
                "title": user["title"],
                "dept_name": user["dept_name"],
            }

        try:
            token = self._get_access_token()
        except Exception as e:
            logger.warning(f"[DingTalk] 获取用户详情 token 失败，返回空详情(保留扫码nick): {e}")
            # 不再降级生成假名，返回空 dict 让调用方保留已有真实 nick
            return {"_mock": True, "userid": userid, "name": "", "mobile": "", "dept_name": "", "title": ""}

        try:
            headers = {"x-acs-dingtalk-access-token": token}
            resp = requests.get(
                f"{self.NEW_BASE_URL}/v1.0/contact/users/{userid}",
                headers=headers,
                timeout=10,
            )
            data = resp.json()
            if "userid" in data or "nick" in data:
                return {
                    "userid": data.get("userid"),
                    "name": data.get("nick", ""),
                    "mobile": data.get("mobile", ""),
                    "avatar": data.get("avatar", ""),
                    "title": data.get("title", ""),
                    "dept_name": "",
                    "union_id": data.get("unionId") or data.get("unionid", ""),
                }
            logger.warning(f"[DingTalk] 用户详情查询失败(openId可能无权限): {data}")
            # 查不到（如 openId 无 Contact.User.Read 权限）→ 返回空详情，不生成假名覆盖真实 nick
            return {"_mock": True, "userid": userid, "name": "", "mobile": "", "dept_name": "", "title": ""}
        except Exception as e:
            logger.warning(f"[DingTalk] 获取用户详情异常，返回空详情(保留扫码nick): {e}")
            return {"_mock": True, "userid": userid, "name": "", "mobile": "", "dept_name": "", "title": ""}

    def _get_user_detail_old(self, userid: str) -> Dict:
        token = self._get_access_token()
        resp = requests.post(
            f"{self.BASE_URL}/topapi/v2/user/get",
            params={"access_token": token},
            json={"userid": userid},
        )
        data = resp.json()
        if data.get("errcode") != 0:
            raise Exception(f"获取用户失败: {data.get('errmsg')}")
        r = data["result"]
        return {
            "userid": r.get("userid"),
            "name": r.get("name"),
            "mobile": r.get("mobile"),
            "avatar": r.get("avatar"),
            "title": r.get("title"),
            "dept_name": r.get("dept_name_list", [{}])[0].get("name", "") if r.get("dept_name_list") else "",
        }

    # ============================================================
    # 发送工作通知
    # ============================================================
    def send_work_notice(self, userid: str, title: str, content: str, url: str = "") -> bool:
        if self.mock_mode:
            logger.info(f"[DingTalk][Mock] 发送通知给 {userid}: {title}")
            return True

        try:
            token = self._get_access_token()
        except Exception as e:
            logger.warning(f"[DingTalk] 发送通知跳过(无token): {e}")
            return False

        msg = {
            "msgtype": "action_card",
            "action_card": {
                "title": title,
                "markdown": content,
                "single_title": "查看详情",
                "single_url": url or "#",
            },
        }
        try:
            resp = requests.post(
                f"{self.BASE_URL}/topapi/message/corpconversation/asyncsend_v2",
                params={"access_token": token},
                json={"agent_id": int(self.agent_id), "userid_list": userid, "msg": msg},
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode") != 0:
                logger.error(f"[DingTalk] 发送消息失败: {data}")
                return False
            logger.info(f"[DingTalk] 消息已发送给 {userid}")
            return True
        except Exception as e:
            logger.warning(f"[DingTalk] 发送消息异常: {e}")
            return False

    def send_approval_notice(self, userid: str, work_order_no: str, device: str, description: str) -> bool:
        content = f"""## 新工单待处理
        - **工单编号**: {work_order_no}
        - **设备**: {device}
        - **描述**: {description[:60]}
        """
        return self.send_work_notice(userid, f"新工单: {work_order_no}", content)

    def send_dispatch_notice(self, userid: str, work_order_no: str, device: str) -> bool:
        content = f"""## 您有新任务
        - **工单编号**: {work_order_no}
        - **设备**: {device}

        请尽快前往现场处理。
        """
        return self.send_work_notice(userid, f"派工通知: {work_order_no}", content)

    def send_dispatch_workorder(
        self,
        technician_userid: str,
        work_order_no: str,
        device_desc: str,
        fault_description: str,
        work_order_id: int = 0,
        supervisor_name: str = "",
        public_url: str = "",
    ) -> bool:
        """派工通知（增强版 action_card）：包含工单详情 + 点击跳转公网工单页。
        若 technician_userid 为空则直接返回 False（不发钉钉）。
        """
        if not technician_userid:
            logger.info(f"[DingTalk] 维修员未绑定钉钉，跳过通知: 工单{work_order_no}")
            return False

        # 构造公网工单详情页链接
        url = public_url.rstrip("/") + f"/#/work-orders?id={work_order_id}" if public_url else "#"

        fault_short = (fault_description or "（无描述）")[:100]
        sup_text = f"\n**派工人**：{supervisor_name}" if supervisor_name else ""
        content = (
            f"## 📋 新工单派工通知\n\n"
            f"**工单编号**：{work_order_no}\n"
            f"**设备**：{device_desc}\n"
            f"**故障描述**：{fault_short}\n"
            f"{sup_text}\n\n"
            f"请点击「查看详情」进入系统查看完整信息并处理。"
        )
        title = f"派工通知: {work_order_no}"
        logger.info(f"[DingTalk] 发送派工卡片给 {technician_userid}: {work_order_no}")
        return self.send_work_notice(technician_userid, title, content, url=url)

    def send_completion_notice(self, userid: str, work_order_no: str, device: str, summary: str = "") -> bool:
        """维修完成通知"""
        content = f"""## 维修已完成
        - **工单编号**: {work_order_no}
        - **设备**: {device}
        """
        if summary:
            content += f"- **处理结果**: {summary[:80]}\n"
        content += "\n感谢您的工作！"
        return self.send_work_notice(userid, f"工单完成: {work_order_no}", content)

    def send_text_notice(self, userid: str, content: str) -> bool:
        """发送纯文本工作通知（Phase1 专用，不用互动卡片）"""
        if self.mock_mode:
            logger.info(f"[DingTalk][Mock] 发送纯文本通知给 {userid}: {content[:50]}...")
            return True

        try:
            token = self._get_access_token()
        except Exception as e:
            logger.warning(f"[DingTalk] 发送纯文本通知跳过(无token): {e}")
            return False

        msg = {
            "msgtype": "text",
            "text": {
                "content": content,
            },
        }
        try:
            resp = requests.post(
                f"{self.BASE_URL}/topapi/message/corpconversation/asyncsend_v2",
                params={"access_token": token},
                json={"agent_id": int(self.agent_id), "userid_list": userid, "msg": msg},
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode") != 0:
                logger.error(f"[DingTalk] 发送纯文本消息失败: {data}")
                return False
            logger.info(f"[DingTalk] 纯文本消息已发送给 {userid}")
            return True
        except Exception as e:
            logger.warning(f"[DingTalk] 发送纯文本消息异常: {e}")
            return False

    def send_inventory_alert(self, userid: str, items: List[Dict]) -> bool:
        """库存预警通知"""
        if not items:
            return True
        item_lines = "\n".join([
            f"- **{i.get('part_name', '')}** ({i.get('part_code', '')}): "
            f"当前 {i.get('stock', 0)} / 安全 {i.get('safety', 0)}"
            for i in items[:10]
        ])
        content = f"""## ⚠️ 库存预警
        以下备件库存低于安全线：
        {item_lines}

        请及时补货，避免影响维修作业。
        """
        return self.send_work_notice(userid, "库存预警通知", content)

    def send_approval_request(self, userid: str, work_order_no: str, device: str,
                               confidence: float, description: str, url: str = "") -> bool:
        """工单待人工审核通知（置信度仅作参考展示）"""
        level = "低" if confidence < 0.5 else "中"
        content = f"""## 待审核工单
        - **工单编号**: {work_order_no}
        - **设备**: {device}
        - **置信度**: {confidence:.0%}（{level}）
        - **描述**: {description[:100]}

        请尽快处理，点击下方按钮前往审核。
        """
        return self.send_work_notice(
            userid,
            f"待审核: {work_order_no}",
            content,
            url=url or f"/work-orders?filter=pending",
        )

    # ============================================================
    # 通讯录
    # ============================================================
    def get_department_list(self) -> List[Dict]:
        """获取部门列表"""
        if self.mock_mode:
            logger.info("[DingTalk][Mock] 获取部门列表")
            return [
                {"dept_id": 1, "name": "运维部", "parent_id": 0, "order": 1},
                {"dept_id": 2, "name": "维修中心", "parent_id": 0, "order": 2},
                {"dept_id": 3, "name": "电气维修组", "parent_id": 2, "order": 1},
                {"dept_id": 4, "name": "机械维修组", "parent_id": 2, "order": 2},
            ]

        try:
            token = self._get_access_token()
        except Exception as e:
            logger.warning(f"[DingTalk] 获取部门列表 token 失败，本次降级 Mock: {e}")
            return [
                {"dept_id": 1, "name": "运维部", "parent_id": 0, "order": 1},
                {"dept_id": 2, "name": "维修中心", "parent_id": 0, "order": 2},
            ]

        try:
            resp = requests.post(
                f"{self.BASE_URL}/topapi/v2/department/listsub",
                params={"access_token": token},
                json={"dept_id": 0},
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode") != 0:
                raise Exception(f"获取部门列表失败: {data.get('errmsg')}")
            return data.get("result", [])
        except Exception as e:
            logger.warning(f"[DingTalk] 获取部门列表失败，本次降级 Mock: {e}")
            return [
                {"dept_id": 1, "name": "运维部", "parent_id": 0, "order": 1},
                {"dept_id": 2, "name": "维修中心", "parent_id": 0, "order": 2},
            ]

    def get_user_list(self, dept_id: int = 0) -> List[Dict]:
        """获取用户列表"""
        if self.mock_mode:
            logger.info(f"[DingTalk][Mock] 获取用户列表 dept={dept_id}")
            users = list(self.MOCK_USERS.values())
            result = []
            for u in users:
                result.append({
                    "userid": u["userid"],
                    "name": u["name"],
                    "mobile": u["mobile"],
                    "title": u["title"],
                    "dept_name": u["dept_name"],
                    "role": u["role"],
                    "active": True,
                })
            return result

        try:
            token = self._get_access_token()
        except Exception as e:
            logger.warning(f"[DingTalk] 获取用户列表 token 失败，本次降级 Mock: {e}")
            return list(self.MOCK_USERS.values())

        try:
            resp = requests.post(
                f"{self.BASE_URL}/topapi/v2/user/list",
                params={"access_token": token},
                json={"dept_id": dept_id, "cursor": 0, "size": 100},
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode") != 0:
                raise Exception(f"获取用户列表失败: {data.get('errmsg')}")
            return data.get("result", {}).get("list", [])
        except Exception as e:
            logger.warning(f"[DingTalk] 获取用户列表失败，本次降级 Mock: {e}")
            return list(self.MOCK_USERS.values())

    def sync_contacts(self) -> Dict:
        """同步通讯录：拉取部门+用户列表"""
        logger.info("[DingTalk] 开始通讯录同步")
        departments = self.get_department_list()
        users = self.get_user_list()

        logger.info(f"[DingTalk] 同步完成: {len(departments)} 个部门, {len(users)} 个用户")
        return {
            "departments": departments,
            "users": users,
            "total_departments": len(departments),
            "total_users": len(users),
        }

    def send_work_notice_to_admin(self, title: str, content: str, url: str = "") -> bool:
        """向管理员发送通知"""
        admin_ids = self._get_admin_userids()
        if not admin_ids:
            logger.warning("[DingTalk] 无管理员可通知")
            return False
        results = []
        for uid in admin_ids:
            results.append(self.send_work_notice(uid, title, content, url))
        return any(results)

    def _get_admin_userids(self) -> List[str]:
        if self.mock_mode:
            return ["mock_admin_001"]
        try:
            token = self._get_access_token()
            resp = requests.post(
                f"{self.BASE_URL}/topapi/v2/user/list",
                params={"access_token": token},
                json={"dept_id": 0, "cursor": 0, "size": 100},
                timeout=10,
            )
            data = resp.json()
            if data.get("errcode") == 0:
                users = data.get("result", {}).get("list", [])
                return [u["userid"] for u in users if u.get("is_admin")]
        except Exception:
            pass
        return []

    # ============================================================
    # OA 审批专用 API
    # ============================================================
    def get_process_instance(self, process_instance_id: str) -> Dict[str, Any]:
        """根据 processInstanceId 拉取 OA 审批单详情（用于审批事件到达后解析字段）"""
        if self.mock_mode:
            logger.info(f"[DingTalk][Mock] get_process_instance {process_instance_id}")
            return {
                "processInstanceId": process_instance_id,
                "processCode": "MOCK_LEAVE_PROCESS",
                "originatorUserid": "mock_tech_001",
                "title": "请假申请",
                "result": {"processResult": "agree", "remark": "mock通过"},
                "status": "COMPLETED",
                "approvers": ["mock_admin_001"],
                "formComponentValues": [
                    {"name": "leave_type", "value": "年假"},
                    {"name": "leave_date_range", "value": "2026-08-10 至 2026-08-11"},
                    {"name": "shift", "value": "全天"},
                    {"name": "note", "value": "家中有事"},
                    {"name": "replacement_user", "value": "mock_tech_002"},
                ],
                "createTime": int(datetime.now().timestamp() * 1000),
                "finishTime": int(datetime.now().timestamp() * 1000),
            }

        try:
            token = self._get_access_token()
        except Exception as e:
            raise Exception(f"获取 access_token 失败: {e}")

        # 优先尝试新版 v1.0 API
        # 官方文档: GET /v1.0/workflow/processInstances?processInstanceId=xxx
        # 参数 processInstanceId 放在 Query 字符串里，不是路径！
        try:
            headers = {"x-acs-dingtalk-access-token": token}
            resp = requests.get(
                f"{self.NEW_BASE_URL}/v1.0/workflow/processInstances",
                params={"processInstanceId": process_instance_id},
                headers=headers,
                timeout=20,
            )
            data = resp.json()
            # 新版API返回 {'result': {...}, 'success': True}，真实数据在 result 子对象里
            if isinstance(data, dict) and isinstance(data.get("result"), dict) and data.get("success") is True:
                return data["result"]
            # 有些版本直接在根级返回
            is_valid = (
                isinstance(data, dict)
                and (
                    "processCode" in data
                    or "processInstanceId" in data
                    or "formComponentValues" in data
                    or "title" in data
                    or "businessId" in data
                    or "originatorUserId" in data
                )
            )
            if is_valid:
                return data
            if isinstance(data, dict) and isinstance(data.get("data"), dict):
                inner = data["data"]
                if (
                    "processCode" in inner
                    or "processInstanceId" in inner
                    or "formComponentValues" in inner
                    or "title" in inner
                    or "businessId" in inner
                ):
                    return inner
            logger.warning(f"[DingTalk] 新版 get_process_instance 返回结构异常（将走旧版API兜底）: {str(data)[:500]}")
        except Exception as e:
            logger.warning(f"[DingTalk] 新版 get_process_instance 调用失败，切旧版: {e}")

        # 回退到旧版 topapi
        try:
            resp = requests.post(
                f"{self.BASE_URL}/topapi/processinstance/get",
                params={"access_token": token},
                json={"process_instance_id": process_instance_id},
                timeout=20,
            )
            data = resp.json()
            if data.get("errcode") != 0:
                raise Exception(f"旧版审批详情错误: {data.get('errmsg')}")
            return data.get("process_instance") or {}
        except Exception as e:
            logger.exception(f"[DingTalk] 旧版 get_process_instance 失败: {e}")
            raise

    def list_process_instances_by_time(
        self,
        process_code: str,
        start_time_ms: int,
        end_time_ms: int,
        size: int = 20,
    ) -> List[str]:
        """按时间范围批量扫审批单 → 返回 processInstanceId 列表（兜底同步用）"""
        if self.mock_mode or not process_code:
            return []
        try:
            token = self._get_access_token()
        except Exception as e:
            logger.warning(f"[DingTalk] list_process_instances_by_time 获取 token 失败: {e}")
            return []
        try:
            resp = requests.post(
                f"{self.BASE_URL}/topapi/processinstance/listids",
                params={"access_token": token},
                json={
                    "process_code": process_code,
                    "start_time": start_time_ms,
                    "end_time": end_time_ms,
                    "size": size,
                    "cursor": 0,
                },
                timeout=20,
            )
            data = resp.json()
            if data.get("errcode") != 0:
                logger.warning(f"[DingTalk] list_process_instances_by_time 失败: {data}")
                return []
            return list(data.get("result", {}).get("list", []) or [])
        except Exception as e:
            logger.warning(f"[DingTalk] list_process_instances_by_time 异常: {e}")
            return []


    # ============================================================
    # Phase 2.1: 请假流程专用卡片推送（B3 互动卡片简版）
    # 说明：
    # - 钉钉互动卡片创建需要先在开放平台创建卡片模板并拿到 templateId，
    #   这一步没有模板时我们采用「action_card（单按钮 markdown」+「文字指令」的替代实现：
    #   师傅端用 markdown 卡片承载表单式纯文本（实际生产环境用 Forms 互动卡片升级）。
    # - 这里提供：提交表单引导卡片、主管审批卡片(携带预检查信息)、审批结果通知
    # ============================================================

    def send_leave_submit_guide(self, userid: str, correlation_id: str,
                                submitter_name: str = "") -> bool:
        """师傅触发「请假」关键字后，机器人推送提交引导卡片。
        correlation_id 用于后续幂等。
        （Phase1 使用 action_card 引导师傅点击跳转/回复关键字完成。
        """
        if self.mock_mode:
            logger.info(f"[DingTalk][Mock] 推送请假引导卡片给 {userid}, cid={correlation_id}")
            return True
        title = "请假申请"
        # 用 action_card 说明请假提交流程：
        # 师傅点「填写请假申请」回复：请假-{cid}」，也支持的提交请假提交的提交请假提交。
        content = (
            f"## 📋 **请假申请流程引导\n\n"
            f"申请人：{submitter_name or '您'}\n\n"
            f"**请按如下格式回复本机器人提交申请：\n\n"
            f"> `请假` + 空格 + 日期 + 空格 + 假别 + 空格 + 班次 + 理由\n\n"
            f"**示例**：\n"
            f"> 请假 2026-08-10~2026-08-12 年假 全天 家中有事\n\n"
            f"> 请假 2026-08-15 病假 上午 发烧去医院\n\n"
            f"**支持假别**：年假 / 病假 / 事假 / 调休 / 婚假 / 产假 / 丧假 / 其他\n"
            f"**支持班次**：全天 / 上午 / 下午\n\n"
            f"申请编号：`{correlation_id}`\n"
            f"（也可直接回复「帮助」查看更多"
        )
        return self.send_work_notice(userid, title, content)

    def send_leave_approval_card(
        self,
        approver_userid: str,
        lr_id: int,
        correlation_id: str,
        requester_name: str,
        leave_type: str,
        leave_reason: str,
        date_range_text: str,
        shift_text: str,
        pending_work_orders: List[Dict] | None = None,
        on_duty_after: Dict[str, int] | None = None,
        min_guard_count: int = 2,
        need_substitute: bool = False,
        substitute_candidates: List[Dict] | None = None,
        web_url: str = "",
    ) -> bool:
        """推送请假审批卡片给主管。若 DINGTALK_MOCK_MODE=True 时直接 log 跳过。
        卡片内携带：冲突工单、每天剩余值班人数、是否需指定顶岗人、顶岗候选人列表。
        """
        if self.mock_mode:
            logger.info(
                f"[DingTalk][Mock] 推送审批卡片给 {approver_userid} "
                f"lr_id={lr_id} 申请人={requester_name}"
            )
            return True
        title = "待审批：" + requester_name + "的" + leave_type + "申请"
        wo_lines = ""
        if pending_work_orders:
            lines = []
            for w in (pending_work_orders or [])[:5]:
                no = w.get("work_order_no") or ""
                st = w.get("status") or ""
                desc = (w.get("fault_description") or "")[:20]
                lines.append(f"- #{no} [{st}] {desc}")
            wo_lines = "\n".join(lines)
            wo_lines = f"\n⚠️ **未完成工单冲突（{len(pending_work_orders)}条，请先转派）**\n{wo_lines}\n"
        duty_lines = ""
        if on_duty_after:
            items = sorted(on_duty_after.items())
            duty_lines = "\n".join([f"- {d}: 剩余{v}人" for d, v in items])
            duty_lines = f"\n👥 **审批后每日剩余值班人数**\n{duty_lines}\n"
        sub_lines = ""
        if need_substitute:
            sub_lines = "\n🔴 **在岗人数将低于最低值({})，**批准时必须指定顶岗人：\n".format(min_guard_count)
            if substitute_candidates:
                sub_lines += "候选顶岗人：" + "、".join(
                    [f"{c.get('name','')}(ID:{c.get('id','')})" for c in substitute_candidates[:8]]
                ) + "\n"
        url_tip = web_url or f"#/leave-requests/{lr_id}"
        content = (
            f"## 📝 请假审批 #{lr_id}\n\n"
            f"**申请人**：{requester_name}\n"
            f"**假别**：{leave_type}\n"
            f"**请假时段**：{date_range_text}（{shift_text}）\n"
            f"**理由**：{leave_reason or '（无）'}\n"
            f"**申请编号**：`{correlation_id}`\n"
            f"{wo_lines}{duty_lines}{sub_lines}\n"
            f"请点击「查看详情」进入主管端审批页面进行批准或回复指令处理。"
        )
        return self.send_work_notice(approver_userid, title, content, url=url_tip)

    def send_leave_result_notice(
        self,
        userid: str,
        requester_name: str,
        leave_type: str,
        date_range_text: str,
        status: str,
        approver_name: str = "",
        approver_comment: str = "",
        substitute_name: str = "",
    ) -> bool:
        """审批完成通知 - 推送给师傅本人；APPROVED 时还可推送给顶岗人（外部调用两次）。"""
        if self.mock_mode:
            logger.info(
                f"[DingTalk][Mock] 审批结果通知 {userid} 状态={status}"
            )
            return True
        status_text = {"APPROVED": "✅ 已批准", "REJECTED": "❌ 已拒绝", "CANCELLED": "🚫 已撤销"}.get(status, status)
        title = f"请假申请{status_text}"
        sub_text = ""
        if status == "APPROVED" and substitute_name:
            sub_text = f"**顶岗人**：{substitute_name}\n"
        cm_text = f"**审批备注**：{approver_comment}\n" if approver_comment else ""
        ap_text = f"**审批人**：{approver_name}\n" if approver_name else ""
        content = (
            f"## {status_text}\n\n"
            f"**申请人**：{requester_name}\n"
            f"**假别**：{leave_type}\n"
            f"**请假时段**：{date_range_text}\n"
            f"{ap_text}{sub_text}{cm_text}"
        )
        return self.send_work_notice(userid, title, content)

    def send_leave_pending_summary(
        self,
        approver_userid: str,
        pending_items: List[Dict],
    ) -> bool:
        """每天早上 9 点推送待办汇总卡片给主管。"""
        if self.mock_mode:
            logger.info(f"[DingTalk][Mock] 推送请假待办汇总给 {approver_userid} 共{len(pending_items)}条")
            return True
        title = f"请假待办汇总（{len(pending_items)}条）"
        lines = "\n".join([
            f"- {p.get('requester_name','')} {p.get('leave_type','')} {p.get('date_range','')} "
            f"#{p.get('id','')}"
            for p in pending_items[:15]
        ])
        more = f"\n（还有 {len(pending_items)-15} 条未显示…" if len(pending_items) > 15 else ""
        content = (
            f"## 📋 今日请假审批待办\n\n"
            f"当前待审批 **{len(pending_items)}** 条：\n{lines}{more}\n\n"
            f"请及时处理，点击「查看详情」前往主管端审批页。"
        )
        return self.send_work_notice(approver_userid, title, content, url="#/leave-requests")

    def send_leave_urgent_reminder(
        self,
        approver_userid: str,
        pending_count: int,
        timeout_hours: int,
    ) -> bool:
        """超过 N 小时未处理，加急催办。"""
        if self.mock_mode:
            logger.info(f"[DingTalk][Mock] 加急催办 {approver_userid} pending={pending_count}")
            return True
        title = "⚠️ 加急：请假待审批催办"
        content = (
            f"## ⚠️ 加急催办\n\n"
            f"您有 **{pending_count}** 条请假申请已超过 **{timeout_hours}** 小时未处理。\n\n"
            f"请尽快审批，避免师傅空等。点击「查看详情」进入审批页。"
        )
        return self.send_work_notice(approver_userid, title, content, url="#/leave-requests")

    def send_text_to_robot_conversation(self, conversation_id: str, userid: str, text: str) -> bool:
        """机器人在单聊里回复一条纯文本（用于指令解析后的直接回复）。
        用工作通知替代：单聊机器人回复无 conversation_id 暂用工作通知顶替代。"""
        return self.send_text_notice(userid, text)


dingtalk = DingTalkClient()


def send_dispatch_workorder(user_id: int, work_order: dict) -> bool:
    """派发工单钉钉通知（纯文本 Phase1）"""
    try:
        from app.core.database import SessionLocal
        from app.models.user import User

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
        finally:
            db.close()

        if not user:
            logger.warning(f"[DingTalk][Dispatch] 用户不存在: user_id={user_id}")
            return False
        if not user.dingtalk_userid:
            logger.warning(
                f"[DingTalk][Dispatch] 用户未绑定钉钉，无法发送通知: "
                f"user_id={user_id}, real_name={user.real_name}"
            )
            return False

        wo_no = work_order.get("work_order_no", "")
        device_code = work_order.get("device_code") or "-"
        location = work_order.get("location") or "-"
        priority = work_order.get("priority", "-")
        fault_desc = work_order.get("fault_description", "") or ""
        fault_trunc = fault_desc[:50] if fault_desc else "-"
        wo_id = work_order.get("id", "")

        content = (
            f"【新维修任务】工单{wo_no}派给您\n"
            f"设备：{device_code}\n"
            f"位置：{location}\n"
            f"优先级：{priority}\n"
            f"故障：{fault_trunc}\n"
            f"请尽快前往处理，点击链接查看详情：{settings.SERVER_PUBLIC_URL}/#/work-orders/{wo_id}"
        )

        return dingtalk.send_text_notice(user.dingtalk_userid, content)
    except Exception as e:
        logger.warning(f"[DingTalk][Dispatch] 发送派工通知异常: {e}")
        return False


def send_progress_notice(
    receiver_user_ids: List[int],
    work_order: dict,
    from_status: str,
    to_status: str,
    operator_name: str,
    remark: str | None = None,
) -> bool:
    """工单进度更新钉钉通知（纯文本 Phase1）"""
    try:
        from app.core.database import SessionLocal
        from app.models.user import User, UserRole

        db = SessionLocal()
        try:
            all_receivers = list(receiver_user_ids) if receiver_user_ids else []

            supervisor_users = (
                db.query(User)
                .filter(User.role == UserRole.SUPERVISOR.value, User.is_active == True)
                .all()
            )
            for su in supervisor_users:
                if su.id not in all_receivers:
                    all_receivers.append(su.id)

            if not all_receivers:
                logger.warning("[DingTalk][Progress] 无接收人，跳过进度通知")
                return False

            users = db.query(User).filter(User.id.in_(all_receivers)).all()
        finally:
            db.close()

        if not users:
            logger.warning("[DingTalk][Progress] 接收人查询为空")
            return False

        wo_no = work_order.get("work_order_no", "")
        device_code = work_order.get("device_code") or "-"
        wo_id = work_order.get("id", "")
        from_s = from_status or "-"
        to_s = to_status or "-"
        rmk = remark or "-"

        content = (
            f"【工单进度】{wo_no} 已更新\n"
            f"由 {operator_name} 操作：{from_s} → {to_s}\n"
            f"备注：{rmk}\n"
            f"设备：{device_code}\n"
            f"详情：{settings.SERVER_PUBLIC_URL}/#/work-orders/{wo_id}"
        )

        any_sent = False
        for u in users:
            if not u.dingtalk_userid:
                logger.warning(
                    f"[DingTalk][Progress] 用户未绑钉钉，跳过: "
                    f"user_id={u.id}, real_name={u.real_name}"
                )
                continue
            if dingtalk.send_text_notice(u.dingtalk_userid, content):
                any_sent = True
        return any_sent
    except Exception as e:
        logger.warning(f"[DingTalk][Progress] 发送进度通知异常: {e}")
        return False


def send_completion_notice(
    receiver_user_ids: List[int],
    work_order: dict,
    operator_name: str,
    work_hours: float | None = None,
) -> bool:
    """工单维修完成钉钉通知（纯文本 Phase1）"""
    try:
        from app.core.database import SessionLocal
        from app.models.user import User

        db = SessionLocal()
        try:
            users = (
                db.query(User)
                .filter(User.id.in_(receiver_user_ids or []))
                .all()
            )
        finally:
            db.close()

        if not users:
            logger.warning("[DingTalk][Completion] 接收人查询为空")
            return False

        wo_no = work_order.get("work_order_no", "")
        device_code = work_order.get("device_code") or "-"
        fault_desc = work_order.get("fault_description", "") or ""
        fault_trunc = fault_desc[:50] if fault_desc else "-"
        wo_id = work_order.get("id", "")
        hours = f"{work_hours}" if work_hours is not None else "-"

        content = (
            f"【维修完成】工单{wo_no}已处理完毕\n"
            f"操作人：{operator_name}\n"
            f"耗时：{hours}小时\n"
            f"设备：{device_code}\n"
            f"故障：{fault_trunc}\n"
            f"请在维修知识库可查阅详情：{settings.SERVER_PUBLIC_URL}/#/work-orders/{wo_id}"
        )

        any_sent = False
        for u in users:
            if not u.dingtalk_userid:
                logger.warning(
                    f"[DingTalk][Completion] 用户未绑钉钉，跳过: "
                    f"user_id={u.id}, real_name={u.real_name}"
                )
                continue
            if dingtalk.send_text_notice(u.dingtalk_userid, content):
                any_sent = True
        return any_sent
    except Exception as e:
        logger.warning(f"[DingTalk][Completion] 发送完成通知异常: {e}")
        return False

