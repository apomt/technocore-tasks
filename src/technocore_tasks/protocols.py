from __future__ import annotations

import re
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Iterable

from .events import DID_RE, EventParseError, canonical_task_id, parse_event as parse_tc_event

KIBBLE_JOB_ID_RE = re.compile(r"^k[0-9a-f]{10}$")
WORK_ID_RE = re.compile(r"^(?:task-[0-9a-f]{8}|k[0-9a-f]{10})$")


@dataclass(frozen=True)
class AdapterParseResult:
    event_kind: str
    task_id: str
    fields: dict[str, str]


@dataclass
class TaskRecord:
    task_id: str
    protocol: str
    protocol_version: str
    source_room: str
    creator_did: str | None = None
    title: str = "Unknown work item (origin event not observed)"
    description: str = ""
    state: str = "partial"
    normalized_state: str | None = "partial"
    created_at: str | None = None
    claims: list[dict] = field(default_factory=list)
    assignee_did: str | None = None
    assignment: dict | None = None
    completion: dict | None = None
    results: list[dict] = field(default_factory=list)
    attestations: list[dict] = field(default_factory=list)
    close_event: dict | None = None
    cancel_event: dict | None = None
    events: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    advertised: dict[str, str] = field(default_factory=dict)
    partial_history: bool = False
    projected_conflict_count: int = 0
    projected_event_count: int = 0
    projected_claim_count: int = 0
    projected_result_count: int = 0
    projected_attestation_count: int = 0
    projected_event_types: list[str] = field(default_factory=list)
    event_pagination: dict = field(default_factory=dict)
    conflict_pagination: dict = field(default_factory=dict)

    @property
    def conflicted(self) -> bool:
        return bool(self.projected_conflict_count or self.conflicts)

    @property
    def missing_event_types(self) -> list[str]:
        if not self.partial_history:
            return []
        origin = "JOB" if self.protocol == "KIBBLE" else "CREATE"
        return [origin] if self.creator_did is None else []

    @property
    def missing_event_types_unknown(self) -> bool:
        return self.partial_history and not self.missing_event_types

    @property
    def observed_event_types(self) -> list[str]:
        return self.projected_event_types or list(dict.fromkeys(event["event_kind"] for event in self.events))

    def to_dict(self, detail: bool = True) -> dict:
        signed_events = [evidence(event) for event in self.events if event.get("signed")]
        signed_facts = {
            "creator_did": self.creator_did,
            "events": signed_events,
            "claims": [evidence(event) for event in self.claims if event.get("signed")],
            "results": [evidence(event) for event in self.results if event.get("signed")],
            "attestations": [evidence(event) for event in self.attestations if event.get("signed")],
            "assignment": evidence(self.assignment) if self.assignment and self.assignment.get("signed") else None,
            "completion": evidence(self.completion) if self.completion and self.completion.get("signed") else None,
        }
        data = {
            "task_id": self.task_id,
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
            "source_room": self.source_room,
            "native_state": self.state,
            "normalized_state": self.normalized_state,
            "title": self.title,
            "description": self.description,
            "creator_did": self.creator_did,
            "created_at": self.created_at,
            "partial_history": self.partial_history,
            "missing_event_types": self.missing_event_types,
            "missing_event_types_unknown": self.missing_event_types_unknown,
            "observed_event_types": self.observed_event_types,
            "conflicts": deepcopy(self.conflicts),
            "conflict_count": self.projected_conflict_count or len(self.conflicts),
            "observed_signed_facts": signed_facts,
            "observed_signed_events": signed_events,
            "advertised_unverified_fields": deepcopy(self.advertised),
            "derived_state": {
                "state": self.state,
                "normalized_state": self.normalized_state,
                "assignee_did": self.assignee_did,
                "claim_count": self.projected_claim_count or len(self.claims),
                "event_count": self.projected_event_count or len(self.events),
                "result_count": self.projected_result_count or len(self.results),
                "attestation_count": self.projected_attestation_count or len(self.attestations),
                "partial_history": self.partial_history,
                "conflicted": self.conflicted,
            },
            "advertised_unverified": deepcopy(self.advertised),
        }
        if detail:
            timeline = []
            for event in self.events:
                item = public_event(event)
                item["partial_history"] = self.partial_history
                item["conflicts"] = [
                    deepcopy(conflict) for conflict in self.conflicts
                    if conflict.get("seq") == event.get("seq") and conflict.get("room") == event.get("room")
                ]
                timeline.append(item)
            data["event_timeline"] = timeline
            data["event_pagination"] = deepcopy(self.event_pagination)
            data["conflict_pagination"] = deepcopy(self.conflict_pagination)
        return data


