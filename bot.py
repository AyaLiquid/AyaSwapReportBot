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


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
            # migrate old format that only had {"offset": N}
            if "sent" not in data:
                data["sent"] = {}
            return data
    return {"offset": 0, "sent": {}}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


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


def has_photo_and_text(message: dict) -> bool:
    """Return True only if the message has both a photo and a caption/text."""
    return bool(message.get("photo")) and bool(
        message.get("caption") or message.get("text")
    )


def send_photo_with_caption(file_id: str, caption: str) -> int | None:
    """Send photo+caption to target group. Returns the sent message_id or None."""
    try:
        resp = requests.post(
            f"{API}/sendPhoto",
            json={"chat_id": TARGET_CHAT_ID, "photo": file_id, "caption": caption},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]
    except requests.RequestException as e:
        log.error("sendPhoto failed: %s", e)
        return None


def edit_caption(target_msg_id: int, new_caption: str) -> None:
    """Edit the caption of an already-sent message in the target group."""
    try:
        resp = requests.post(
            f"{API}/editMessageCaption",
            json={
                "chat_id": TARGET_CHAT_ID,
                "message_id": target_msg_id,
                "caption": new_caption,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error("editMessageCaption failed: %s", e)


def check_and_forward() -> None:
    state = load_state()
    offset = state["offset"]
    # sent: str(source_message_id) -> target_message_id
    sent: dict[str, int] = state["sent"]
    forwarded = 0
    edited_count = 0

    while True:
        updates = get_updates(offset)
        if not updates:
            break

        # Collect new messages and edits from the source group separately
        new_messages: dict[str, dict] = {}
        edited_messages: dict[str, dict] = {}

        for update in updates:
            offset = update["update_id"] + 1

            msg = update.get("message")
            if msg and msg.get("chat", {}).get("id") == SOURCE_CHAT_ID:
                new_messages[str(msg["message_id"])] = msg

            edited = update.get("edited_message")
            if edited and edited.get("chat", {}).get("id") == SOURCE_CHAT_ID:
                edited_messages[str(edited["message_id"])] = edited

        # Process new messages; use the edited version if it arrived in the same cycle
        for msg_id, message in new_messages.items():
            if msg_id in edited_messages:
                # Edited before we even forwarded it — use the latest version
                message = edited_messages.pop(msg_id)

            if not has_photo_and_text(message):
                log.debug("Skipped message %s (needs both photo and text)", msg_id)
                continue

            file_id = message["photo"][-1]["file_id"]
            caption = message.get("caption") or message.get("text", "")
            target_id = send_photo_with_caption(file_id, caption)
            if target_id:
                sent[msg_id] = target_id
                forwarded += 1
                log.info("Forwarded %s → target %s", msg_id, target_id)

        # Process edits to messages that were forwarded in a previous cycle
        for msg_id, edited in edited_messages.items():
            if msg_id not in sent:
                log.debug("Edited message %s was never forwarded, skipping", msg_id)
                continue

            if not has_photo_and_text(edited):
                log.debug("Edited message %s no longer qualifies, skipping", msg_id)
                continue

            new_caption = edited.get("caption") or edited.get("text", "")
            edit_caption(sent[msg_id], new_caption)
            edited_count += 1
            log.info("Updated caption of target %s (source %s)", sent[msg_id], msg_id)

        state["offset"] = offset
        state["sent"] = sent
        save_state(state)

        # Fewer than 100 updates means we've caught up
        if len(updates) < 100:
            break

    log.info("Cycle done — forwarded %d, updated %d", forwarded, edited_count)


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
