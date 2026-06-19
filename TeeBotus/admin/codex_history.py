from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from TeeBotus import __version__
from TeeBotus.admin.accounts_report import DEFAULT_INSTANCES_DIR, ReadOnlySecretToolInstanceSecretProvider, discover_instances, parse_csv
from TeeBotus.runtime.accounts import (
    INSTANCE_MAPPING_KEY_PURPOSE,
    INSTANCE_STATE_ACCOUNT_ID,
    AccountStore,
    AccountStoreError,
    InstanceSecretProvider,
)

CODEX_HISTORY_SCHEMA_VERSION = 1
CODEX_HISTORY_TARGET_GROUP = "status_admins"

_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")
_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{7,12}:[A-Za-z0-9_\-]{25,}\b")
_GENERIC_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|cookie)\b\s*[:=]\s*([^\s,;]{12,})"
)


@dataclass(frozen=True)
class CodexHistoryReportOptions:
    instances_dir: Path
    instances: tuple[str, ...] = ()
    repo: str = ""
    provider: InstanceSecretProvider | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_codex_history_summary(
    store: AccountStore,
    *,
    repo_root: str | Path,
    title: str,
    bullets: Sequence[str] = (),
    changed_files: Sequence[str] = (),
    tests: Sequence[str] = (),
    session_id: str = "",
    source: str = "manual_cli",
    status: str = "queued",
    target_group: str = CODEX_HISTORY_TARGET_GROUP,
) -> dict[str, Any]:
    repo = build_repo_metadata(repo_root)
    version = resolve_repo_version(repo["repo_root"])
    timestamp = utc_now()
    account_id = INSTANCE_STATE_ACCOUNT_ID
    redacted_title = redact_codex_history_text(title).strip() or "Codex run summary"
    redacted_bullets = [redact_codex_history_text(item).strip() for item in bullets if str(item or "").strip()]
    redacted_changed_files = [redact_codex_history_text(item).strip() for item in changed_files if str(item or "").strip()]
    redacted_tests = [redact_codex_history_text(item).strip() for item in tests if str(item or "").strip()]

    with store.codex_history_outbox_lock(account_id):
        rows = store.read_codex_history_outbox(account_id)
        summary_number = _next_summary_number_for_repo(rows, repo["repo_id"])
        summary_prefix = _summary_prefix(version["semver"], summary_number)
        markdown = build_codex_history_markdown(
            summary_prefix=summary_prefix,
            title=redacted_title,
            repo=repo,
            version=version,
            bullets=redacted_bullets,
            changed_files=redacted_changed_files,
            tests=redacted_tests,
            created_at=timestamp,
        )
        item = {
            "id": _unique_history_id(rows),
            "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
            "kind": "codex_run_summary",
            "source": source,
            "status": status,
            "created_at": timestamp,
            "updated_at": timestamp,
            "project": repo,
            "version": {
                "semver": version["semver"],
                "tag": version["tag"],
                "summary_number": summary_number,
                "summary_prefix": summary_prefix,
            },
            "codex": {
                "session_id": redact_codex_history_text(session_id).strip(),
                "cwd": repo["repo_root"],
                "finished_at": timestamp,
            },
            "summary": {
                "title": redacted_title,
                "markdown": markdown,
                "bullets": redacted_bullets,
                "changed_files": redacted_changed_files,
                "tests": redacted_tests,
            },
            "delivery": {
                "target_group": target_group,
                "attempts": 0,
                "last_attempt_at": "",
                "sent_at": "",
                "accepted_at": "",
                "delivered_at": "",
                "acknowledged_at": "",
            },
            "indexing": {
                "indexable": True,
                "repo_history": True,
                "keywords": _history_keywords(repo, version, redacted_title, redacted_bullets, redacted_changed_files, redacted_tests),
            },
            "status_history": [
                {
                    "at": timestamp,
                    "status": status,
                    "reason": "codex_history_summary_created",
                }
            ],
            "summary_number": summary_number,
            "summary_prefix": summary_prefix,
        }
        rows.append(item)
        store.write_codex_history_outbox(account_id, rows)
        _upsert_project(store, account_id, repo, item, timestamp)
        return dict(item)


