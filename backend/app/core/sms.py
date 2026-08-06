"""短信服务模块 — 阿里云短信 SDK 封装"""
import json
import random
from loguru import logger
from app.core.config import settings


class SMSService:
    """短信发送服务，封装阿里云 SMS SDK"""

    def __init__(self):
        self._client = None
        self._enabled = settings.SMS_ENABLED

    def _get_client(self):
        """懒加载阿里云 SMS 客户端"""
        if self._client is not None:
            return self._client

        if not self._enabled:
            logger.info("[SMS] 未启用真实短信服务，使用控制台输出")
            return None

        try:
            from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
            from alibabacloud_tea_openapi import models as open_api_models

            access_key_id = settings.SMS_ACCESS_KEY_ID
            access_key_secret = settings.SMS_ACCESS_KEY_SECRET

            if not access_key_id or not access_key_secret:
                logger.warning("[SMS] AccessKey 未配置，降级为控制台输出")
                self._enabled = False
                return None

            config = open_api_models.Config(
                access_key_id=access_key_id,
                access_key_secret=access_key_secret,
            )
            config.endpoint = "dysmsapi.aliyuncs.com"
            self._client = DysmsapiClient(config)
            logger.info("[SMS] 阿里云短信客户端初始化成功")
            return self._client
        except ImportError:
            logger.warning("[SMS] alibabacloud_dysmsapi20170525 未安装，降级为控制台输出")
            self._enabled = False
            return None
        except Exception as e:
            logger.error(f"[SMS] 客户端初始化失败: {e}")
            self._enabled = False
            return None

    def generate_code(self) -> str:
        """生成 6 位随机验证码"""
        return f"{random.randint(0, 999999):06d}"

    def send_code(self, phone: str, code: str, scene: str = "login") -> bool:
        """
        发送短信验证码

        Args:
            phone: 手机号码
            code: 验证码
            scene: 场景标识 (login/register/bind/reset_password)

        Returns:
            是否发送成功
        """
        scene_labels = {
            "login": "登录验证",
            "register": "注册验证",
            "bind": "绑定手机",
            "reset_password": "重置密码",
        }
        scene_label = scene_labels.get(scene, "身份验证")

        client = self._get_client()

        if client is None:
            # 未启用真实短信：打印到控制台
            logger.info(f"[SMS][Mock] 发送验证码到 {phone}: code={code}, scene={scene}")
            print(f"\n{'='*50}")
            print(f"  [短信验证码]")
            print(f"  手机号: {phone}")
            print(f"  验证码: {code}")
            print(f"  场景:   {scene_label}")
            print(f"{'='*50}\n")
            return True

        # 真实发送
        try:
            from alibabacloud_dysmsapi20170525 import models as dysmsapi_models

            sign_name = settings.SMS_SIGN_NAME
            template_code = settings.SMS_TEMPLATE_CODE

            if not sign_name or not template_code:
                logger.error("[SMS] 短信签名或模板 CODE 未配置")
                return False

            request = dysmsapi_models.SendSmsRequest(
                phone_numbers=phone,
                sign_name=sign_name,
                template_code=template_code,
                template_param=json.dumps({"code": code, "min": "5"}),
            )

            response = client.send_sms(request)
            body = response.body

            if body.code == "OK":
                logger.info(f"[SMS] 验证码已发送: phone={phone}, scene={scene}")
                return True
            else:
                logger.error(f"[SMS] 发送失败: code={body.code}, message={body.message}")
                return False
        except Exception as e:
            logger.error(f"[SMS] 发送异常: {e}")
            return False


# 全局单例
sms_service = SMSService()
