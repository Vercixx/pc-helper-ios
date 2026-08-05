"""Wire format for the control socket: newline-delimited JSON.

Request   {"id": 1, "cmd": "pair.begin", "args": {...}}
Response  {"id": 1, "ok": true, "data": {...}}
          {"id": 1, "ok": false, "error": {"code": "...", "message": "..."}}
Event     {"event": "pair.request", "data": {...}}          (unsolicited)
"""

from __future__ import annotations

import json
from typing import Any

# One line must comfortably hold an audit dump; anything larger is a client bug
# or an attempt to exhaust memory.
MAX_LINE_BYTES = 1 << 20

CMD_STATUS = "status"
CMD_PAIR_BEGIN = "pair.begin"
CMD_PAIR_CANCEL = "pair.cancel"
CMD_PAIR_APPROVE = "pair.approve"
CMD_PAIR_DENY = "pair.deny"
CMD_DEVICES_LIST = "devices.list"
CMD_DEVICES_REVOKE = "devices.revoke"
CMD_DEVICES_DELETE = "devices.delete"
CMD_AUDIT_TAIL = "audit.tail"

COMMANDS = frozenset(
    {
        CMD_STATUS,
        CMD_PAIR_BEGIN,
        CMD_PAIR_CANCEL,
        CMD_PAIR_APPROVE,
        CMD_PAIR_DENY,
        CMD_DEVICES_LIST,
        CMD_DEVICES_REVOKE,
        CMD_DEVICES_DELETE,
        CMD_AUDIT_TAIL,
    }
)

EVENT_PAIR_OPENED = "pair.opened"
EVENT_PAIR_REQUEST = "pair.request"
EVENT_PAIR_CLOSED = "pair.closed"
EVENT_PAIR_COMPLETED = "pair.completed"


def encode(message: dict[str, Any]) -> bytes:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def decode(line: bytes) -> dict[str, Any]:
    data = json.loads(line.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("control message must be a JSON object")
    return data


def response(request_id: Any, data: Any) -> dict[str, Any]:
    return {"id": request_id, "ok": True, "data": data if data is not None else {}}


def error(request_id: Any, code: str, message: str) -> dict[str, Any]:
    return {"id": request_id, "ok": False, "error": {"code": code, "message": message}}


def event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
