"""Build an unsigned tclk/1 open-offer packet without accessing any signing key."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

DOMAIN = "FLOP::tclk::v1"
PREFIX = "tclk1 "
OFFER_ROOM = "tclk-offers"
BUILDER_DID = "did:key:z6MkimcfTzAFj18jNxxYEWenqwr59AEPCWYhvG4qC5WdzrXY"
JOB_ID = "technocore-tasks-v0211-validation"
DID_RE = re.compile(r"^did:key:z6Mk[1-9A-HJ-NP-Za-km-z]{44}$")
NONCE_RE = re.compile(r"^[0-9a-f]{8,64}$")


def canonical_json(value: object) -> str:
    """Released v0.1.0 canonical JSON for this ASCII-only offer shape."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def offer_id(fields: dict[str, object]) -> str:
    payload = f"{DOMAIN}|offer|{canonical_json(fields)}".encode("ascii")
    return "0x" + hashlib.sha256(payload).hexdigest()


def build_packet(
    *, from_did: str, context_url: str, frame_nonce: str, now_ms: int, transport_nonce: int
) -> dict[str, object]:
    if not DID_RE.fullmatch(from_did):
        raise ValueError("from DID does not match the released tclk/1 Ed25519 did:key shape")
    if not NONCE_RE.fullmatch(frame_nonce):
        raise ValueError("frame nonce must be 8..64 lowercase hexadecimal characters")
    if not context_url.startswith("https://github.com/apomt/technocore-tasks/blob/"):
        raise ValueError("context URL must be an immutable technocore-tasks GitHub blob URL")
    if not isinstance(now_ms, int) or now_ms <= 0:
        raise ValueError("now-ms must be a positive integer")
    if not isinstance(transport_nonce, int) or transport_nonce <= 0:
        raise ValueError("transport nonce must be a positive integer")

    expires_ms = now_ms + 24 * 60 * 60 * 1000
    claim_by_ms = now_ms + 7 * 24 * 60 * 60 * 1000
    refund_after_ms = now_ms + 8 * 24 * 60 * 60 * 1000
    fields: dict[str, object] = {
        "amount": "1",
        "asset": "PAPER",
        "claimByMs": claim_by_ms,
        "expiresMs": expires_ms,
        "from": from_did,
        "job": {"context": context_url, "id": JOB_ID, "proto": "a2a"},
        "lock": "hash",
        "nonce": frame_nonce,
        "rails": ["paper"],
        "refundAfterMs": refund_after_ms,
        "role": "payer",
        "type": "offer",
    }
    if not now_ms < expires_ms < claim_by_ms < refund_after_ms:
        raise AssertionError("deadline ordering failed")
    identifier = offer_id(fields)
    offer = {**fields, "id": identifier}
    offer_json = canonical_json(offer)
    frame = PREFIX + offer_json
    if len(frame) > 4096 or not frame.isascii() or "\n" in frame or "\r" in frame:
        raise AssertionError("released Technocore frame constraints failed")
    signing_payload = f"{OFFER_ROOM}|{transport_nonce}|{frame}"
    return {
        "packet_version": 1,
        "status": "UNSIGNED_DO_NOT_POST",
        "released_tclk": {
            "version": "v0.1.0",
            "commit": "54e5caf03da76cd6c3d412ab840f543be018734b",
            "protocol": "tclk/1",
        },
        "target_room": OFFER_ROOM,
        "offer": offer,
        "offer_id": identifier,
        "canonical_offer_json": offer_json,
        "frame": frame,
        "frame_utf8_hex": frame.encode("utf-8").hex(),
        "transport_nonce": transport_nonce,
        "transport_signing_payload": signing_payload,
        "transport_signing_payload_utf8_hex": signing_payload.encode("utf-8").hex(),
        "deadline_offsets_ms": {
            "offer_expiry": 24 * 60 * 60 * 1000,
            "claim": 7 * 24 * 60 * 60 * 1000,
            "refund": 8 * 24 * 60 * 60 * 1000,
        },
        "expected_public_effect": (
            "One signed open offer becomes publicly visible in tclk-offers; no deal exists "
            "until a different external DID posts a valid accept before expiresMs."
        ),
        "human_checks": [
            "Confirm context_url and its immutable commit.",
            "Confirm transport_nonce exceeds this DID's last nonce in tclk-offers.",
            "Confirm frame_nonce is fresh and random.",
            "Confirm exact UTF-8 signing payload outside Codex before signing.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-url", required=True)
    parser.add_argument("--frame-nonce", required=True)
    parser.add_argument("--now-ms", type=int, default=None)
    parser.add_argument("--transport-nonce", type=int, default=None)
    parser.add_argument("--from-did", default=BUILDER_DID)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    now_ms = args.now_ms if args.now_ms is not None else time.time_ns() // 1_000_000
    transport_nonce = args.transport_nonce if args.transport_nonce is not None else now_ms
    packet = build_packet(
        from_did=args.from_did,
        context_url=args.context_url,
        frame_nonce=args.frame_nonce,
        now_ms=now_ms,
        transport_nonce=transport_nonce,
    )
    rendered = json.dumps(packet, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        if args.output.exists():
            raise SystemExit(f"refusing to overwrite {args.output}")
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
