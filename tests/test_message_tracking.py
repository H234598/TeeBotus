from __future__ import annotations

from TeeBotus.runtime.message_tracking import MessageTracker, SentMessageRef


def _ref(message_ref: str = "1") -> SentMessageRef:
    return SentMessageRef(
        channel="signal",
        instance_name="Demo",
        account_id="account-1",
        chat_id="+491",
        message_ref=message_ref,
        ref_kind="signal_timestamp",
    )


def test_message_tracker_record_deduplicates_refs() -> None:
    tracker = MessageTracker()
    ref = _ref("123")

    tracker.record(ref)
    tracker.record(ref)

    assert tracker.list_for_chat("+491", instance_name="Demo", channel="signal") == [ref]
    assert tracker.pop_for_cleanup(instance_name="Demo", channel="signal", chat_id="+491", count="all") == [ref]


def test_message_tracker_persisted_duplicates_are_not_reintroduced(tmp_path) -> None:
    path = tmp_path / "refs.json"
    ref = _ref("123")
    tracker = MessageTracker(path)
    tracker.record(ref)
    tracker.record(ref)

    reloaded = MessageTracker(path)

    assert reloaded.list_for_chat("+491", instance_name="Demo", channel="signal") == [ref]