def build_repo_metadata(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    git_root = _git_output(root, "rev-parse", "--show-toplevel")
    if git_root:
        root = Path(git_root).resolve()
    remote_url = _git_output(root, "remote", "get-url", "origin")
    branch = _git_output(root, "rev-parse", "--abbrev-ref", "HEAD")
    head_commit = _git_output(root, "rev-parse", "HEAD")
    status = _git_output(root, "status", "--porcelain")
    repo_name = _repo_name(root, remote_url)
    identity = _normalize_remote_url(remote_url) or str(root)
    return {
        "repo_id": "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "repo_name": repo_name,
        "repo_root": str(root),
        "remote_url": remote_url,
        "provider": _repo_provider(remote_url),
        "branch": branch,
        "head_commit": head_commit,
        "dirty": bool(status.strip()),
    }


def resolve_repo_version(repo_root: str | Path) -> dict[str, str]:
    root = Path(repo_root).expanduser().resolve()
    semver = _pyproject_version(root) or _version_file(root) or _git_latest_semver_tag(root) or _teebotus_version(root) or "untagged"
    tag = semver if semver.startswith("v") or semver == "untagged" else f"v{semver}"
    return {"semver": semver.removeprefix("v") if semver != "untagged" else semver, "tag": tag}


def redact_codex_history_text(value: object) -> str:
    text = str(value or "")
    text = _OPENAI_KEY_RE.sub("<redacted:openai-key>", text)
    text = _TELEGRAM_TOKEN_RE.sub("<redacted:telegram-token>", text)
    text = _GENERIC_SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted:secret>", text)
    return text


def build_codex_history_markdown(
    *,
    summary_prefix: str,
    title: str,
    repo: Mapping[str, Any],
    version: Mapping[str, str],
    bullets: Sequence[str],
    changed_files: Sequence[str],
    tests: Sequence[str],
    created_at: str,
) -> str:
    lines = [
        f"# {summary_prefix} {title}",
        "",
        f"- Projekt: `{repo.get('repo_name', '')}`",
        f"- Repo: `{repo.get('repo_root', '')}`",
        f"- Version: `{version.get('tag', '')}`",
        f"- Commit: `{repo.get('head_commit', '') or '<none>'}`",
        f"- Branch: `{repo.get('branch', '') or '<none>'}`",
        f"- Erstellt: `{created_at}`",
        "",
        "## Zusammenfassung",
    ]
    if bullets:
        lines.extend(f"- {bullet}" for bullet in bullets)
    else:
        lines.append("- Keine Detailpunkte angegeben.")
    lines.append("")
    lines.append("## Geaenderte Dateien")
    if changed_files:
        lines.extend(f"- `{path}`" for path in changed_files)
    else:
        lines.append("- Keine Dateien angegeben.")
    lines.append("")
    lines.append("## Verifikation")
    if tests:
        lines.extend(f"- `{test}`" for test in tests)
    else:
        lines.append("- Keine Tests angegeben.")
    lines.append("")
    return "\n".join(lines)


def build_codex_history_report(
    *,
    instances_dir: str | Path = DEFAULT_INSTANCES_DIR,
    instances: Sequence[str] = (),
    repo: str = "",
    provider: InstanceSecretProvider | None = None,
) -> dict[str, Any]:
    options = CodexHistoryReportOptions(
        instances_dir=Path(instances_dir),
        instances=tuple(instances),
        repo=str(repo or "").strip(),
        provider=provider or ReadOnlySecretToolInstanceSecretProvider(),
    )
    selected_instances = discover_instances(options.instances_dir, options.instances)
    report: dict[str, Any] = {
        "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
        "scope": "codex_history",
        "generated_at": utc_now(),
        "instances_dir": str(options.instances_dir),
        "instance_count": len(selected_instances),
        "instances": [],
        "totals": {
            "projects": 0,
            "outbox_items": 0,
            "dispatch_results": 0,
            "store_errors": 0,
        },
    }
    for instance_name in selected_instances:
        instance_report = build_instance_codex_history_report(
            instances_dir=options.instances_dir,
            instance_name=instance_name,
            provider=options.provider,
            repo=options.repo,
        )
        report["instances"].append(instance_report)
        _add_totals(report["totals"], instance_report)
    return report


def build_instance_codex_history_report(
    *,
    instances_dir: Path,
    instance_name: str,
    provider: InstanceSecretProvider,
    repo: str = "",
) -> dict[str, Any]:
    accounts_root = instances_dir / instance_name / "data" / "accounts"
    store = AccountStore(
        accounts_root,
        instance_name,
        secret_provider=provider,
        create_dirs=False,
        secret_guard_purposes=(INSTANCE_MAPPING_KEY_PURPOSE,),
    )
    codex_history: dict[str, Any] = {
        "projects": [],
        "outbox_items": 0,
        "dispatch_results": 0,
        "outbox_status_counts": {},
        "dispatch_status_counts": {},
        "latest_by_repo": [],
        "errors": [],
    }
    try:
        projects = _filter_projects(store.read_codex_history_projects(INSTANCE_STATE_ACCOUNT_ID), repo)
        outbox = _filter_outbox(store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID), repo)
        dispatch_results = store.read_codex_history_dispatch_results(INSTANCE_STATE_ACCOUNT_ID)
    except (AccountStoreError, OSError, ValueError) as exc:
        codex_history["errors"].append(f"{type(exc).__name__}:{exc}")
        projects = []
        outbox = []
        dispatch_results = []
    codex_history["projects"] = projects
    codex_history["outbox_items"] = len(outbox)
    codex_history["dispatch_results"] = len(dispatch_results)
    codex_history["outbox_status_counts"] = _status_counts(outbox)
    codex_history["dispatch_status_counts"] = _status_counts(dispatch_results)
    codex_history["latest_by_repo"] = _latest_by_repo(outbox)
    return {
        "instance": instance_name,
        "accounts_root": str(accounts_root),
        "accounts_root_exists": accounts_root.exists(),
        "codex_history": codex_history,
    }


