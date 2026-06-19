from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from TeeBotus.runtime.accounts import AccountStore, StaticSecretProvider, signal_identity_key, telegram_identity_key
from TeeBotus.runtime.actions import SendText
from TeeBotus.runtime.admin_accounts import (
    ADMIN_ACCOUNT_IDS_ENV,
    DEFAULT_ADMIN_ACCOUNT_IDS,
    admin_account_group_status_lines,
    format_admin_notification_result_lines,
    notify_runtime_status_admin_accounts,
    resolve_admin_account_group,
    runtime_status_problem_lines,
)


def store_for(root: Path, instance_name: str = "Depressionsbot") -> AccountStore:
    return AccountStore(root / "accounts", instance_name, StaticSecretProvider(b"a" * 32))


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
    assert f"admin_account=Depressionsbot/{account_id} status=routable channel=telegram slot=1" in lines


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


def test_runtime_status_admin_notify_sends_to_routable_admin_account(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    account_store = store_for(instance_dir / "data")
    identity = telegram_identity_key(123)
    account_id = account_store.resolve_or_create_account(identity)
    account_store.update_identity_route(identity, channel="telegram", chat_id="123", chat_type="private", adapter_slot=1)
    sent: list[tuple[dict[str, object], SendText]] = []

    def sender(route: dict[str, object], action: SendText, _metadata: dict[str, object]) -> str:
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

    assert lines == (f"admin_notify=Depressionsbot status=sent account_id={account_id} channel=telegram",)
    assert len(sent) == 1
    assert sent[0][1].chat_id == "123"
    assert "TeeBotus Runtime-Status Warnungen" in sent[0][1].text
    assert "telegram_slot=Depressionsbot/default status=broken error=bad" in sent[0][1].text


def test_runtime_status_admin_notify_builds_only_required_sender_channels(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    account_store = store_for(instance_dir / "data")
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
    assert lines == (f"admin_notify=Depressionsbot status=sent account_id={account_id} channel=telegram",)


def test_runtime_status_admin_notify_isolates_sender_failures_by_channel(tmp_path, monkeypatch) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    account_store = store_for(instance_dir / "data")
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
    assert f"admin_notify=Depressionsbot status=sent account_id={telegram_account_id} channel=telegram" in lines
    assert f"admin_notify=Depressionsbot status=failed account_id={signal_account_id} channel=signal reason=sender_factory:RuntimeError" in lines


def test_runtime_status_admin_notify_does_not_build_senders_without_local_admin(tmp_path) -> None:
    instances_dir = tmp_path / "instances"
    instance_dir = instances_dir / "Depressionsbot"
    account_store = store_for(instance_dir / "data")
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
        f"admin_notify=Depressionsbot status=skipped account_id={DEFAULT_ADMIN_ACCOUNT_IDS[0]} reason=not_local",
    )
