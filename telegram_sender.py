import requests
import threading
from KisKey import telegram_bot_token, telegram_chat_id

def send_telegram_message_sync(text: str):
    """동기 방식으로 텔레그램 메시지를 전송합니다."""
    if not telegram_bot_token or not telegram_chat_id:
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

def send_telegram_message_async(text: str):
    """비동기 방식으로 텔레그램 메시지를 전송합니다."""
    if not telegram_bot_token or not telegram_chat_id:
        return

    thread = threading.Thread(target=send_telegram_message_sync, args=(text,), daemon=True)
    thread.start()

def send_telegram_message(text: str, sync: bool = False):
    """동기/비동기 상황에 맞춰 메시지를 전송할 수 있는 래퍼 함수입니다."""
    if sync:
        send_telegram_message_sync(text)
    else:
        send_telegram_message_async(text)
