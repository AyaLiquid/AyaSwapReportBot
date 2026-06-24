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
EDIT_POLL_INTERVAL = 10   # seconds between edit checks
FORWARD_INTERVAL = 60     # seconds between forwarding new messages (1 min)


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
            data.setdefault("sent", {})
            data.setdefault("pending", {})
            return data
    return {"offset": 0, "sent": {}, "pending": {}}


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


def _dbg(msg: str, data: dict, hyp: str) -> None:
    import json as _json
    entry = _json.dumps({"sessionId": "cd5fb4", "timestamp": int(time.time() * 1000),
                         "message": msg, "data": data, "hypothesisId": hyp})
    with open("debug-cd5fb4.log", "a", encoding="utf-8") as _f:
        _f.write(entry + "\n")


def edit_caption(target_msg_id: int, new_caption: str) -> None:
    """Edit the caption of an already-sent message in the target group."""
    # #region agent log
    _dbg("edit_caption called", {"target_msg_id": target_msg_id, "caption_len": len(new_caption)}, "A_D")
    # #endregion
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
        # #region agent log
        try:
            resp_body = resp.json()
        except Exception:
            resp_body = {}
        _dbg("edit_caption response", {"http_status": resp.status_code, "ok": resp_body.get("ok"), "description": resp_body.get("description", "")}, "A_D")
        # #endregion
        resp.raise_for_status()
    except requests.RequestException as e:
        # #region agent log
        _dbg("edit_caption exception", {"error": str(e)}, "A_D")
        # #endregion
        log.error("editMessageCaption failed: %s", e)


def drain_updates(state: dict) -> tuple[int, int]:
    """
    Fetch all pending updates from Telegram.
    - New messages are added to state["pending"] (forwarded later on schedule).
    - Edited messages are applied immediately: edit the target if already forwarded,
      or update the pending buffer if the message hasn't been sent yet.
    Returns (edited_count, updates_processed).
    """
    sent: dict[str, int] = state["sent"]
    pending: dict[str, dict] = state["pending"]
    offset: int = state["offset"]
    edited_count = 0
    total = 0

    while True:
        updates = get_updates(offset)
        if not updates:
            break

        for update in updates:
            offset = update["update_id"] + 1
            total += 1

            msg = update.get("message")
            if msg and msg.get("chat", {}).get("id") == SOURCE_CHAT_ID:
                pending[str(msg["message_id"])] = msg

            edited = update.get("edited_message")
            if edited and edited.get("chat", {}).get("id") == SOURCE_CHAT_ID:
                msg_id = str(edited["message_id"])
                # #region agent log
                _dbg("edited_message received", {
                    "msg_id": msg_id,
                    "in_sent": msg_id in sent,
                    "in_pending": msg_id in pending,
                    "has_photo": bool(edited.get("photo")),
                    "has_caption": bool(edited.get("caption") or edited.get("text")),
                    "qualifies": has_photo_and_text(edited),
                    "sent_keys": list(sent.keys())[-5:],
                }, "B_C")
                # #endregion

                if msg_id in sent:
                    # Already forwarded — edit the target message right away
                    if has_photo_and_text(edited):
                        caption = edited.get("caption") or edited.get("text", "")
                        edit_caption(sent[msg_id], caption)
                        edited_count += 1
                        log.info(
                            "Immediately updated target %s (source %s)",
                            sent[msg_id], msg_id,
                        )
                    else:
                        log.debug("Edit on %s no longer qualifies, skipping", msg_id)
                elif msg_id in pending:
                    # Still in the buffer — replace with the edited version
                    pending[msg_id] = edited
                    log.debug("Updated buffered message %s with its edit", msg_id)

        state["offset"] = offset

        if len(updates) < 100:
            break

    return edited_count, total


def forward_pending(state: dict) -> int:
    """Forward all buffered new messages that qualify (photo + text)."""
    sent: dict[str, int] = state["sent"]
    pending: dict[str, dict] = state["pending"]
    forwarded = 0

    for msg_id in list(pending):
        message = pending.pop(msg_id)
        if not has_photo_and_text(message):
            log.debug("Skipped %s (needs both photo and text)", msg_id)
            continue

        file_id = message["photo"][-1]["file_id"]
        caption = message.get("caption") or message.get("text", "")
        target_id = send_photo_with_caption(file_id, caption)
        if target_id:
            sent[msg_id] = target_id
            forwarded += 1
            log.info("Forwarded %s → target %s", msg_id, target_id)

    return forwarded


def main() -> None:
    state = load_state()
    last_forward_at = 0.0

    log.info(
        "Bot started. Source: %s → Target: %s. "
        "New messages every %ds, edit checks every %ds.",
        SOURCE_CHAT_ID, TARGET_CHAT_ID, FORWARD_INTERVAL, EDIT_POLL_INTERVAL,
    )

    while True:
        try:
            edited_count, _ = drain_updates(state)
            if edited_count:
                log.info("Applied %d edit(s) immediately", edited_count)

            now = time.time()
            if now - last_forward_at >= FORWARD_INTERVAL:
                forwarded = forward_pending(state)
                last_forward_at = now
                log.info("Forward cycle done — sent %d new message(s)", forwarded)

            save_state(state)

        except Exception as e:
            log.error("Unexpected error: %s", e)

        time.sleep(EDIT_POLL_INTERVAL)


if __name__ == "__main__":
    main()
