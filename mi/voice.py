"""
语音接收器模块
"""
import threading
import time
from typing import Callable, Dict, List, Optional

try:
    from .mina import MiNA
except ImportError:
    from mina import MiNA


class VoiceMessage:
    """语音消息类"""

    def __init__(self, text: str, timestamp: int, request_id: str):
        self.text = text  # 语音内容文本
        self.timestamp = timestamp  # 消息时间戳（毫秒）
        self.request_id = request_id  # 请求ID

    def __repr__(self):
        return f"VoiceMessage(text='{self.text}', timestamp={self.timestamp}, request_id='{self.request_id}')"


class VoiceReceiver:
    """语音接收器，用于监听小米音箱的语音对话"""

    def __init__(self, mina: MiNA):
        """
        初始化语音接收器

        Args:
            mina: MiNA 实例
        """
        self.mina = mina
        self.last_timestamp = 0
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

    def start(
        self,
        callback: Callable[[VoiceMessage], None],
        interval: int = 1000,
        only_new: bool = True,
    ):
        """
        开始监听语音消息

        Args:
            callback: 收到新消息时的回调函数
            interval: 轮询间隔（毫秒），默认 1000
            only_new: 是否只获取新消息，默认 True
        """
        if self.is_running:
            print("⚠️ 语音接收器已在运行中")
            return

        self.is_running = True
        self.stop_event.clear()

        # 初始化时获取最新消息的时间戳
        self._init_last_timestamp()

        # 启动轮询线程
        def poll_loop():
            while not self.stop_event.is_set():
                self._fetch_messages(callback, only_new)
                # 等待指定时间（转换为秒）
                self.stop_event.wait(interval / 1000.0)

        self.thread = threading.Thread(target=poll_loop, daemon=True)
        self.thread.start()
        print("✅ 开始监听语音消息...")

    def stop(self):
        """停止监听"""
        if not self.is_running:
            return

        self.is_running = False
        self.stop_event.set()

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

        print("⏹️ 已停止监听")

    def get_history_messages(
        self, limit: int = 10, timestamp: Optional[int] = None
    ) -> List[VoiceMessage]:
        """
        获取历史消息（不启动轮询）

        Args:
            limit: 获取数量，默认 10
            timestamp: 时间戳（毫秒），获取此时间之前的消息

        Returns:
            语音消息列表
        """
        conversations = self.mina.get_conversations(
            limit=limit,
            timestamp=int(timestamp / 1000) if timestamp else None,
        )

        if not conversations or "records" not in conversations:
            return []

        messages = []
        for record in conversations["records"]:
            messages.append(
                VoiceMessage(
                    text=record.get("query", ""),
                    timestamp=record.get("time", 0),
                    request_id=record.get("requestId", ""),
                )
            )

        return messages

    def _init_last_timestamp(self):
        """初始化最后一条消息的时间戳"""
        try:
            conversations = self.mina.get_conversations(limit=1)
            if conversations and "records" in conversations and len(conversations["records"]) > 0:
                self.last_timestamp = conversations["records"][0].get("time", 0)
        except Exception as e:
            print(f"⚠️ 初始化时间戳失败: {e}")

    def _fetch_messages(
        self, callback: Callable[[VoiceMessage], None], only_new: bool
    ):
        """获取消息并触发回调"""
        try:
            conversations = self.mina.get_conversations(limit=10)

            if not conversations:
                print(f"⚠️ 获取对话列表为空")
                return
            
            if "records" not in conversations:
                print(f"⚠️ 对话列表中没有 records 字段")
                return

            # 从新到旧排序
            records = conversations["records"]

            new_messages_count = 0
            for record in records:
                record_time = record.get("time", 0)
                query_text = record.get("query", "")

                # 如果只获取新消息，跳过已处理的消息
                if only_new and record_time <= self.last_timestamp:
                    continue

                new_messages_count += 1
                # 更新最后处理的时间戳
                if record_time > self.last_timestamp:
                    self.last_timestamp = record_time

                # 触发回调
                message = VoiceMessage(
                    text=query_text,
                    timestamp=record_time,
                    request_id=record.get("requestId", ""),
                )

                try:
                    callback(message)
                except Exception as e:
                    print(f"❌ 回调函数执行失败: {e}")
                    import traceback
                    traceback.print_exc()

        except Exception as e:
            print(f"❌ 获取语音消息失败: {e}")
            import traceback
            traceback.print_exc()