def evidence(event: dict) -> dict:
    return {
        "protocol": event["protocol_name"],
        "protocol_version": event["protocol_version"],
        "source_room": event["room"],
        "signer_did": event.get("signer_did"),
        "room_sequence": event["seq"],
        "nonce": event.get("nonce"),
        "timestamp": event["timestamp"],
        "exact_original_text": event["original_message"],
        "native_event_type": event["event_kind"],
        "parsed_fields": deepcopy(event["fields"]),
        "evidence_level": "signed_key_possession" if event.get("signed") else "unsigned_observation",
    }


def public_event(event: dict) -> dict:
    item = evidence(event)
    item.update({
        "room": event["room"], "seq": event["seq"], "original_message": event["original_message"],
        "event_kind": event["event_kind"], "fields": deepcopy(event["fields"]),
        "signed": bool(event.get("signed")), "valid_transition": event.get("valid_transition", False),
        "reason": event.get("reason"),
    })
    return item


def _reject(task: TaskRecord, event: dict, reason: str, conflict: bool = True) -> None:
    event["valid_transition"] = False
    event["reason"] = reason
    if conflict:
        task.conflicts.append({"room": event["room"], "seq": event["seq"], "kind": event["event_kind"], "reason": reason})


class TaskProtocolAdapter(ABC):
    protocol_name: str
    protocol_version: str

    @abstractmethod
    def detect(self, text: str) -> bool: ...

    @abstractmethod
    def parse_event(self, text: str) -> AdapterParseResult: ...

    @abstractmethod
    def apply_event(self, task: TaskRecord, event: dict) -> None: ...

    @abstractmethod
    def reduce(self, task_id: str, source_room: str, events: Iterable[dict], partial: bool) -> TaskRecord: ...


