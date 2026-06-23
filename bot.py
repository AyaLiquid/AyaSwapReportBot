import os
import json
import time
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
SOURCE_CHAT_ID = int(os.environ["SOURCE_CHAT_ID"])
TARGET_CHAT_ID = int(os.environ["TARGET_CHAT_ID"])

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
STATE_FILE = "last_id.json"
INTERVAL = 600  # seconds (10 minutes)


def load_offset() -> int:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f).get("offset", 0)
    return 0


def save_offset(offset: int) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump({"offset": offset}, f)


def get_updates(offset: int) -> list:
    try:
        resp = requests.get(
            f"{API}/getUpdates",
            params={"offset": offset, "limit": 100, "timeout": 0},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])
    except requests.RequestException as e:
        log.error("getUpdates failed: %s", e)
        return []


def send_text(text: str) -> None:
    try:
        resp = requests.post(
            f"{API}/sendMessage",
            json={"chat_id": TARGET_CHAT_ID, "text": text},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error("sendMessage failed: %s", e)


def send_photo(file_id: str, caption: str | None) -> None:
    payload = {"chat_id": TARGET_CHAT_ID, "photo": file_id}
    if caption:
        payload["caption"] = caption
    try:
        resp = requests.post(f"{API}/sendPhoto", json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error("sendPhoto failed: %s", e)


def forward_message(message: dict) -> None:
    photos = message.get("photo")
    text = message.get("text") or message.get("caption")

    if photos:
        # photos is a list sorted by size; last item is highest quality
        file_id = photos[-1]["file_id"]
        send_photo(file_id, caption=text)
        log.info("Forwarded photo (caption=%r)", text[:40] if text else None)
    elif text:
        send_text(text)
        log.info("Forwarded text (%d chars)", len(text))
    else:
        log.debug("Skipped message with no text or photo")


def check_and_forward() -> None:
    offset = load_offset()
    forwarded = 0

    while True:
        updates = get_updates(offset)
        if not updates:
            break

        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if message and message.get("chat", {}).get("id") == SOURCE_CHAT_ID:
                forward_message(message)
                forwarded += 1

        save_offset(offset)

        # If fewer than 100 updates returned, we've caught up
        if len(updates) < 100:
            break

    log.info("Cycle done — forwarded %d message(s)", forwarded)


def main() -> None:
    log.info(
        "Bot started. Source: %s → Target: %s. Interval: %ds",
        SOURCE_CHAT_ID,
        TARGET_CHAT_ID,
        INTERVAL,
    )
    while True:
        try:
            check_and_forward()
        except Exception as e:
            log.error("Unexpected error: %s", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
