from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .collector import Collector
from .config import Settings
from .events import build_event, canonical_task_id
from .storage import Store


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m technocore_tasks")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("did", help="print the DID derived from the local SIGN_SEED")

    create = commands.add_parser("create")
    create.add_argument("--title", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--reward")
    create.add_argument("--budget")
    create.add_argument("--payment")

    claim = commands.add_parser("claim")
    claim.add_argument("task_id")
    claim.add_argument("--note")

    assign = commands.add_parser("assign")
    assign.add_argument("task_id")
    assign.add_argument("assignee_did")

    complete = commands.add_parser("complete")
    complete.add_argument("task_id")
    complete.add_argument("--result")

    close = commands.add_parser("close")
    close.add_argument("task_id")

    cancel = commands.add_parser("cancel")
    cancel.add_argument("task_id")
    cancel.add_argument("--reason")

    commands.add_parser("sync", help="perform one read-only collector pass")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=int(os.getenv("PORT", "8800")))
    return root


def _post(kind: str, fields: dict[str, str], settings: Settings, nonce: int | None = None) -> dict:
    from .local_signing import LocalSigner, ensure_local_mode, load_seed, next_nonce, post_signed

    ensure_local_mode()
    signer = LocalSigner(load_seed())
    nonce = nonce or next_nonce()
    text = build_event(kind, fields)
    return post_signed(settings.base_url, settings.signing_room, signer, nonce, text)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    settings = Settings.from_env()
    try:
        if args.command == "did":
            from .local_signing import LocalSigner, ensure_local_mode, load_seed
            ensure_local_mode()
            print(LocalSigner(load_seed()).did)
            return 0
        if args.command == "sync":
            async def sync_all():
                store = Store(settings.database)
                return await asyncio.gather(*(
                    Collector(store, settings.base_url, room).collect_once()
                    for room in settings.source_rooms
                ))
            result = asyncio.run(sync_all())
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "serve":
            import uvicorn
            uvicorn.run("technocore_tasks.web:app", host=args.host, port=args.port)
            return 0

        fields: dict[str, str]
        nonce = None
        if args.command == "create":
            from .local_signing import LocalSigner, ensure_local_mode, load_seed, next_nonce
            ensure_local_mode()
            signer = LocalSigner(load_seed())
            nonce = next_nonce()
            task_id = canonical_task_id(signer.did, nonce, args.title)
            fields = {"task": task_id, "title": args.title}
            for name in ("description", "reward", "budget", "payment"):
                value = getattr(args, name)
                if value:
                    fields[name] = value
        elif args.command == "claim":
            fields = {"task": args.task_id}
            if args.note:
                fields["note"] = args.note
        elif args.command == "assign":
            fields = {"task": args.task_id, "assignee": args.assignee_did}
        elif args.command == "complete":
            fields = {"task": args.task_id}
            if args.result:
                fields["result"] = args.result
        elif args.command == "close":
            fields = {"task": args.task_id}
        else:
            fields = {"task": args.task_id}
            if args.reason:
                fields["reason"] = args.reason
        result = _post(args.command.upper(), fields, settings, nonce=nonce)
        safe = {key: result.get(key) for key in ("room", "posted", "last_seq") if key in result}
        print(json.dumps(safe, ensure_ascii=False))
        return 0
    except (RuntimeError, ValueError, http_error_types()) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def http_error_types() -> type[Exception]:
    import httpx
    return httpx.HTTPError