class TCTaskV1Adapter(TaskProtocolAdapter):
    protocol_name = "TC-TASK"
    protocol_version = "1"

    def detect(self, text: str) -> bool:
        return text.startswith("TC-TASK/")

    def parse_event(self, text: str) -> AdapterParseResult:
        parsed = parse_tc_event(text)
        return AdapterParseResult(parsed.kind, parsed.task_id, parsed.fields)

    def apply_event(self, task: TaskRecord, event: dict) -> None:
        events = task.events if event in task.events else [*task.events, event]
        rebuilt = self.reduce(task.task_id, task.source_room, events, task.partial_history)
        task.__dict__.update(rebuilt.__dict__)

    def reduce(self, task_id: str, source_room: str, events: Iterable[dict], partial: bool) -> TaskRecord:
        task = TaskRecord(task_id, self.protocol_name, self.protocol_version, source_room)
        terminal = False
        assignment_dids: set[str] = set()
        task.partial_history = partial
        for source in events:
            event = deepcopy(source)
            task.events.append(event)
            kind, fields, signer = event["event_kind"], event["fields"], event.get("signer_did")
            if not event.get("signed") or not signer or not DID_RE.fullmatch(signer):
                _reject(task, event, "unsigned or invalid-DID event is not authoritative")
                continue
            if kind == "CREATE":
                expected = canonical_task_id(signer, event["nonce"], fields["title"])
                if expected != task_id:
                    _reject(task, event, f"CREATE task id mismatch; expected {expected}")
                    task.partial_history = True
                    continue
                if task.creator_did is not None:
                    _reject(task, event, "duplicate CREATE preserved; earliest valid CREATE establishes the task")
                    continue
                event.update(valid_transition=True, reason=None)
                task.creator_did, task.title = signer, fields["title"]
                task.description, task.created_at = fields.get("description", ""), event["timestamp"]
                task.state = task.normalized_state = "open"
                task.advertised = {k: fields[k] for k in ("reward", "budget", "payment") if k in fields}
                continue
            if task.creator_did is None:
                task.partial_history = True
                _reject(task, event, "partial history: valid CREATE was not observed", conflict=False)
                continue
            if kind == "CLAIM":
                if terminal:
                    _reject(task, event, "CLAIM occurred after a terminal event")
                else:
                    event.update(valid_transition=True, reason=None)
                    task.claims.append(event)
                    if task.assignment is None:
                        task.state = task.normalized_state = "claimed"
                continue
            if kind == "ASSIGN":
                assignee = fields["assignee"]
                claimant_dids = {claim["signer_did"] for claim in task.claims}
                if signer != task.creator_did:
                    _reject(task, event, "ASSIGN signer is not the original creator DID")
                elif terminal or task.completion is not None:
                    _reject(task, event, "ASSIGN occurred after completion or a terminal event")
                elif assignee not in claimant_dids:
                    _reject(task, event, "ASSIGN target has no observed valid CLAIM")
                else:
                    event.update(valid_transition=True, reason=None)
                    if assignment_dids and assignee not in assignment_dids:
                        task.conflicts.append({"room": event["room"], "seq": event["seq"], "kind": kind,
                                               "reason": "conflicting creator-signed ASSIGN; latest valid event wins"})
                    assignment_dids.add(assignee)
                    task.assignment, task.assignee_did = event, assignee
                    task.state, task.normalized_state = "assigned", "claimed"
                continue
            if kind == "COMPLETE":
                if terminal:
                    _reject(task, event, "COMPLETE occurred after a terminal event")
                elif not task.assignee_did:
                    _reject(task, event, "COMPLETE has no valid assignment")
                elif signer != task.assignee_did:
                    _reject(task, event, "COMPLETE signer is not the latest valid assignee DID")
                else:
                    event.update(valid_transition=True, reason=None)
                    if task.completion is not None and task.completion["fields"] != fields:
                        task.conflicts.append({"room": event["room"], "seq": event["seq"], "kind": kind,
                                               "reason": "conflicting COMPLETE; latest valid event wins"})
                    task.completion = event
                    task.results.append(event)
                    task.state, task.normalized_state = "completed", "results_submitted"
                continue
            if kind in {"CLOSE", "CANCEL"}:
                if signer != task.creator_did:
                    _reject(task, event, f"{kind} signer is not the original creator DID")
                elif terminal:
                    _reject(task, event, "duplicate or conflicting terminal event")
                else:
                    event.update(valid_transition=True, reason=None)
                    if kind == "CLOSE":
                        task.close_event = event
                        task.state, task.normalized_state = "closed", "attested_completed"
                    else:
                        task.cancel_event = event
                        task.state, task.normalized_state = "cancelled", None
                    terminal = True
        if task.creator_did is None:
            task.state, task.normalized_state, task.partial_history = "partial", "partial", True
        return task


