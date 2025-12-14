"""
工具函数模块
"""
import base64
import hashlib
import hmac
import json
import random
import urllib.parse
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class HashUtils:
    """哈希工具类"""

    @staticmethod
    def md5(s: str) -> str:
        """计算 MD5 哈希值"""
        return hashlib.md5(s.encode()).hexdigest()

    @staticmethod
    def sha1(s: str) -> str:
        """计算 SHA1 哈希值（base64）"""
        return base64.b64encode(hashlib.sha1(s.encode()).digest()).decode()

    @staticmethod
    def sha256(snonce: bytes, msg: str) -> str:
        """计算 HMAC-SHA256"""
        return base64.b64encode(
            hmac.new(snonce, msg.encode(), hashlib.sha256).digest()
        ).decode()

    @staticmethod
    def sign_nonce(ssecurity: str, nonce: str) -> str:
        """签名 nonce"""
        m = hashlib.sha256()
        m.update(base64.b64decode(ssecurity))
        m.update(base64.b64decode(nonce))
        return base64.b64encode(m.digest()).decode()

    @staticmethod
    def uuid() -> str:
        """生成 UUID"""
        import uuid as uuid_lib
        return str(uuid_lib.uuid4())

    @staticmethod
    def random_noise() -> str:
        """生成随机噪声（12字节，base64编码）"""
        noise = bytes([random.randint(0, 255) for _ in range(12)])
        return base64.b64encode(noise).decode()


class RC4:
    """RC4 加密/解密类"""

    def __init__(self, key: bytes):
        self.iii = 0
        self.jjj = 0
        self.bytes = bytearray(256)
        length = len(key)

        # 初始化 S 盒
        for i in range(256):
            self.bytes[i] = i

        j = 0
        for i in range(256):
            j = (j + self.bytes[i] + key[i % length]) & 255
            self.bytes[i], self.bytes[j] = self.bytes[j], self.bytes[i]

    def update(self, data: bytearray) -> bytearray:
        """更新数据流"""
        result = bytearray(data)
        for i in range(len(result)):
            self.iii = (self.iii + 1) & 255
            self.jjj = (self.jjj + self.bytes[self.iii]) & 255
            self.bytes[self.iii], self.bytes[self.jjj] = (
                self.bytes[self.jjj],
                self.bytes[self.iii],
            )
            result[i] ^= self.bytes[
                (self.bytes[self.iii] + self.bytes[self.jjj]) & 255
            ]
        return result


