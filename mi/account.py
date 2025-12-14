"""
账号认证模块
"""
import json
import os
from typing import Any, Dict, Optional

try:
    from .utils import CodecUtils, HashUtils, HttpClient
except ImportError:
    from utils import CodecUtils, HashUtils, HttpClient


class MiAccount:
    """小米账号类"""

    def __init__(
        self,
        sid: str,
        device_id: str,
        user_id: Optional[str] = None,
        password: Optional[str] = None,
        pass_token: Optional[str] = None,
        did: Optional[str] = None,
    ):
        self.sid = sid  # 'xiaomiio' or 'micoapi'
        self.device_id = device_id
        self.user_id = user_id
        self.password = password
        self.pass_token = pass_token
        self.did = did
        self.pass_data: Optional[Dict[str, Any]] = None
        self.service_token: Optional[str] = None
        self.device: Optional[Dict[str, Any]] = None


class AccountManager:
    """账号管理器"""

    def __init__(self, config_file: str = ".mi.json"):
        self.config_file = config_file
        self.http = HttpClient()
        self.login_api = "https://account.xiaomi.com/pass"

    def _get_login_cookies(self, account: MiAccount) -> Dict[str, str]:
        """获取登录 cookies"""
        cookies = {}
        if account.user_id:
            cookies["userId"] = account.user_id
        if account.device_id:
            cookies["deviceId"] = account.device_id
        if account.pass_token:
            cookies["passToken"] = account.pass_token
        return cookies

    def _get_service_token(self, pass_data: Dict[str, Any]) -> Optional[str]:
        """获取服务 token"""
        location = pass_data.get("location")
        nonce = pass_data.get("nonce")
        ssecurity = pass_data.get("ssecurity")

        if not location or not nonce or not ssecurity:
            return None

        client_sign = HashUtils.sha1(f"nonce={nonce}&{ssecurity}")
        response = self.http.get(
            location,
            params={"_userIdNeedEncrypt": "true", "clientSign": client_sign},
            raw_response=True,
        )

        if hasattr(response, "headers"):
            cookies = response.headers.get("Set-Cookie", "")
            if isinstance(cookies, str):
                for cookie in cookies.split(","):
                    if "serviceToken" in cookie:
                        return cookie.split(";")[0].split("=")[1]
            elif isinstance(cookies, list):
                for cookie in cookies:
                    if "serviceToken" in cookie:
                        return cookie.split(";")[0].split("=")[1]

        print("❌ 获取 Mi Service Token 失败")
        return None

    def get_account(
        self,
        account: MiAccount,
        relogin: bool = False,
    ) -> Optional[MiAccount]:
        """获取账号信息（登录）"""
        # 从文件读取已保存的账号信息
        if not relogin and os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    store = json.load(f)
                    service_key = account.sid
                    if service_key in store:
                        saved_account = store[service_key]
                        account.pass_token = saved_account.get("passToken")
                        account.service_token = saved_account.get("serviceToken")
                        account.pass_data = saved_account.get("pass")
                        account.device = saved_account.get("device")
            except:
                pass

        # 如果没有 passToken 且没有 userId/password，返回 None
        if not account.pass_token and (not account.user_id or not account.password):
            print("❌ 没有找到账号或密码，请检查是否已配置相关参数：userId, password")
            return None

        # 登录
        res = self.http.get(
            f"{self.login_api}/serviceLogin",
            params={"sid": account.sid, "_json": "true", "_locale": "zh_CN"},
            cookies=self._get_login_cookies(account),
        )

        if isinstance(res, dict) and res.get("isError"):
            print("❌ 登录失败", res)
            return None

        pass_data = CodecUtils.parse_auth_pass(res)

        # 如果登录态失效，重新登录
        if pass_data.get("code") != 0:
            data = {
                "_json": "true",
                "qs": pass_data.get("qs", ""),
                "sid": account.sid,
                "_sign": pass_data.get("_sign", ""),
                "callback": pass_data.get("callback", ""),
                "user": account.user_id,
                "hash": HashUtils.md5(account.password).upper(),
            }
            res = self.http.post(
                f"{self.login_api}/serviceLoginAuth2",
                data=CodecUtils.encode_query(data),
                cookies=self._get_login_cookies(account),
            )

            if isinstance(res, dict) and res.get("isError"):
                print("❌ OAuth2 登录失败", res)
                return None

            pass_data = CodecUtils.parse_auth_pass(res)

        # 检查是否需要验证码
        if pass_data.get("notificationUrl", "").find("identity/authStart") != -1:
            print("❌ 本次登录需要验证码，请使用 passToken 重新登录")
            print("💡 获取 passToken 教程：https://github.com/idootop/migpt-next/issues/4")
            return None

        if (
            not pass_data.get("location")
            or not pass_data.get("nonce")
            or not pass_data.get("passToken")
        ):
            print("❌ 登录失败，请检查你的账号密码是否正确")
            return None

        # 获取 service token
        service_token = self._get_service_token(pass_data)
        if not service_token:
            return None

        account.pass_data = pass_data
        account.service_token = service_token

        # 获取设备信息（延迟导入避免循环依赖）
        try:
            from .mina import MiNA
        except ImportError:
            from mina import MiNA
        account = MiNA.get_device(account)
        if account.did and not account.device:
            print(f"❌ 找不到设备：{account.did}")
            print(
                "🐛 请检查你的 did 与米家中的设备名称是否一致。注意错别字、空格和大小写，比如：音响 👉 音箱"
            )
            print(
                "💡 建议打开 debug 选项，查看目标设备的真实 name、miotDID 或 mac 地址，更新 did 参数"
            )
            return None

        # 保存账号信息
        self._save_account(account)

        return account

    def _save_account(self, account: MiAccount):
        """保存账号信息到文件"""
        try:
            store = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    store = json.load(f)

            service_key = account.sid
            store[service_key] = {
                "deviceId": account.device_id,
                "userId": account.user_id,
                "passToken": account.pass_token,
                "serviceToken": account.service_token,
                "pass": account.pass_data,
                "device": account.device,
            }

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存账号信息失败: {e}")