class KibbleV1Adapter(TaskProtocolAdapter):
    protocol_name = "KIBBLE"
    protocol_version = "1"
    prefixes = ("JOB v1 |", "CLAIM v1 |", "RESULT v1 |", "DELIVER v1 |", "ATTEST v1 |")

    def detect(self, text: str) -> bool:
        return text.startswith(self.prefixes)

    @staticmethod
    def _clean(parts: list[str], expected: int) -> None:
        if len(parts) != expected or any(not part.strip() for part in parts):
            raise EventParseError("malformed KIBBLE-V1 event")

    def parse_event(self, text: str) -> AdapterParseResult:
        if any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in text):
            raise EventParseError("event contains control characters")
        head = text.split(" | ", 1)[0]
        if head == "JOB v1":
            parts = text.split(" | ", 4)
            self._clean(parts, 5)
            fields = {"job": parts[1], "category": parts[2], "title": parts[3], "body": parts[4]}
        elif head in {"CLAIM v1", "RESULT v1", "DELIVER v1"}:
            parts = text.split(" | ", 2)
            self._clean(parts, 3)
            name = "claim" if head == "CLAIM v1" else "result"
            fields = {"job": parts[1], name: parts[2]}
        elif head == "ATTEST v1":
            parts = text.split(" | ", 3)
            if len(parts) != 4 or any(not part.strip() for part in parts):
                raise EventParseError("malformed KIBBLE-V1 ATTEST")
            if parts[2] not in {"useful", "not"}:
                raise EventParseError("unknown KIBBLE-V1 ATTEST verdict")
            fields = {"job": parts[1], "verdict": parts[2]}
            hash_match = re.match(r"^(rh:[0-9a-f]{16}) \| (.+)$", parts[3])
            if hash_match:
                fields.update(result_hash=hash_match.group(1), reason=hash_match.group(2))
            elif parts[3].startswith("rh:"):
                raise EventParseError("invalid KIBBLE-V1 result hash reference")
            else:
                fields["reason"] = parts[3]
        else:
            raise EventParseError("not a KIBBLE-V1 event")
        if not KIBBLE_JOB_ID_RE.fullmatch(fields["job"]):
            raise EventParseError("invalid observed KIBBLE-V1 job id form")
        return AdapterParseResult(head.removesuffix(" v1"), fields["job"], fields)

    def apply_event(self, task: TaskRecord, event: dict) -> None:
        kind, fields, signer = event["event_kind"], event["fields"], event.get("signer_did")
        if not event.get("signed") or not signer or not DID_RE.fullmatch(signer):
            _reject(task, event, "unsigned or invalid-DID line is not signed evidence")
            return
        event.update(valid_transition=True, reason=None)
        if kind == "JOB":
            if task.creator_did is None:
                task.creator_did, task.title = signer, fields["title"]
                task.description, task.created_at = fields["body"], event["timestamp"]
                task.advertised = {"category": fields["category"]}
            else:
                _reject(task, event, "multiple signed JOB origins observed; earliest is displayed")
        elif kind == "CLAIM":
            task.claims.append(event)
        elif kind in {"RESULT", "DELIVER"}:
            task.results.append(event)
            task.completion = event
        elif kind == "ATTEST":
            task.attestations.append(event)

    def reduce(self, task_id: str, source_room: str, events: Iterable[dict], partial: bool) -> TaskRecord:
        task = TaskRecord(task_id, self.protocol_name, self.protocol_version, source_room)
        task.partial_history = partial
        for source in events:
            event = deepcopy(source)
            task.events.append(event)
            self.apply_event(task, event)
        claimers = {e.get("signer_did") for e in task.claims if e.get("signed")}
        if len(claimers) > 1:
            task.conflicts.append({"room": source_room, "seq": task.claims[-1]["seq"], "kind": "CLAIM",
                                   "reason": "multiple signer DIDs claimed this job; exclusivity is unspecified and not adjudicated"})
        result_values = {e["fields"].get("result") for e in task.results if e.get("signed")}
        if len(result_values) > 1:
            task.conflicts.append({"room": source_room, "seq": task.results[-1]["seq"], "kind": task.results[-1]["event_kind"],
                                   "reason": "different signed result texts were observed; no winner is inferred"})
        verdicts = {e["fields"].get("verdict") for e in task.attestations if e.get("signed")}
        if len(verdicts) > 1:
            task.conflicts.append({"room": source_room, "seq": task.attestations[-1]["seq"], "kind": "ATTEST",
                                   "reason": "both useful and not attestations were observed; no authority ranking is inferred"})
        if task.creator_did is None:
            task.state, task.normalized_state, task.partial_history = "partial", "partial", True
        elif task.attestations:
            task.state, task.normalized_state = "attested", "attested_completed"
        elif task.results:
            task.state, task.normalized_state = "result", "results_submitted"
        elif task.claims:
            task.state = task.normalized_state = "claimed"
        else:
            task.state = task.normalized_state = "open"
        return task


