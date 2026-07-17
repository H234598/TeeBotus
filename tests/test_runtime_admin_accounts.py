from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path

from TeeBotus import __version__
from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key, telegram_identity_key
from TeeBotus.runtime.actions import SendAttachment, SendText
from TeeBotus.runtime.admin_accounts import (
    ADMIN_ACCOUNT_IDS_ENV,
    DEFAULT_ADMIN_ACCOUNT_IDS,
    STATUS_SUMMARY_INSTANCE_NAME,
    admin_account_group_status_lines,
    format_admin_notification_result_lines,
    notify_benchmark_admin_accounts,
    notify_runtime_status_admin_accounts,
    resolve_admin_account_group,
    runtime_status_problem_lines,
)
from TeeBotus.runtime import admin_accounts as admin_accounts_module


def store_for(root: Path, instance_name: str = "Depressionsbot") -> AccountStore:
    return AccountStore(root / "accounts", instance_name, StaticSecretProvider(b"a" * 32))


def status_summary_store_for(instances_dir: Path) -> AccountStore:
    return store_for(instances_dir / STATUS_SUMMARY_INSTANCE_NAME / "data", STATUS_SUMMARY_INSTANCE_NAME)


def test_default_admin_store_uses_runtime_secret_retry_policy(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRIES", "2")
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_LOOKUP_RETRY_DELAY_SECONDS", "0.25")
    monkeypatch.setenv("TEEBOTUS_SECRET_TOOL_TIMEOUT_SECONDS", "4")

    store = admin_accounts_module._default_account_store(tmp_path, "Demo")
    provider = store.secret_provider.delegate

    assert provider.create_if_missing is False
    assert provider.lookup_retries == 2
    assert provider.lookup_retry_delay_seconds == 0.25
    assert provider.timeout_seconds == 4.0


def test_default_admin_group_contains_configured_account_ids() -> None:
    group = resolve_admin_account_group(env={})

    assert group.account_ids == DEFAULT_ADMIN_ACCOUNT_IDS
    assert group.invalid_ids == ()
    assert group.source == "default"


def test_admin_group_env_parses_ids_deduplicates_and_reports_invalid() -> None:
    group = resolve_admin_account_group(
        instance_name="Depressionsbot",
        env={ADMIN_ACCOUNT_IDS_ENV: f"<{DEFAULT_ADMIN_ACCOUNT_IDS[0]}> nope {DEFAULT_ADMIN_ACCOUNT_IDS[0].upper()}"},
    )

    assert group.account_ids == (DEFAULT_ADMIN_ACCOUNT_IDS[0],)
    assert group.invalid_ids == ("nope",)
    assert group.source == ADMIN_ACCOUNT_IDS_ENV


def test_admin_account_status_redacts_secret_like_invalid_ids(tmp_path) -> None:
    account_store = store_for(tmp_path)

    lines = admin_account_group_status_lines(
        instance_name="Depressionsbot",
        project_root=tmp_path,
        env={ADMIN_ACCOUNT_IDS_ENV: "sk-testsecret123456"},
        store=account_store,
    )

    joined = "\n".join(lines)
    assert "sk-testsecret123456" not in joined
    assert "admin_account=Depressionsbot/sk-<redacted> status=broken reason=invalid_account_id" in lines


def test_admin_group_instance_env_overrides_global_env() -> None:
    instance_env = "TEEBOTUS_ADMIN_ACCOUNT_IDS_DEPRESSIONSBOT"
    group = resolve_admin_account_group(
        instance_name="Depressionsbot",
        env={
            ADMIN_ACCOUNT_IDS_ENV: DEFAULT_ADMIN_ACCOUNT_IDS[0],
            instance_env: DEFAULT_ADMIN_ACCOUNT_IDS[1],
        },
    )

    assert group.account_ids == (DEFAULT_ADMIN_ACCOUNT_IDS[1],)
    assert group.source == instance_env


def test_admin_group_uses_process_environment_when_env_is_omitted(monkeypatch) -> None:
    monkeypatch.setenv(ADMIN_ACCOUNT_IDS_ENV, DEFAULT_ADMIN_ACCOUNT_IDS[0])

    group = resolve_admin_account_group()

    assert group.account_ids == (DEFAULT_ADMIN_ACCOUNT_IDS[0],)
    assert group.source == ADMIN_ACCOUNT_IDS_ENV


def test_admin_account_status_uses_account_route(tmp_path) -> None:
    account_store = store_for(tmp_path)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)

    lines = admin_account_group_status_lines(
        instance_name="Depressionsbot",
        project_root=tmp_path,
        env={ADMIN_ACCOUNT_IDS_ENV: account_id},
        store=account_store,
    )

    assert lines[0].startswith("admin_accounts=Depressionsbot status=configured")
    assert f"admin_account=Depressionsbot/{account_id} status=routable channel=telegram slot=1 source_instance=Depressionsbot" in lines


