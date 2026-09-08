"""Build the exact unsigned tclk/1 offer #2 packet without signing or posting it."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

DOMAIN = "FLOP::tclk::v1"
PREFIX = "tclk1 "
ROOM = "tclk-offers"
BUILDER_DID = "did:key:z6MkimcfTzAFj18jNxxYEWenqwr59AEPCWYhvG4qC5WdzrXY"
RELEASE = "v0.1.0"
RELEASE_COMMIT = "54e5caf03da76cd6c3d412ab840f543be018734b"
CONTEXT_URL = (
    "https://github.com/apomt/technocore-tasks/blob/"
    "63681bbe959b80f05d12a84f32c49a2e5ab26cc5/"
    "docs/tclk-pilot/phase1-worker-brief.md"
)
JOB_ID = "technocore-tasks-v0211-phase1"
EXPIRY_OFFSET_MS = 18 * 60 * 60 * 1000
CLAIM_OFFSET_MS = 42 * 60 * 60 * 1000
REFUND_OFFSET_MS = 48 * 60 * 60 * 1000

DID_RE = re.compile(r"^did:key:z6Mk[1-9A-HJ-NP-Za-km-z]{44}$")
NONCE_RE = re.compile(r"^[0-9a-f]{16,64}$")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def offer_id(fields: dict[str, object]) -> str:
    payload = f"{DOMAIN}|offer|{canonical_json(fields)}".encode("ascii")
    return "0x" + hashlib.sha256(payload).hexdigest()


def build_packet(*, frame_nonce: str, now_ms: int, transport_nonce: int) -> dict[str, object]:
    if not DID_RE.fullmatch(BUILDER_DID):
        raise AssertionError("public builder DID does not match released tclk/1 shape")
    if not NONCE_RE.fullmatch(frame_nonce):
        raise ValueError("frame nonce must be 16..64 lowercase hexadecimal characters")
    if not isinstance(now_ms, int) or now_ms <= 0:
        raise ValueError("now-ms must be a positive integer")
    if not isinstance(transport_nonce, int) or transport_nonce <= 0:
        raise ValueError("transport nonce must be a positive integer")

    fields: dict[str, object] = {
        "amount": "200",
        "asset": "FLOP",
        "claimByMs": now_ms + CLAIM_OFFSET_MS,
        "expiresMs": now_ms + EXPIRY_OFFSET_MS,
        "from": BUILDER_DID,
        "job": {"context": CONTEXT_URL, "id": JOB_ID, "proto": "a2a"},
        "lock": "hash",
        "nonce": frame_nonce,
        "rails": ["paper"],
        "refundAfterMs": now_ms + REFUND_OFFSET_MS,
        "role": "payer",
        "type": "offer",
    }
    if not now_ms < fields["expiresMs"] < fields["claimByMs"] < fields["refundAfterMs"]:
        raise AssertionError("deadline ordering failed")
    identifier = offer_id(fields)
    offer = {**fields, "id": identifier}
    canonical_offer = canonical_json(offer)
    frame = PREFIX + canonical_offer
    if not frame.isascii() or len(frame.encode("ascii")) > 4096 or "\n" in frame or "\r" in frame:
        raise AssertionError("released tclk/1 frame constraints failed")
    signing_payload = f"{ROOM}|{transport_nonce}|{frame}"
    return {
        "packet_version": 2,
        "status": "UNSIGNED_DO_NOT_POST",
        "released_tclk": {"version": RELEASE, "commit": RELEASE_COMMIT, "protocol": "tclk/1"},
        "target_room": ROOM,
        "offer": offer,
        "offer_id": identifier,
        "canonical_offer_json": canonical_offer,
        "frame": frame,
        "frame_utf8_hex": frame.encode("utf-8").hex(),
        "transport_nonce": transport_nonce,
        "transport_signing_payload": signing_payload,
        "transport_signing_payload_utf8_hex": signing_payload.encode("utf-8").hex(),
        "deadline_offsets_ms": {
            "offer_expiry": EXPIRY_OFFSET_MS,
            "claim": CLAIM_OFFSET_MS,
            "refund": REFUND_OFFSET_MS,
        },
        "accounting_notice": (
            "FLOP 200 is a symbolic PaperRail rehearsal amount, not real FLOP payment; "
            "no token transfer or monetary payment is promised and no airdrop entitlement is implied."
        ),
        "required_sequence": [
            "Keep the read-only tracker armed until its cursor is current and continuously healthy.",
            "Bind this exact unsigned packet to the tracker without changing its cursor.",
            "Only after human review may an isolated signer sign and a human POST it.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame-nonce", required=True)
    parser.add_argument("--now-ms", required=True, type=int)
    parser.add_argument("--transport-nonce", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")
    packet = build_packet(
        frame_nonce=args.frame_nonce,
        now_ms=args.now_ms,
        transport_nonce=args.transport_nonce,
    )
    args.output.write_text(json.dumps(packet, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"wrote unsigned packet: {args.output}")
    print(f"offer id: {packet['offer_id']}")
    print("no signature was created and nothing was posted")


if __name__ == "__main__":
    main()