ADAPTERS: tuple[TaskProtocolAdapter, ...] = (KibbleV1Adapter(), TCTaskV1Adapter())
ADAPTER_BY_KEY = {(adapter.protocol_name, adapter.protocol_version): adapter for adapter in ADAPTERS}


def detect_and_parse(text: str) -> tuple[TaskProtocolAdapter | None, AdapterParseResult | None, str | None]:
    for adapter in ADAPTERS:
        if adapter.detect(text):
            try:
                return adapter, adapter.parse_event(text), None
            except EventParseError as exc:
                return adapter, None, str(exc)
    return None, None, None


def protocol_catalog() -> list[dict]:
    return [
        {
            "protocol": "KIBBLE", "version": "1", "display_name": "KIBBLE-V1",
            "default_source_room": "kibble",
            "status": "independent read-only exploration of an externally published convention",
            "native_events": ["JOB", "CLAIM", "RESULT", "DELIVER", "ATTEST"],
            "observed_grammar": [
                "JOB v1 | <job_id> | <category> | <title> | <body>",
                "CLAIM v1 | <job_id> | <claim text>",
                "RESULT v1 | <job_id> | <result text>",
                "DELIVER v1 | <job_id> | <result text>",
                "ATTEST v1 | <job_id> | useful|not | [rh:<result_hash> |] <reason>",
            ],
            "external_specification": {
                "label": "Kibble-hosted specification",
                "url": "https://flop-kibble.onrender.com/llms.txt",
                "ui_url": "https://flop-kibble.onrender.com/",
                "publisher_status": "external protocol publisher; not independently proven to be official FLOP Labs or Technocore authority",
                "documented_claims": [
                    "Kibble is a public useful-work job board using schema kibble-v1.",
                    "The native lifecycle is JOB, CLAIM, RESULT, and ATTEST; DELIVER is read as RESULT.",
                    "Identity uses did:key, and poster, worker, and validator are documented as separate parties.",
                    "Kibble says it is not flop.finance and describes itself as a board 'until $FLOP can pay'.",
                    "Ranking is described as a recomputed advisory IOU, not a redeemable balance.",
                ],
            },
            "provenance": {
                "kibble_hosted_specification": "rules documented by the external Kibble host",
                "observed_signed_tape": "signed-lane events actually retained from Technocore room kibble",
                "reconstructed_state": "deterministic Technocore Tasks projection of retained events",
                "inferred_or_unknown": "anything not explicitly established by the external specification or signed tape",
                "room_topic_claim": "untrusted caller-created Technocore note",
            },
            "observed_client_id_generation": "one independent client uses k + 5 random bytes as lowercase hex",
            "limitations": [
                "not an official Technocore task board",
                "not independently established as an official FLOP Labs protocol",
                "no current payment or escrow mechanism is established here; no guaranteed airdrop, balance, or redemption",
                "retained room history can be incomplete",
            ],
        },
        {
            "protocol": "TC-TASK", "version": "1", "display_name": "TC-TASK/1",
            "default_source_room": None,
            "status": "experimental community convention implemented by this project",
            "native_events": ["CREATE", "CLAIM", "ASSIGN", "COMPLETE", "CLOSE", "CANCEL"],
            "source_status": "disabled by default; no dedicated room currently exists",
            "provenance": {
                "specification": "project-local community convention",
                "observed_signed_tape": "none currently configured by default",
                "reconstructed_state": "deterministic projection when compatible events are explicitly collected",
            },
            "limitations": ["experimental", "no dedicated live room", "must not be written into unrelated rooms"],
        },
    ]
