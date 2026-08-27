from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote, unquote

PREFIX = "TC-TASK/1"
TASK_ID_RE = re.compile(r"^task-[0-9a-f]{8}$")
DID_RE = re.compile(r"^did:key:z6Mk[1-9A-HJ-NP-Za-km-z]{44}$")
BAD_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")

FIELD_RULES = {
    "CREATE": ({"task", "title"}, {"description", "reward", "budget", "payment"}),
    "CLAIM": ({"task"}, {"note"}),
    "ASSIGN": ({"task", "assignee"}, set()),
    "COMPLETE": ({"task"}, {"result"}),
    "CLOSE": ({"task"}, set()),
    "CANCEL": ({"task"}, {"reason"}),
}


class EventParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedEvent:
    kind: str
    task_id: str
    fields: dict[str, str]


def canonical_title(title: str) -> str:
    """NFC, trim, then collapse every Unicode whitespace run to one ASCII space."""
    return " ".join(unicodedata.normalize("NFC", title).split())


def canonical_task_id(creator_did: str, create_nonce: int, title: str) -> str:
    canonical = canonical_title(title)
    material = f"{creator_did}\n{int(create_nonce)}\n{canonical}".encode("utf-8")
    return "task-" + hashlib.sha256(material).hexdigest()[:8]


def _encode(value: str) -> str:
    return quote(str(value), safe="-._~:/")


def _decode(value: str) -> str:
    if BAD_ESCAPE_RE.search(value):
        raise EventParseError("invalid percent escape")
    try:
        return unquote(value, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EventParseError("invalid UTF-8 escape") from exc


def build_event(kind: str, fields: dict[str, str]) -> str:
    kind = kind.upper()
    if kind not in FIELD_RULES:
        raise EventParseError("unknown event kind")
    required, optional = FIELD_RULES[kind]
    keys = set(fields)
    if not required <= keys or not keys <= required | optional:
        raise EventParseError(f"invalid fields for {kind}")
    if not TASK_ID_RE.fullmatch(fields["task"]):
        raise EventParseError("invalid task id")
    if kind == "CREATE" and not canonical_title(fields["title"]):
        raise EventParseError("title must not be empty")
    if kind == "ASSIGN" and not DID_RE.fullmatch(fields["assignee"]):
        raise EventParseError("invalid assignee DID")
    order = ["task", "title", "description", "reward", "budget", "payment", "note", "assignee", "result", "reason"]
    rendered = " ".join(f"{key}={_encode(fields[key])}" for key in order if key in fields)
    return f"{PREFIX} {kind} {rendered}"


def parse_event(text: str) -> ParsedEvent:
    if any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in text):
        raise EventParseError("event contains control characters")
    parts = text.split(" ")
    if len(parts) < 3 or parts[0] != PREFIX or not parts[1]:
        raise EventParseError("not a TC-TASK/1 event")
    kind = parts[1].upper()
    if kind not in FIELD_RULES:
        raise EventParseError("unknown event kind")
    fields: dict[str, str] = {}
    for token in parts[2:]:
        if not token or "=" not in token:
            raise EventParseError("malformed field")
        key, raw = token.split("=", 1)
        if not re.fullmatch(r"[a-z]+", key) or key in fields:
            raise EventParseError("invalid or duplicate field")
        fields[key] = _decode(raw)
    required, optional = FIELD_RULES[kind]
    keys = set(fields)
    if not required <= keys or not keys <= required | optional:
        raise EventParseError(f"invalid fields for {kind}")
    task_id = fields["task"]
    if not TASK_ID_RE.fullmatch(task_id):
        raise EventParseError("invalid task id")
    if kind == "CREATE" and not canonical_title(fields["title"]):
        raise EventParseError("title must not be empty")
    if kind == "ASSIGN" and not DID_RE.fullmatch(fields["assignee"]):
        raise EventParseError("invalid assignee DID")
    return ParsedEvent(kind=kind, task_id=task_id, fields=fields)

