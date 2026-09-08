from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "docs" / "tclk-pilot" / "build_offer2.py"
SPEC = importlib.util.spec_from_file_location("build_offer2", BUILDER_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_offer2_deterministic_test_key_validation_only():
    packet = builder.build_packet(
        frame_nonce="00112233445566778899aabbccddeeff",
        now_ms=1_900_000_000_000,
        transport_nonce=1_900_000_000_001,
    )
    offer = packet["offer"]
    assert packet["status"] == "UNSIGNED_DO_NOT_POST"
    assert offer["id"] == builder.offer_id({k: v for k, v in offer.items() if k != "id"})
    assert offer["asset"] == "FLOP" and offer["amount"] == "200"
    assert offer["rails"] == ["paper"] and offer["job"]["proto"] == "a2a"
    assert offer["expiresMs"] == 1_900_064_800_000
    assert offer["claimByMs"] == 1_900_151_200_000
    assert offer["refundAfterMs"] == 1_900_172_800_000
    assert packet["frame"] == builder.PREFIX + builder.canonical_json(offer)

    # This constant key is deliberately synthetic and confined to protocol-format testing.
    test_key = ed25519.Ed25519PrivateKey.from_private_bytes(bytes([0x42]) * 32)
    payload = packet["transport_signing_payload"].encode("utf-8")
    signature = test_key.sign(payload)
    test_key.public_key().verify(signature, payload)
    assert base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    assert "signature" not in packet


def test_offer2_public_templates_have_no_absolute_deadline_or_secret_material():
    template = json.loads((ROOT / "docs" / "tclk-pilot" / "offer-2-template.json").read_text("utf-8"))
    assert template["status"] == "UNSIGNED_TEMPLATE_DO_NOT_POST"
    assert template["signature"] is None and template["posted"] is False
    assert set(template["deadline_offsets_ms"]) == {"expiresMs", "claimByMs", "refundAfterMs"}
    combined = "\n".join(
        path.read_text("utf-8")
        for path in (
            BUILDER_PATH,
            ROOT / "docs" / "tclk-pilot" / "offer-2-template.json",
            ROOT / "docs" / "tclk-pilot" / "offer-2-plan.md",
            ROOT / "docs" / "tclk-pilot" / "offer-2-signing-checkpoint.md",
        )
    ).lower()
    assert "c:\\users\\" not in combined and "c:/users/" not in combined
    for forbidden in ("sign_seed=", "private_key=", "wallet_seed=", "preimage="):
        assert forbidden not in combined