def test_admin_account_status_summarizes_not_local_accounts_without_ids(tmp_path) -> None:
    account_store = store_for(tmp_path)

    lines = admin_account_group_status_lines(
        instance_name="Depressionsbot",
        project_root=tmp_path,
        env={ADMIN_ACCOUNT_IDS_ENV: DEFAULT_ADMIN_ACCOUNT_IDS[0]},
        store=account_store,
    )

    assert lines == (
        "admin_accounts=Depressionsbot status=configured source=TEEBOTUS_ADMIN_ACCOUNT_IDS "
        "accounts=1 local=0 cross_instance=0 not_local=1 routable=0 warnings=0 invalid=0",
    )
    assert DEFAULT_ADMIN_ACCOUNT_IDS[0] not in "\n".join(lines)
    assert not account_store.account_dir(DEFAULT_ADMIN_ACCOUNT_IDS[0]).exists()


def test_admin_account_status_reports_cross_instance_routable_admin(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    logger_store = status_summary_store_for(instances_dir)
    source_store = store_for(instances_dir / "Depressionsbot" / "data", "Depressionsbot")
    identity = telegram_identity_key(123)
    account_id = source_store.resolve_or_create_account(identity)
    source_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    logger_store.account_dir(account_id).mkdir(parents=True)

    def store_factory(_root: Path, instance_name: str) -> AccountStore:
        if instance_name == STATUS_SUMMARY_INSTANCE_NAME:
            return logger_store
        if instance_name == "Depressionsbot":
            return source_store
        raise AssertionError(f"unexpected instance store: {instance_name}")

    lines = admin_account_group_status_lines(
        instance_name=STATUS_SUMMARY_INSTANCE_NAME,
        project_root=tmp_path,
        env={ADMIN_ACCOUNT_IDS_ENV: account_id},
        store=logger_store,
        store_factory=store_factory,
    )

    assert lines[0] == (
        f"admin_accounts={STATUS_SUMMARY_INSTANCE_NAME} status=configured source=TEEBOTUS_ADMIN_ACCOUNT_IDS "
        "accounts=1 local=1 cross_instance=1 not_local=0 routable=1 warnings=0 invalid=0"
    )
    assert (
        f"admin_account={STATUS_SUMMARY_INSTANCE_NAME}/{account_id} status=routable "
        "channel=telegram slot=1 source_instance=Depressionsbot"
    ) in lines


def test_runtime_status_problem_lines_extracts_warnings_and_errors() -> None:
    output = "\n".join(
        [
            "[Messenger]",
            "telegram_slot=Depressionsbot/default status=configured token=configured",
            "matrix_account=Depressionsbot/default status=broken error=missing",
            "account_identity_warning=Depressionsbot status=warning reason=unlinked",
            "signal_account=Depressionsbot/default status=registered warning=sync_messages_ignored",
            "gemini_free_tier_limits status=fallback_defaults error=public_source_unavailable",
            "structured_decision=Depressionsbot status=enabled route_status=unavailable route_error=pool_disabled",
        ]
    )

    assert runtime_status_problem_lines(output) == (
        "matrix_account=Depressionsbot/default status=broken error=missing",
        "account_identity_warning=Depressionsbot status=warning reason=unlinked",
        "signal_account=Depressionsbot/default status=registered warning=sync_messages_ignored",
        "gemini_free_tier_limits status=fallback_defaults error=public_source_unavailable",
        "structured_decision=Depressionsbot status=enabled route_status=unavailable route_error=pool_disabled",
    )


def test_runtime_status_problem_lines_redacts_secrets() -> None:
    output = "llm_route=hard_reasoning status=broken error=token sk-testsecret123456 leaked"

    assert runtime_status_problem_lines(output) == (
        "llm_route=hard_reasoning status=broken error=token sk-<redacted> leaked",
    )


def test_runtime_status_problem_lines_honors_non_positive_limit() -> None:
    output = "telegram status=broken error=bad\nsignal status=warning reason=slow"

    assert runtime_status_problem_lines(output, limit=0) == ()
    assert runtime_status_problem_lines(output, limit=-1) == ()


def test_runtime_status_admin_notify_sends_to_routable_admin_account(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    sent: list[tuple[dict[str, object], SendAttachment]] = []

    def sender(route: dict[str, object], action: SendAttachment, _metadata: dict[str, object]) -> str:
        sent.append((route, action))
        return "ok"

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=lambda _instance, _store: {"telegram": sender},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert lines == (f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={account_id} channel=telegram",)
    assert len(sent) == 1
    action = sent[0][1]
    assert isinstance(action, SendAttachment)
    assert action.chat_id == "123"
    assert action.caption == f"Release TeeBotus {__version__}"
    assert action.content_type == "text/markdown"
    assert action.filename == f"TeeBotus_release_{__version__}_0001.md"
    markdown = action.data.decode("utf-8")
    assert markdown.startswith(f"# Release TeeBotus {__version__}\n")
    assert f"**Summary:** `v{__version__} #0001`" in markdown
    assert "## Probleme" in markdown
    assert "- `telegram_slot=Depressionsbot/default status=broken error=bad`" in markdown
    outbox = account_store.read_status_outbox(account_id)
    assert outbox[0]["status"] == "sent"
    assert outbox[0]["summary_number"] == 1
    assert outbox[0]["summary_prefix"] == f"v{__version__} #0001"
    assert outbox[0]["message_text"] == f"Release TeeBotus {__version__}"
    assert outbox[0]["markdown_filename"] == f"TeeBotus_release_{__version__}_0001.md"
    assert outbox[0]["markdown_document"].startswith(f"# Release TeeBotus {__version__}\n")
    assert account_store.read_status_dispatch_results(account_id)[0]["status"] == "sent"


def test_runtime_status_admin_notify_honors_cross_instance_admin_opt_out(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    logger_store = status_summary_store_for(instances_dir)
    source_store = store_for(instances_dir / "Depressionsbot" / "data", "Depressionsbot")
    identity = telegram_identity_key(123)
    account_id = source_store.resolve_or_create_account(identity)
    source_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    source_store.write_status_auth_state(
        account_id,
        {"schema_version": 1, "authorized": False, "admin_opt_out": True},
    )
    sent: list[SendAttachment] = []

    def store_factory(_root: Path, instance_name: str) -> AccountStore:
        if instance_name == STATUS_SUMMARY_INSTANCE_NAME:
            return logger_store
        if instance_name == "Depressionsbot":
            return source_store
        raise AssertionError(f"unexpected instance store: {instance_name}")

    results = asyncio.run(
        notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=store_factory,
            sender_factory=lambda _instance, _store: {"telegram": lambda _route, action, _metadata: sent.append(action) or "ok"},
        )
    )

    assert format_admin_notification_result_lines(results) == (
        f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=skipped account_id={account_id} reason=admin_opt_out",
    )
    assert sent == []
    assert logger_store.read_status_outbox(account_id) == []


def test_runtime_status_dispatch_audit_failure_does_not_hide_delivery(tmp_path, monkeypatch, caplog) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)

    def fail_dispatch_result(*_args, **_kwargs):
        raise OSError("dispatch result store unavailable")

    monkeypatch.setattr(account_store, "append_status_dispatch_result", fail_dispatch_result)
    with caplog.at_level(logging.ERROR, logger="TeeBotus.runtime.admin_accounts"):
        results = asyncio.run(
            notify_runtime_status_admin_accounts(
                instances_dir=instances_dir,
                selected_instances=("Depressionsbot",),
                status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
                env={ADMIN_ACCOUNT_IDS_ENV: account_id},
                store_factory=lambda _root, _instance: account_store,
                sender_factory=lambda _instance, _store: {"telegram": lambda _route, _action, _metadata: "ok"},
                now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
            )
        )

    assert format_admin_notification_result_lines(results) == (
        f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={account_id} channel=telegram",
    )
    assert account_store.read_status_outbox(account_id)[0]["status"] == "sent"
    assert account_store.read_status_dispatch_results(account_id) == []
    assert "Runtime status dispatch result persistence failed" in caplog.text


def test_benchmark_admin_notify_sends_markdown_attachment_to_routable_admin_account(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    sent: list[tuple[dict[str, object], SendAttachment, dict[str, object]]] = []

    def sender(route: dict[str, object], action: SendAttachment, metadata: dict[str, object]) -> str:
        sent.append((route, action, metadata))
        return "ok"

    async def run_notify() -> tuple[str, ...]:
        results = await notify_benchmark_admin_accounts(
            instances_dir=instances_dir,
            markdown_document="# TeeBotus Benchmarks\n\nok\n",
            markdown_filename="teebotus-benchmarks-latest.md",
            json_artifact_path=tmp_path / "teebotus-benchmarks-latest.json",
            benchmark_suite={"ok": True, "quick": True, "results": [{"name": "memory_jsonl"}]},
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=lambda _instance, _store: {"telegram": sender},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert lines == (f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={account_id} channel=telegram",)
    assert len(sent) == 1
    _route, action, metadata = sent[0]
    assert isinstance(action, SendAttachment)
    assert action.chat_id == "123"
    assert action.caption == f"Benchmark TeeBotus {__version__}"
    assert action.content_type == "text/markdown"
    assert action.filename == "teebotus-benchmarks-latest.md"
    assert action.data.decode("utf-8").startswith("# TeeBotus Benchmarks\n")
    assert metadata == {"source": "benchmark_admin", "account_id": account_id}
    outbox = account_store.read_status_outbox(account_id)
    assert outbox[0]["kind"] == "benchmark_summary"
    assert outbox[0]["status"] == "sent"
    assert outbox[0]["summary_number"] == 1
    assert outbox[0]["summary_prefix"] == f"v{__version__} #0001"
    assert outbox[0]["message_text"] == f"Benchmark TeeBotus {__version__}"
    assert outbox[0]["benchmark_ok"] is True
    assert outbox[0]["benchmark_quick"] is True
    assert outbox[0]["benchmark_result_count"] == 1
    assert account_store.read_status_dispatch_results(account_id)[0]["status"] == "sent"


def test_benchmark_admin_notify_uses_cross_instance_admin_route_but_writes_logger_outbox(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    logger_store = status_summary_store_for(instances_dir)
    source_store = store_for(instances_dir / "Depressionsbot" / "data", "Depressionsbot")
    identity = telegram_identity_key(123)
    account_id = source_store.resolve_or_create_account(identity)
    source_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    logger_store.account_dir(account_id).mkdir(parents=True)
    sent: list[tuple[dict[str, object], SendAttachment]] = []
    sender_instances: list[str] = []

    def store_factory(_root: Path, instance_name: str) -> AccountStore:
        if instance_name == STATUS_SUMMARY_INSTANCE_NAME:
            return logger_store
        if instance_name == "Depressionsbot":
            return source_store
        raise AssertionError(f"unexpected instance store: {instance_name}")

    async def run_notify() -> tuple[str, ...]:
        results = await notify_benchmark_admin_accounts(
            instances_dir=instances_dir,
            markdown_document="# TeeBotus Benchmarks\n\nok\n",
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=store_factory,
            sender_factory=lambda instance, _store: sender_instances.append(instance)
            or {"telegram": lambda route, action, _metadata: sent.append((route, action)) or "ok"},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert lines == (f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={account_id} channel=telegram",)
    assert len(sent) == 1
    route, action = sent[0]
    assert route["chat_id"] == "123"
    assert route["route_source_instance"] == "Depressionsbot"
    assert sender_instances == ["Depressionsbot"]
    assert action.caption == f"Benchmark TeeBotus {__version__}"
    assert logger_store.read_status_outbox(account_id)[0]["kind"] == "benchmark_summary"
    assert source_store.read_status_outbox(account_id) == []


def test_runtime_status_admin_notify_includes_code_authenticated_status_recipients(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    account_store.write_status_auth_state(
        account_id,
        {
            "schema_version": 1,
            "authorized": True,
            "authorized_at": "2026-06-19T12:00:00+00:00",
            "source": "runtime_code",
        },
    )
    sent: list[SendAttachment] = []

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="signal_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: ""},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=lambda _instance, _store: {"telegram": lambda _route, action, _metadata: sent.append(action) or "ok"},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert lines == (f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={account_id} channel=telegram",)
    assert len(sent) == 1
    assert sent[0].caption == f"Release TeeBotus {__version__}"
    assert "signal_slot=Depressionsbot/default status=broken error=bad" in sent[0].data.decode("utf-8")
    assert account_store.read_status_outbox(account_id)[0]["status"] == "sent"


def test_runtime_status_admin_notify_numbers_status_summaries_per_account(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)

    async def notify_once(error: str) -> None:
        await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output=f"telegram_slot=Depressionsbot/default status=broken error={error}",
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=lambda _instance, _store: {"telegram": lambda _route, _action, _metadata: "ok"},
            now=datetime(2026, 6, 19, 12, tzinfo=timezone.utc),
        )

    asyncio.run(notify_once("first"))
    asyncio.run(notify_once("second"))

    outbox = account_store.read_status_outbox(account_id)
    assert [row["summary_prefix"] for row in outbox] == [f"v{__version__} #0001", f"v{__version__} #0002"]


def test_runtime_status_admin_notify_includes_status_auth_recipients_when_admin_ids_are_set(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    admin_identity = telegram_identity_key(111)
    status_identity = telegram_identity_key(222)
    admin_account_id = account_store.resolve_or_create_account(admin_identity)
    status_account_id = account_store.resolve_or_create_account(status_identity)
    account_store.update_identity_route(admin_identity, channel="telegram", chat_id="111", chat_type="private", adapter_slot=1)
    account_store.update_identity_route(status_identity, channel="telegram", chat_id="222", chat_type="private", adapter_slot=1)
    account_store.write_status_auth_state(
        status_account_id,
        {
            "schema_version": 1,
            "authorized": True,
            "authorized_at": "2026-06-19T12:00:00+00:00",
            "source": "runtime_code",
        },
    )

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: admin_account_id},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=lambda _instance, _store: {"telegram": lambda _route, _action, _metadata: "ok"},
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert lines == (
        f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={admin_account_id} channel=telegram",
        f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={status_account_id} channel=telegram",
    )
    assert len(account_store.read_status_outbox(admin_account_id)) == 1
    assert len(account_store.read_status_outbox(status_account_id)) == 1


def test_runtime_status_admin_notify_skips_opted_out_configured_admin(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    account_store.write_status_auth_state(
        account_id,
        {
            "schema_version": 1,
            "authorized": False,
            "admin_opt_out": True,
            "updated_at": "2026-06-19T12:00:00+00:00",
            "source": "runtime_admin_command",
        },
    )

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=lambda _instance, _store: {"telegram": lambda _route, _action, _metadata: "ok"},
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert lines == ()
    assert account_store.read_status_outbox(account_id) == []


def test_runtime_status_admin_notify_builds_only_required_sender_channels(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    requested_channels: list[tuple[str, ...]] = []

    def fake_runtime_sender_factory(_instances_dir: Path, _env: dict[str, str], *, channels: tuple[str, ...]):
        requested_channels.append(channels)
        return lambda _instance, _store: {"telegram": lambda _route, _action, _metadata: "ok"}

    monkeypatch.setattr("TeeBotus.runtime.admin_accounts._runtime_sender_factory", fake_runtime_sender_factory)

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=lambda _root, _instance: account_store,
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert requested_channels == [("telegram",)]
    assert lines == (f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={account_id} channel=telegram",)


def test_runtime_status_admin_notify_isolates_sender_failures_by_channel(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    telegram_identity = telegram_identity_key(123)
    telegram_account_id = account_store.resolve_or_create_account(telegram_identity)
    account_store.update_identity_route(telegram_identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    signal_identity = signal_identity_key(source_uuid="signal-admin")
    signal_account_id = account_store.resolve_or_create_account(signal_identity)
    account_store.update_identity_route(signal_identity, channel="signal", chat_id="+49123", chat_type="private", adapter_slot=1)
    requested_channels: list[tuple[str, ...]] = []
    sent: list[SendText] = []

    def fake_runtime_sender_factory(_instances_dir: Path, _env: dict[str, str], *, channels: tuple[str, ...]):
        requested_channels.append(channels)
        if channels == ("signal",):
            raise RuntimeError("signal unavailable")
        if channels != ("telegram",):
            raise AssertionError(f"unexpected channel bundle: {channels}")
        return lambda _instance, _store: {"telegram": lambda _route, action, _metadata: sent.append(action) or "ok"}

    monkeypatch.setattr("TeeBotus.runtime.admin_accounts._runtime_sender_factory", fake_runtime_sender_factory)

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: f"{telegram_account_id},{signal_account_id}"},
            store_factory=lambda _root, _instance: account_store,
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert requested_channels == [("telegram",), ("signal",)]
    assert len(sent) == 1
    assert sent[0].chat_id == "123"
    assert f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={telegram_account_id} channel=telegram" in lines
    assert f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=failed account_id={signal_account_id} channel=signal reason=sender_factory:RuntimeError" in lines


def test_runtime_status_admin_notify_isolates_status_outbox_update_failure(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    first_identity = telegram_identity_key(123)
    first_account_id = account_store.resolve_or_create_account(first_identity)
    account_store.update_identity_route(first_identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    second_identity = telegram_identity_key(456)
    second_account_id = account_store.resolve_or_create_account(second_identity)
    account_store.update_identity_route(second_identity, channel="telegram", chat_id="456", chat_type="private", adapter_slot=1)
    original_write_status_outbox = account_store.write_status_outbox
    write_calls = 0
    sent: list[str] = []

    def flaky_write_status_outbox(account_id: str, rows: list[dict[str, object]]) -> None:
        nonlocal write_calls
        write_calls += 1
        if write_calls > 2:
            raise OSError("status outbox unavailable")
        original_write_status_outbox(account_id, rows)

    monkeypatch.setattr(account_store, "write_status_outbox", flaky_write_status_outbox)

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: f"{first_account_id},{second_account_id}"},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=lambda _instance, _store: {
                "telegram": lambda route, _action, _metadata: sent.append(str(route["chat_id"])) or "ok"
            },
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert sent == ["123", "456"]
    assert f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={first_account_id} channel=telegram" in lines
    assert f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={second_account_id} channel=telegram" in lines


def test_runtime_status_admin_notify_handles_broken_sender_factory_return_value(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=lambda _instance, _store: object(),
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert lines == (f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=failed account_id={account_id} channel=telegram reason=sender_factory:AttributeError",)


def test_runtime_status_admin_notify_treats_non_callable_sender_as_failure(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=lambda _instance, _store: {"telegram": 42},
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert lines == (f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=failed account_id={account_id} channel=telegram reason=sender_factory:non_callable",)


def test_runtime_status_admin_notify_handles_sender_keys_without_case_sensitivity(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    sent: list[SendAttachment] = []

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=lambda _instance, _store: {"Telegram": lambda _route, action, _metadata: sent.append(action) or "ok"},
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert lines == (f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={account_id} channel=telegram",)
    assert len(sent) == 1


def test_runtime_status_admin_notify_handles_broken_default_runtime_sender_factory(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)

    def broken_runtime_sender_factory(_instances_dir: Path, _env: dict[str, str], *, channels: tuple[str, ...]):
        return lambda _instance, _store: {"telegram": 42}

    monkeypatch.setattr("TeeBotus.runtime.admin_accounts._runtime_sender_factory", broken_runtime_sender_factory)

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: account_id},
            store_factory=lambda _root, _instance: account_store,
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert lines == (f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=failed account_id={account_id} channel=telegram reason=sender_factory:non_callable",)


def test_runtime_status_admin_notify_calls_injected_sender_factory_once_per_instance(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    telegram_identity = telegram_identity_key(123)
    telegram_account_id = account_store.resolve_or_create_account(telegram_identity)
    account_store.update_identity_route(telegram_identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    signal_identity = signal_identity_key(source_uuid="signal-admin")
    signal_account_id = account_store.resolve_or_create_account(signal_identity)
    account_store.update_identity_route(signal_identity, channel="signal", chat_id="+49123", chat_type="private", adapter_slot=1)
    calls: list[str] = []

    def sender_factory(instance: str, _store: AccountStore):
        calls.append(instance)
        return {
            "telegram": lambda _route, _action, _metadata: "telegram-ok",
            "signal": lambda _route, _action, _metadata: "signal-ok",
        }

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: f"{telegram_account_id},{signal_account_id}"},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=sender_factory,
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert calls == [STATUS_SUMMARY_INSTANCE_NAME]
    assert f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={telegram_account_id} channel=telegram" in lines
    assert f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=sent account_id={signal_account_id} channel=signal" in lines


def test_runtime_status_admin_notify_does_not_build_senders_without_local_admin(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    account_store = status_summary_store_for(instances_dir)
    called = False

    def sender_factory(_instance: str, _store: AccountStore):
        nonlocal called
        called = True
        raise AssertionError("sender factory should not run without local admin routes")

    async def run_notify() -> tuple[str, ...]:
        results = await notify_runtime_status_admin_accounts(
            instances_dir=instances_dir,
            selected_instances=("Depressionsbot",),
            status_output="telegram_slot=Depressionsbot/default status=broken error=bad",
            env={ADMIN_ACCOUNT_IDS_ENV: DEFAULT_ADMIN_ACCOUNT_IDS[0]},
            store_factory=lambda _root, _instance: account_store,
            sender_factory=sender_factory,
        )
        return format_admin_notification_result_lines(results)

    lines = asyncio.run(run_notify())

    assert called is False
    assert lines == (
        f"admin_notify={STATUS_SUMMARY_INSTANCE_NAME} status=skipped account_id={DEFAULT_ADMIN_ACCOUNT_IDS[0]} reason=not_local",
    )
