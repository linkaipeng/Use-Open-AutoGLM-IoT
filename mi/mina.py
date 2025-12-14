"""
MiNA (小米小爱) 模块
"""
import json
import time
from typing import Any, Dict, List, Optional

try:
    from .account import MiAccount
    from .utils import CodecUtils, HashUtils, HttpClient
except ImportError:
    from account import MiAccount
    from utils import CodecUtils, HashUtils, HttpClient


class MiNA:
    """MiNA 类，用于与小爱音箱交互"""

    def __init__(self, account: MiAccount):
        self.account = account
        self.http = HttpClient()
        self.base_url = "https://api2.mina.mi.com"

    @staticmethod
    def get_device(account: MiAccount) -> MiAccount:
        """获取设备信息"""
        if account.sid != "micoapi":
            return account

        mina = MiNA(account)
        devices = mina._call_mina("GET", "/admin/v2/device_list")

        if devices:
            device = None
            for d in devices:
                if (
                    account.did
                    in [
                        d.get("deviceID"),
                        d.get("miotDID"),
                        d.get("name"),
                        d.get("alias"),
                        d.get("mac"),
                    ]
                ):
                    device = d
                    break

            if device:
                account.device = {
                    **device,
                    "deviceId": device.get("deviceID"),
                }

        return account

    def _call_mina(
        self, method: str, path: str, data: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        """调用 MiNA API"""
        if data is None:
            data = {}

        data["requestId"] = HashUtils.uuid()
        data["timestamp"] = int(time.time())

        url = f"{self.base_url}{path}"

        cookies = {}
        if self.account.user_id:
            cookies["userId"] = self.account.user_id
        if self.account.service_token:
            cookies["serviceToken"] = self.account.service_token
        if self.account.device:
            if self.account.device.get("serialNumber"):
                cookies["sn"] = self.account.device.get("serialNumber")
            if self.account.device.get("hardware"):
                cookies["hardware"] = self.account.device.get("hardware")
            if self.account.device.get("deviceId"):
                cookies["deviceId"] = self.account.device.get("deviceId")
            if self.account.device.get("deviceSNProfile"):
                cookies["deviceSNProfile"] = self.account.device.get("deviceSNProfile")

        headers = {
            "User-Agent": "MICO/AndroidApp/@SHIP.TO.2A2FE0D7@/2.4.40",
        }

        try:
            if method == "GET":
                response = self.http.get(url, params=data, cookies=cookies, headers=headers)
            else:
                response = self.http.post(
                    url, data=CodecUtils.encode_query(data), cookies=cookies, headers=headers
                )

            if isinstance(response, dict):
                if response.get("code") == 0:
                    return response.get("data")
                else:
                    print(f"❌ _call_mina failed: {response}")
                    return None
            else:
                # 尝试解析 JSON
                try:
                    result = json.loads(response)
                    if result.get("code") == 0:
                        return result.get("data")
                    else:
                        print(f"❌ _call_mina failed: {result}")
                        return None
                except:
                    return None
        except Exception as e:
            print(f"❌ _call_mina error: {e}")
            return None

    def call_ubus(self, scope: str, command: str, message: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """调用小爱音箱上的 ubus 服务"""
        if message is None:
            message = {}
        message_str = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        return self._call_mina(
            "POST",
            "/remote/ubus",
            {
                "deviceId": self.account.device.get("deviceId") if self.account.device else "",
                "path": scope,
                "method": command,
                "message": message_str,
            },
        )

    def get_devices(self) -> Optional[List[Dict[str, Any]]]:
        """获取设备列表"""
        return self._call_mina("GET", "/admin/v2/device_list")

    def get_conversations(
        self, limit: int = 10, timestamp: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """获取对话消息列表"""
        url = "https://userprofile.mina.mi.com/device_profile/v2/conversation"

        params = {
            "limit": limit,
            "requestId": HashUtils.uuid(),
            "source": "dialogu",
        }
        if self.account.device and self.account.device.get("hardware"):
            params["hardware"] = self.account.device.get("hardware")

        if timestamp:
            params["timestamp"] = timestamp

        cookies = {}
        if self.account.user_id:
            cookies["userId"] = self.account.user_id
        if self.account.service_token:
            cookies["serviceToken"] = self.account.service_token
        if self.account.device and self.account.device.get("deviceId"):
            cookies["deviceId"] = self.account.device.get("deviceId")

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; 000; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/119.0.6045.193 Mobile Safari/537.36 /XiaoMi/HybridView/ micoSoundboxApp/i appVersion/A_2.4.40",
            "Referer": "https://userprofile.mina.mi.com/dialogue-note/index.html",
        }

        try:
            response = self.http.get(url, params=params, cookies=cookies, headers=headers)

            if isinstance(response, dict):
                if response.get("code") == 0:
                    data_str = response.get("data")
                    if isinstance(data_str, str):
                        return json.loads(data_str)
                    return data_str
                else:
                    print(f"❌ get_conversations failed: {response}")
                    return None
            else:
                try:
                    result = json.loads(response)
                    if result.get("code") == 0:
                        data_str = result.get("data")
                        if isinstance(data_str, str):
                            return json.loads(data_str)
                        return data_str
                    else:
                        print(f"❌ get_conversations failed: {result}")
                        return None
                except Exception as e:
                    print(f"❌ get_conversations parse error: {e}")
                    return None
        except Exception as e:
            print(f"❌ get_conversations error: {e}")
            return None

