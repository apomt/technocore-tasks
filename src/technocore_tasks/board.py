from __future__ import annotations

from collections import defaultdict

from .protocols import ADAPTER_BY_KEY, TaskRecord
from .storage import Store

Task = TaskRecord


class Board:
    def __init__(self, store: Store):
        self.store = store

    def all_tasks(self) -> list[Task]:
        grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
        for event in self.store.events():
            key = (event["protocol_name"], event["protocol_version"], event["room"], event["task_id"])
            grouped[key].append(event)
        tasks = []
        for (protocol, version, room, task_id), events in grouped.items():
            adapter = ADAPTER_BY_KEY[(protocol, version)]
            tasks.append(adapter.reduce(task_id, room, events, bool(self.store.gaps(room))))
        return sorted(tasks, key=lambda task: (task.created_at or "", task.task_id), reverse=True)

    def task(self, task_id: str, protocol: str | None = None) -> Task | None:
        matches = [task for task in self.all_tasks() if task.task_id == task_id]
        if protocol:
            wanted = protocol.upper().replace("-V1", "").replace("/1", "")
            matches = [task for task in matches if task.protocol == wanted]
        return matches[0] if len(matches) == 1 else None

    def search(self, query: str = "", state: str | None = None, protocol: str | None = None) -> list[Task]:
        needle = query.casefold().strip()
        wanted = protocol.upper().replace("-V1", "").replace("/1", "") if protocol else None
        result = []
        for task in self.all_tasks():
            if wanted and task.protocol != wanted:
                continue
            state_match = task.conflicted if state == "conflicted" else (
                not state or task.state == state or task.normalized_state == state
            )
            participants = [event.get("signer_did") or "" for event in task.events]
            haystack = "\n".join([task.task_id, task.protocol, task.source_room, task.creator_did or "",
                                   task.title, task.description, task.assignee_did or "", *participants]).casefold()
            if state_match and (not needle or needle in haystack):
                result.append(task)
        return result

    def did_tasks(self, did: str) -> list[Task]:
        return [task for task in self.all_tasks() if any(event.get("signer_did") == did for event in task.events)]

    def stats(self) -> dict:
        tasks = self.all_tasks()
        native, protocols = defaultdict(int), defaultdict(int)
        for task in tasks:
            native[task.state] += 1
            protocols[f"{task.protocol}-{task.protocol_version}"] += 1
        return {"tasks": len(tasks), "native_states": dict(native), "states": dict(native),
                "protocols": dict(protocols), "conflicted": sum(t.conflicted for t in tasks),
                "partial_history": sum(t.partial_history for t in tasks), **self.store.counts()}
