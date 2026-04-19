import requests
import threading
from KisKey import telegram_bot_token
from KisKey import telegram_chat_id
from KisKey import telegram_enable
from KisKey import telegram_server_power_log


class Telegram:
    @staticmethod
    def send_message(text: str, sync: bool = False):
        """동기/비동기 상황에 맞춰 메시지를 전송할 수 있는 래퍼 함수입니다."""
        if sync:
            Telegram._send_message_sync(text)
        else:
            Telegram._send_message_async(text)

    @staticmethod
    def send_power_log_message(text: str, sync: bool = False):
        """서버 전원 관련 로그를 텔레그램으로 전송합니다."""
        if telegram_server_power_log:
            Telegram.send_message(text, sync=sync)

    @staticmethod
    def _send_message_sync(text: str):
        """동기 방식으로 텔레그램 메시지를 전송합니다."""
        if not telegram_bot_token or not telegram_chat_id:
            return
        if not telegram_enable:
            return
            
        try:
            url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": telegram_chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            requests.post(url, json=payload, timeout=5.0)
        except Exception:
            pass

    @staticmethod
    def _send_message_async(text: str):
        """비동기 방식으로 텔레그램 메시지를 전송합니다."""
        if not telegram_bot_token or not telegram_chat_id:
            return
        if not telegram_enable:
            return
        thread = threading.Thread(target=Telegram._send_message_sync, args=(text,), daemon=True)
        thread.start()
