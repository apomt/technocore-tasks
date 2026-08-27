import unicodedata

import pytest

from technocore_tasks.events import EventParseError, build_event, canonical_task_id, canonical_title, parse_event


def test_event_parser_round_trip_arbitrary_human_text(dids):
    task_id = canonical_task_id(dids[0], 42, "  Café\t review  ")
    text = build_event("CREATE", {
        "task": task_id,
        "title": "Café & <script>alert(1)</script>",
        "description": "line-like % text / 日本語 ? x=y",
        "reward": "$100 maybe",
    })
    assert " " not in text.split("title=", 1)[1].split(" ", 1)[0]
    parsed = parse_event(text)
    assert parsed.kind == "CREATE"
    assert parsed.fields["description"] == "line-like % text / 日本語 ? x=y"
    assert parsed.fields["reward"] == "$100 maybe"


def test_canonical_task_id_exact_algorithm(dids):
    composed = "  Café\t\nwork "
    decomposed = "Cafe\u0301 work"
    assert canonical_title(composed) == unicodedata.normalize("NFC", decomposed)
    assert canonical_task_id(dids[0], 7, composed) == canonical_task_id(dids[0], 7, decomposed)
    assert canonical_task_id(dids[0], 7, composed).startswith("task-")
    assert len(canonical_task_id(dids[0], 7, composed)) == 13


@pytest.mark.parametrize("text", [
    "TC-TASK/1 CREATE task=task-12345678 title=x title=y",
    "TC-TASK/1 CREATE task=task-12345678 title=%GG",
    "TC-TASK/1 CREATE task=bad title=x",
    "TC-TASK/1 CLAIM task=task-12345678 unknown=x",
    "TC-TASK/1 BOOM task=task-12345678",
    "TC-TASK/1 CREATE task=task-12345678 title=x\nboom",
])
def test_parser_rejects_ambiguous_or_unsafe_forms(text):
    with pytest.raises(EventParseError):
        parse_event(text)


def test_builder_is_deterministic(dids):
    fields = {"description": "d", "title": "t", "task": "task-12345678", "reward": "r"}
    assert build_event("CREATE", fields) == "TC-TASK/1 CREATE task=task-12345678 title=t description=d reward=r"

