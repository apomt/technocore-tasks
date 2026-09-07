from __future__ import annotations

import json

from .protocols import TaskRecord
from .storage import Store

Task = TaskRecord


class Board:
    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def _task(row: dict) -> Task:
        task = TaskRecord(
            task_id=row["task_id"], protocol=row["protocol_name"],
            protocol_version=row["protocol_version"], source_room=row["room"],
            creator_did=row["creator_did"], title=row["title"], description=row["description"],
            state=row["state"], normalized_state=row["normalized_state"], created_at=row["created_at"],
            assignee_did=row["assignee_did"], advertised=json.loads(row["advertised_json"]),
            partial_history=bool(row["partial_history"]),
        )
        task.projected_conflict_count = int(row["conflict_count"])
        task.projected_event_count = int(row["event_count"])
        task.projected_claim_count = int(row["claim_count"])
        task.projected_result_count = int(row["result_count"])
        task.projected_attestation_count = int(row["attestation_count"])
        task.projected_event_types = json.loads(row["event_types_json"])
        return task

    def search_page(self, query: str = "", state: str | None = None, protocol: str | None = None,
                    page: int = 1, page_size: int = 50) -> tuple[list[Task], dict]:
        rows, pagination = self.store.projection_rows(query, state, protocol, page=page, page_size=page_size)
        return [self._task(row) for row in rows], pagination

    def search(self, query: str = "", state: str | None = None, protocol: str | None = None,
               page: int = 1, page_size: int = 50) -> list[Task]:
        return self.search_page(query, state, protocol, page, page_size)[0]

    def all_tasks(self, page: int = 1, page_size: int = 50) -> list[Task]:
        return self.search(page=page, page_size=page_size)

    def task(self, task_id: str, protocol: str | None = None, page: int = 1,
             page_size: int = 50) -> Task | None:
        row = self.store.projection(task_id, protocol)
        if row is None:
            return None
        task = self._task(row)
        task.events, task.event_pagination = self.store.events(task_id, protocol, page, page_size, row["room"])
        task.conflicts, task.conflict_pagination = self.store.conflicts(row, page, page_size)
        task.claims = [event for event in task.events if event["event_kind"] == "CLAIM" and event["valid_transition"]]
        task.results = [event for event in task.events if event["event_kind"] in {"RESULT", "DELIVER", "COMPLETE"}
                        and event["valid_transition"]]
        task.attestations = [event for event in task.events if event["event_kind"] == "ATTEST" and event["valid_transition"]]
        valid = [event for event in task.events if event["valid_transition"]]
        task.assignment = next((event for event in reversed(valid) if event["event_kind"] == "ASSIGN"), None)
        task.completion = next((event for event in reversed(valid)
                                if event["event_kind"] in {"COMPLETE", "RESULT", "DELIVER"}), None)
        task.close_event = next((event for event in reversed(valid) if event["event_kind"] == "CLOSE"), None)
        task.cancel_event = next((event for event in reversed(valid) if event["event_kind"] == "CANCEL"), None)
        return task

    def did_tasks_page(self, did: str, page: int = 1, page_size: int = 50) -> tuple[list[Task], dict]:
        rows, pagination = self.store.projection_rows(did=did, page=page, page_size=page_size)
        return [self._task(row) for row in rows], pagination

    def did_tasks(self, did: str, page: int = 1, page_size: int = 50) -> list[Task]:
        return self.did_tasks_page(did, page, page_size)[0]

    def stats(self) -> dict:
        return {**self.store.projection_stats(), **self.store.counts()}