def render_text_report(report: Mapping[str, Any]) -> str:
    lines = [
        "TeeBotus Codex-History Report",
        "",
        f"generated_at: {report.get('generated_at', '')}",
        f"instances_dir: {report.get('instances_dir', '')}",
        "",
        "Totals:",
    ]
    totals = report.get("totals", {})
    if isinstance(totals, Mapping):
        for key in sorted(totals):
            lines.append(f"  {key}: {totals[key]}")
    for instance in report.get("instances", []):
        if not isinstance(instance, Mapping):
            continue
        history = instance.get("codex_history", {})
        if not isinstance(history, Mapping):
            history = {}
        lines.extend(["", f"Instance: {instance.get('instance', '')}"])
        lines.append(f"  projects: {len(history.get('projects', []) or [])}")
        lines.append(f"  outbox_items: {history.get('outbox_items', 0)}")
        lines.append(f"  dispatch_results: {history.get('dispatch_results', 0)}")
        for item in history.get("latest_by_repo", []):
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "  latest: "
                f"{item.get('repo_name', '')} {item.get('summary_prefix', '')} "
                f"status={item.get('status', '')} title={item.get('title', '')}"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, provider: InstanceSecretProvider | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m TeeBotus.admin codex-history")
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    append_parser.add_argument("--instance", required=True)
    append_parser.add_argument("--repo-root", required=True)
    append_parser.add_argument("--title", default="Codex run summary")
    append_parser.add_argument("--bullet", action="append", default=[])
    append_parser.add_argument("--changed-file", action="append", default=[])
    append_parser.add_argument("--test", action="append", default=[])
    append_parser.add_argument("--session-id", default="")
    append_parser.add_argument("--source", default="manual_cli")
    append_parser.add_argument("--format", choices=("text", "json"), default="text")
    append_parser.add_argument("--output", default="")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--instances-dir", default=DEFAULT_INSTANCES_DIR)
    report_parser.add_argument("--instances", default="")
    report_parser.add_argument("--repo", default="")
    report_parser.add_argument("--format", choices=("text", "json"), default="text")
    report_parser.add_argument("--output", default="")

    dispatch_parser = subparsers.add_parser("dispatch")
    dispatch_parser.add_argument("--format", choices=("text", "json"), default="text")
    dispatch_parser.add_argument("--dry-run", action="store_true")

    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("--format", choices=("text", "json"), default="text")
    watch_parser.add_argument("--once", action="store_true")

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "append":
        store = _store_for_instance(Path(args.instances_dir), args.instance, provider)
        item = append_codex_history_summary(
            store,
            repo_root=args.repo_root,
            title=args.title,
            bullets=tuple(args.bullet or ()),
            changed_files=tuple(args.changed_file or ()),
            tests=tuple(args.test or ()),
            session_id=args.session_id,
            source=args.source,
        )
        output_payload = {"ok": True, "item": item}
        output = (
            json.dumps(output_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if args.format == "json"
            else f"queued {item['summary_prefix']} {item['project']['repo_name']} {item['id']}\n"
        )
        _write_or_print(output, args.output)
        return 0
    if args.command == "report":
        report = build_codex_history_report(
            instances_dir=args.instances_dir,
            instances=parse_csv(getattr(args, "instances", None)),
            repo=args.repo,
            provider=provider,
        )
        output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if args.format == "json" else render_text_report(report)
        _write_or_print(output, args.output)
        return 0
    if args.command in {"dispatch", "watch"}:
        payload = {
            "ok": False,
            "status": "not_implemented",
            "command": args.command,
            "message": "Codex history storage/reporting is implemented; dispatch/watch will be wired in a later phase.",
        }
        output = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" if args.format == "json" else payload["message"] + "\n"
        print(output, end="")
        return 2
    parser.error("unknown command")
    return 2


def _store_for_instance(instances_dir: Path, instance_name: str, provider: InstanceSecretProvider | None) -> AccountStore:
    return AccountStore(
        instances_dir / instance_name / "data" / "accounts",
        instance_name,
        secret_provider=provider or ReadOnlySecretToolInstanceSecretProvider(),
        create_dirs=True,
    )


def _write_or_print(output: str, output_path: str) -> None:
    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
    else:
        print(output, end="")


def _git_output(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, ValueError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _repo_name(root: Path, remote_url: str) -> str:
    if remote_url:
        name = remote_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        if ":" in name:
            name = name.rsplit(":", 1)[-1].removesuffix(".git")
        if name:
            return name
    return root.name


def _normalize_remote_url(remote_url: str) -> str:
    value = str(remote_url or "").strip()
    if not value:
        return ""
    value = value.removesuffix(".git")
    value = re.sub(r"^git@", "ssh://git@", value)
    return value.casefold()


def _repo_provider(remote_url: str) -> str:
    value = remote_url.casefold()
    if "github.com" in value:
        return "github"
    if value:
        return "git"
    return "local"


def _pyproject_version(root: Path) -> str:
    path = root / "pyproject.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return ""
    project = data.get("project", {})
    if not isinstance(project, Mapping):
        return ""
    return str(project.get("version") or "").strip()


def _version_file(root: Path) -> str:
    try:
        return (root / "VERSION").read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return ""


def _git_latest_semver_tag(root: Path) -> str:
    tag = _git_output(root, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*")
    if re.match(r"^v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?$", tag):
        return tag
    return ""


def _teebotus_version(root: Path) -> str:
    package_root = Path(__file__).resolve().parents[2]
    try:
        if root.resolve() == package_root:
            return __version__
    except OSError:
        return ""
    return ""


def _next_summary_number_for_repo(rows: Sequence[Mapping[str, Any]], repo_id: str) -> int:
    highest = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        project = row.get("project", {})
        if not isinstance(project, Mapping) or project.get("repo_id") != repo_id:
            continue
        try:
            number = int(row.get("summary_number") or row.get("version", {}).get("summary_number") or 0)  # type: ignore[union-attr]
        except (TypeError, ValueError, AttributeError):
            number = 0
        highest = max(highest, number)
    return highest + 1


def _summary_prefix(semver: str, summary_number: int) -> str:
    version = str(semver or "").strip() or "untagged"
    prefix = "untagged" if version == "untagged" else f"v{version.removeprefix('v')}"
    return f"{prefix} #{max(1, int(summary_number)):04d}"


def _unique_history_id(rows: Sequence[Mapping[str, Any]]) -> str:
    existing_ids = {str(row.get("id", "")).strip() for row in rows if isinstance(row, Mapping)}
    item_id = f"hist_{uuid.uuid4().hex}"
    while item_id in existing_ids:
        item_id = f"hist_{uuid.uuid4().hex}"
    return item_id


def _history_keywords(
    repo: Mapping[str, Any],
    version: Mapping[str, str],
    title: str,
    bullets: Sequence[str],
    changed_files: Sequence[str],
    tests: Sequence[str],
) -> list[str]:
    words: set[str] = {
        "codex",
        "history",
        "outbox",
        str(repo.get("repo_name") or "").casefold(),
        str(version.get("tag") or "").casefold(),
    }
    for value in (title, *bullets, *changed_files, *tests):
        for token in re.findall(r"[A-Za-z0-9_.-]{3,}", value):
            words.add(token.casefold())
    return sorted(word for word in words if word)


def _upsert_project(store: AccountStore, account_id: str, repo: Mapping[str, Any], item: Mapping[str, Any], timestamp: str) -> None:
    projects = store.read_codex_history_projects(account_id)
    repo_id = str(repo.get("repo_id") or "")
    normalized = dict(repo)
    normalized.update(
        {
            "schema_version": CODEX_HISTORY_SCHEMA_VERSION,
            "updated_at": timestamp,
            "last_summary_id": item.get("id", ""),
            "last_summary_prefix": item.get("summary_prefix", ""),
            "last_summary_at": timestamp,
        }
    )
    replaced = False
    for index, project in enumerate(projects):
        if isinstance(project, Mapping) and project.get("repo_id") == repo_id:
            summary_count = int(project.get("summary_count") or 0) + 1
            normalized["created_at"] = project.get("created_at") or timestamp
            normalized["summary_count"] = summary_count
            projects[index] = normalized
            replaced = True
            break
    if not replaced:
        normalized["created_at"] = timestamp
        normalized["summary_count"] = 1
        projects.append(normalized)
    store.write_codex_history_projects(account_id, projects)


def _filter_projects(projects: Sequence[Mapping[str, Any]], repo: str) -> list[dict[str, Any]]:
    needle = repo.strip().casefold()
    result = []
    for project in projects:
        if not isinstance(project, Mapping):
            continue
        if needle and needle not in str(project.get("repo_name") or "").casefold() and needle not in str(project.get("repo_id") or "").casefold():
            continue
        result.append(dict(project))
    return result


def _filter_outbox(rows: Sequence[Mapping[str, Any]], repo: str) -> list[dict[str, Any]]:
    needle = repo.strip().casefold()
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        project = row.get("project", {})
        if not isinstance(project, Mapping):
            project = {}
        if needle and needle not in str(project.get("repo_name") or "").casefold() and needle not in str(project.get("repo_id") or "").casefold():
            continue
        result.append(dict(row))
    return result


def _status_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "unknown").strip().casefold() or "unknown"
        counts[status] += 1
    return dict(sorted(counts.items()))


def _latest_by_repo(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        project = row.get("project", {})
        if not isinstance(project, Mapping):
            continue
        repo_id = str(project.get("repo_id") or "")
        if not repo_id:
            continue
        previous = latest.get(repo_id)
        if previous is None or str(row.get("created_at") or "") >= str(previous.get("created_at") or ""):
            latest[repo_id] = row
    result = []
    for row in latest.values():
        project = row.get("project", {})
        summary = row.get("summary", {})
        if not isinstance(project, Mapping):
            project = {}
        if not isinstance(summary, Mapping):
            summary = {}
        result.append(
            {
                "repo_id": project.get("repo_id", ""),
                "repo_name": project.get("repo_name", ""),
                "summary_prefix": row.get("summary_prefix", ""),
                "status": row.get("status", ""),
                "title": summary.get("title", ""),
                "created_at": row.get("created_at", ""),
            }
        )
    return sorted(result, key=lambda item: (str(item.get("repo_name") or ""), str(item.get("created_at") or "")))


def _add_totals(totals: dict[str, int], instance_report: Mapping[str, Any]) -> None:
    history = instance_report.get("codex_history", {})
    if not isinstance(history, Mapping):
        return
    totals["projects"] += len(history.get("projects", []) or [])
    totals["outbox_items"] += int(history.get("outbox_items", 0) or 0)
    totals["dispatch_results"] += int(history.get("dispatch_results", 0) or 0)
    if history.get("errors"):
        totals["store_errors"] += 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