class CodecUtils:
    """编解码工具类"""

    @staticmethod
    def encode_base64(text: str) -> str:
        """Base64 编码"""
        return base64.b64encode(text.encode()).decode()

    @staticmethod
    def decode_base64(base64_str: str) -> str:
        """Base64 解码"""
        return base64.b64decode(base64_str).decode()

    @staticmethod
    def parse_auth_pass(res: str) -> Dict[str, Any]:
        """解析认证响应"""
        try:
            # 去除前缀
            res = res.replace("&&&START&&&", "")
            # 将大数字转为字符串
            import re
            res = re.sub(r":(\d{9,})", r':"\1"', res)
            return json.loads(res)
        except:
            return {}

    @staticmethod
    def encode_query(data: Dict[str, Any]) -> str:
        """编码查询字符串"""
        parts = []
        for key, value in data.items():
            if value is not None:
                parts.append(
                    f"{urllib.parse.quote(str(key))}={urllib.parse.quote(str(value))}"
                )
        return "&".join(parts)

    @staticmethod
    def decode_query(query_str: str) -> Dict[str, Any]:
        """解码查询字符串"""
        result = {}
        if not query_str:
            return result
        for pair in query_str.split("&"):
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            key = urllib.parse.unquote(key)
            value = urllib.parse.unquote(value)
            if value.startswith("[{"):
                try:
                    value = json.loads(value)
                except:
                    pass
            result[key] = value
        return result

    @staticmethod
    def rc4_hash(method: str, uri: str, data: Dict[str, str], ssecurity: str) -> str:
        """计算 RC4 哈希"""
        array_list = []
        if method:
            array_list.append(method.upper())
        if uri:
            array_list.append(uri)
        if data:
            for k, v in data.items():
                array_list.append(f"{k}={v}")
        array_list.append(ssecurity)
        sb = "&".join(array_list)
        return HashUtils.sha1(sb)

    @staticmethod
    def encode_miot(
        method: str, uri: str, data: Any, ssecurity: str
    ) -> Dict[str, str]:
        """编码 MIoT 请求"""
        nonce = HashUtils.random_noise()
        snonce = HashUtils.sign_nonce(ssecurity, nonce)
        key = base64.b64decode(snonce)
        rc4 = RC4(key)
        # 更新 1024 字节
        rc4.update(bytearray(1024))

        json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        map_data: Dict[str, str] = {"data": json_str}
        map_data["rc4_hash__"] = CodecUtils.rc4_hash(method, uri, map_data, snonce)

        # RC4 加密
        for k in map_data:
            v = map_data[k]
            encrypted = rc4.update(bytearray(v.encode()))
            map_data[k] = base64.b64encode(encrypted).decode()

        map_data["signature"] = CodecUtils.rc4_hash(method, uri, map_data, snonce)
        map_data["_nonce"] = nonce
        map_data["ssecurity"] = ssecurity
        return map_data

    @staticmethod
    def decode_miot(
        ssecurity: str, nonce: str, data: str, gzip: bool = False
    ) -> Optional[Dict[str, Any]]:
        """解码 MIoT 响应"""
        try:
            key = base64.b64decode(HashUtils.sign_nonce(ssecurity, nonce))
            rc4 = RC4(key)
            # 更新 1024 字节
            rc4.update(bytearray(1024))

            decrypted = rc4.update(bytearray(base64.b64decode(data)))

            if gzip:
                import gzip
                decrypted = gzip.decompress(bytes(decrypted))
                decrypted_str = decrypted.decode()
            else:
                decrypted_str = decrypted.decode()

            return json.loads(decrypted_str)
        except Exception as e:
            print(f"❌ decode_miot failed: {e}")
            return None


class HttpClient:
    """HTTP 客户端"""

    def __init__(self, timeout: int = 5000):
        self.timeout = timeout / 1000  # 转换为秒
        self.session = requests.Session()
        # 设置重试策略
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _build_cookies(self, cookies: Dict[str, Any]) -> Dict[str, str]:
        """构建 cookies"""
        result = {}
        for key, value in cookies.items():
            if value is not None:
                result[key] = str(value)
        return result

    def _build_headers(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """构建请求头"""
        default_headers = {
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 10; RMX2111 Build/QP1A.190711.020) APP/xiaomi.mico APPV/2004040 MK/Uk1YMjExMQ== PassportSDK/3.8.3 passport-ui/3.8.3",
        }
        if headers:
            default_headers.update(headers)
        return default_headers

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        raw_response: bool = False,
    ) -> Any:
        """GET 请求"""
        try:
            response = self.session.get(
                url,
                params=params,
                cookies=self._build_cookies(cookies) if cookies else None,
                headers=self._build_headers(headers),
                timeout=self.timeout,
            )
            if raw_response:
                return response
            return response.text
        except Exception as e:
            return {"isError": True, "error": str(e), "code": "未知", "message": str(e)}

    def post(
        self,
        url: str,
        data: Optional[Any] = None,
        cookies: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        raw_response: bool = False,
    ) -> Any:
        """POST 请求"""
        try:
            response = self.session.post(
                url,
                data=data,
                cookies=self._build_cookies(cookies) if cookies else None,
                headers=self._build_headers(headers),
                timeout=self.timeout,
            )
            if raw_response:
                return response
            return response.text
        except Exception as e:
            return {"isError": True, "error": str(e), "code": "未知", "message": str(e)}

