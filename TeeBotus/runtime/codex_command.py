from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from TeeBotus.runtime.accounts import INSTANCE_STATE_ACCOUNT_ID, AccountStore, AccountStoreError

CODEX_COMMAND = "/codex"
CODEX_OUTPUT_LIMIT = 3600


@dataclass(frozen=True)
class CodexCommandRequest:
    prompt: str
    project_filter: str = ""
    repo_filter: str = ""


@dataclass(frozen=True)
class CodexSessionTarget:
    session_id: str
    codex_home: str
    repo_root: str
    repo_name: str = ""
    session_path: str = ""
    source: str = ""


@dataclass(frozen=True)
class CodexCommandResult:
    status: str
    text: str = ""
    error: str = ""
    target: CodexSessionTarget | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class _CodexHistoryTarget:
    session_id: str
    repo_root: str
    repo_name: str
    created_at: str
    updated_at: str
    item_id: str


@dataclass(frozen=True)
class _CodexSessionInfo:
    session_id: str
    cwd: str
    codex_home: str
    path: Path
    mtime: float


Runner = Callable[..., subprocess.CompletedProcess[str]]


def execute_codex_admin_command(
    account_store: AccountStore,
    *,
    instance_name: str,
    text: str,
    project_root: str | Path,
    timeout_seconds: int = 300,
    session_roots: Sequence[str | Path] | None = None,
    runner: Runner | None = None,
    executable: str = "codex",
) -> CodexCommandResult:
    request = parse_codex_admin_command(text, _known_targets(account_store, session_roots=session_roots))
    if request is None:
        return CodexCommandResult("ignored")
    if not request.prompt:
        return CodexCommandResult("usage")
    if shutil.which(executable) is None:
        return CodexCommandResult("not_found")
    try:
        target = resolve_codex_session_target(
            account_store,
            project_root=project_root,
            project_filter=request.project_filter,
            repo_filter=request.repo_filter,
            session_roots=session_roots,
        )
    except (AccountStoreError, OSError, ValueError) as exc:
        return CodexCommandResult("error", error=f"{type(exc).__name__}: {exc}")
    if target is None:
        return CodexCommandResult("no_session", error="Keine passende Codex-Session gefunden.")
    try:
        output = _run_codex_resume(
            target,
            request.prompt,
            timeout_seconds=max(1, int(timeout_seconds or 300)),
            runner=runner or subprocess.run,
            executable=executable,
        )
    except subprocess.TimeoutExpired:
        return CodexCommandResult("error", error=f"Timeout nach {max(1, int(timeout_seconds or 300))}s", target=target)
    except OSError as exc:
        return CodexCommandResult("error", error=str(exc), target=target)
    if output.returncode != 0:
        return CodexCommandResult("error", error=_short_process_error(output), target=target)
    response_text = (output.stdout or "").strip() or (output.stderr or "").strip()
    if not response_text:
        return CodexCommandResult("empty", target=target)
    return CodexCommandResult("ok", text=_format_codex_response(response_text, target), target=target)


def parse_codex_admin_command(text: str, known_targets: Sequence[tuple[str, str]] = ()) -> CodexCommandRequest | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    parts = raw.split(maxsplit=1)
    command = parts[0].casefold()
    if "@" in command:
        command = command.split("@", maxsplit=1)[0]
    if command != CODEX_COMMAND:
        return None
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not rest:
        return CodexCommandRequest(prompt="")
    bracket_match = re.match(r"^\[(?P<project>[^\]]*)\]\s+\[(?P<repo>[^\]]*)\]\s+(?P<prompt>.+)$", rest, re.DOTALL)
    if bracket_match:
        return CodexCommandRequest(
            prompt=bracket_match.group("prompt").strip(),
            project_filter=bracket_match.group("project").strip(),
            repo_filter=bracket_match.group("repo").strip(),
        )
    key_value = _parse_key_value_codex_request(rest)
    if key_value is not None:
        return key_value
    positional = _parse_positional_codex_request(rest, known_targets)
    if positional is not None:
        return positional
    return CodexCommandRequest(prompt=rest)


def resolve_codex_session_target(
    account_store: AccountStore,
    *,
    project_root: str | Path,
    project_filter: str = "",
    repo_filter: str = "",
    session_roots: Sequence[str | Path] | None = None,
) -> CodexSessionTarget | None:
    history_target = _latest_history_target(account_store, project_filter=project_filter, repo_filter=repo_filter)
    repo_root = history_target.repo_root if history_target and history_target.repo_root else str(project_root)
    repo_name = history_target.repo_name if history_target and history_target.repo_name else Path(repo_root).name
    sessions = _discover_codex_sessions(session_roots)
    session = _latest_session_for_repo(sessions, repo_root)
    if session is None and history_target and history_target.session_id:
        session = _session_by_id(sessions, history_target.session_id)
    if session is None and (project_filter or repo_filter):
        session = _latest_session_matching_filters(sessions, project_filter=project_filter, repo_filter=repo_filter)
        if session is not None:
            repo_root = session.cwd
            repo_name = Path(session.cwd).name
    if session is None:
        return None
    return CodexSessionTarget(
        session_id=session.session_id,
        codex_home=session.codex_home,
        repo_root=session.cwd or repo_root,
        repo_name=repo_name or Path(session.cwd).name,
        session_path=str(session.path),
        source="session_log",
    )


def default_codex_session_roots(home: str | Path | None = None) -> tuple[Path, ...]:
    base = Path(home).expanduser() if home is not None else Path.home()
    roots: list[Path] = []
    main_root = base / ".codex" / "sessions"
    if main_root.is_dir():
        roots.append(main_root)
    agents_root = base / ".codex-agents"
    if agents_root.is_dir():
        for child in sorted(agents_root.iterdir(), key=lambda path: path.name):
            sessions = child / "sessions"
            if sessions.is_dir():
                roots.append(sessions)
    return tuple(roots)


def _parse_key_value_codex_request(rest: str) -> CodexCommandRequest | None:
    try:
        tokens = shlex.split(rest)
    except ValueError:
        return None
    if len(tokens) < 2:
        return None
    project_filter = ""
    repo_filter = ""
    prompt_tokens: list[str] = []
    consumed_key = False
    for token in tokens:
        if "=" in token and not prompt_tokens:
            key, value = token.split("=", 1)
            normalized = key.strip().casefold()
            if normalized in {"project", "projekt"}:
                project_filter = value.strip()
                consumed_key = True
                continue
            if normalized in {"repo", "repository"}:
                repo_filter = value.strip()
                consumed_key = True
                continue
        prompt_tokens.append(token)
    if not consumed_key:
        return None
    return CodexCommandRequest(prompt=" ".join(prompt_tokens).strip(), project_filter=project_filter, repo_filter=repo_filter)


def _parse_positional_codex_request(rest: str, known_targets: Sequence[tuple[str, str]]) -> CodexCommandRequest | None:
    if not known_targets:
        return None
    try:
        tokens = shlex.split(rest)
    except ValueError:
        return None
    if len(tokens) < 3:
        return None
    project_filter, repo_filter = tokens[0].strip(), tokens[1].strip()
    if not _known_target_matches(project_filter, repo_filter, known_targets):
        return None
    return CodexCommandRequest(prompt=" ".join(tokens[2:]).strip(), project_filter=project_filter, repo_filter=repo_filter)


def _known_target_matches(project_filter: str, repo_filter: str, known_targets: Sequence[tuple[str, str]]) -> bool:
    project = project_filter.casefold()
    repo = repo_filter.casefold()
    for known_project, known_repo in known_targets:
        if project == known_project.casefold() and repo in _repo_aliases(known_repo):
            return True
    return False


def _repo_aliases(repo: str) -> set[str]:
    text = str(repo or "").strip()
    aliases = {text.casefold()}
    if text:
        path_name = Path(text).name
        if path_name:
            aliases.add(path_name.casefold())
    return aliases


def _known_targets(account_store: AccountStore, *, session_roots: Sequence[str | Path] | None) -> tuple[tuple[str, str], ...]:
    targets: list[tuple[str, str]] = []
    try:
        for row in account_store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID):
            if not isinstance(row, Mapping):
                continue
            project = row.get("project", {})
            if not isinstance(project, Mapping):
                continue
            repo_name = str(project.get("repo_name") or "").strip()
            repo_root = str(project.get("repo_root") or "").strip()
            if repo_name and repo_root:
                targets.append((repo_name, repo_root))
    except (AccountStoreError, OSError, ValueError):
        pass
    for session in _discover_codex_sessions(session_roots):
        if session.cwd:
            targets.append((Path(session.cwd).name, session.cwd))
    return tuple(dict.fromkeys(targets))


def _latest_history_target(account_store: AccountStore, *, project_filter: str, repo_filter: str) -> _CodexHistoryTarget | None:
    candidates: list[_CodexHistoryTarget] = []
    for row in account_store.read_codex_history_outbox(INSTANCE_STATE_ACCOUNT_ID):
        if not isinstance(row, Mapping):
            continue
        project = row.get("project", {})
        codex = row.get("codex", {})
        if not isinstance(project, Mapping):
            project = {}
        if not isinstance(codex, Mapping):
            codex = {}
        if not _history_project_matches(project, project_filter=project_filter, repo_filter=repo_filter):
            continue
        candidates.append(
            _CodexHistoryTarget(
                session_id=str(codex.get("session_id") or "").strip(),
                repo_root=str(project.get("repo_root") or "").strip(),
                repo_name=str(project.get("repo_name") or "").strip(),
                created_at=str(row.get("created_at") or "").strip(),
                updated_at=str(row.get("updated_at") or "").strip(),
                item_id=str(row.get("id") or "").strip(),
            )
        )
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (_timestamp_sort_key(item.updated_at or item.created_at), item.item_id))[-1]


def _history_project_matches(project: Mapping[str, Any], *, project_filter: str, repo_filter: str) -> bool:
    if project_filter and not _matches_any(project_filter, (project.get("repo_name", ""), project.get("repo_root", ""), project.get("remote_url", ""))):
        return False
    if repo_filter and not _matches_any(repo_filter, (project.get("repo_name", ""), project.get("repo_root", ""), project.get("remote_url", ""), project.get("repo_id", ""))):
        return False
    return True


def _matches_any(needle: str, values: Sequence[object]) -> bool:
    normalized = str(needle or "").strip().casefold()
    if not normalized:
        return True
    return any(normalized in str(value or "").casefold() for value in values)


def _discover_codex_sessions(session_roots: Sequence[str | Path] | None) -> tuple[_CodexSessionInfo, ...]:
    roots = tuple(Path(root).expanduser() for root in session_roots) if session_roots is not None else default_codex_session_roots()
    sessions: list[_CodexSessionInfo] = []
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else sorted(root.rglob("*.jsonl"))
        for path in files:
            info = _read_codex_session_info(path)
            if info is not None:
                sessions.append(info)
    return tuple(sessions)


def _read_codex_session_info(path: Path) -> _CodexSessionInfo | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    session_id = ""
    cwd = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index > 80:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, Mapping):
                    continue
                payload = event.get("payload", {})
                if not isinstance(payload, Mapping):
                    continue
                if event.get("type") == "session_meta":
                    session_id = str(payload.get("id") or session_id).strip()
                    cwd = str(payload.get("cwd") or cwd).strip()
                elif event.get("type") == "turn_context":
                    cwd = str(payload.get("cwd") or cwd).strip()
                if session_id and cwd:
                    break
    except OSError:
        return None
    if not session_id:
        match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", path.name)
        session_id = match.group(1) if match else ""
    if not session_id:
        return None
    return _CodexSessionInfo(session_id=session_id, cwd=cwd, codex_home=str(_codex_home_for_session_file(path)), path=path, mtime=stat.st_mtime)


def _codex_home_for_session_file(path: Path) -> Path:
    parts = path.resolve().parts
    if "sessions" in parts:
        index = parts.index("sessions")
        if index > 0:
            return Path(*parts[:index])
    return path.parent


def _latest_session_for_repo(sessions: Sequence[_CodexSessionInfo], repo_root: str) -> _CodexSessionInfo | None:
    normalized_repo = _normalized_path(repo_root)
    matches = [session for session in sessions if normalized_repo and _normalized_path(session.cwd) == normalized_repo]
    if not matches:
        return None
    return sorted(matches, key=lambda session: (session.mtime, session.path.as_posix()))[-1]


def _latest_session_matching_filters(
    sessions: Sequence[_CodexSessionInfo],
    *,
    project_filter: str,
    repo_filter: str,
) -> _CodexSessionInfo | None:
    matches = [
        session
        for session in sessions
        if _matches_any(project_filter, (Path(session.cwd).name, session.cwd))
        and _matches_any(repo_filter, (Path(session.cwd).name, session.cwd))
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda session: (session.mtime, session.path.as_posix()))[-1]


def _session_by_id(sessions: Sequence[_CodexSessionInfo], session_id: str) -> _CodexSessionInfo | None:
    normalized = str(session_id or "").strip()
    if not normalized:
        return None
    for session in sessions:
        if session.session_id == normalized:
            return session
    return None


def _normalized_path(value: str | Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve(strict=False))
    except OSError:
        return str(Path(text).expanduser())


def _timestamp_sort_key(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _run_codex_resume(
    target: CodexSessionTarget,
    prompt: str,
    *,
    timeout_seconds: int,
    runner: Runner,
    executable: str,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if target.codex_home:
        env["CODEX_HOME"] = target.codex_home
    args = [executable, "exec", "resume", target.session_id, "-"]
    return runner(
        args,
        cwd=target.repo_root or None,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
        env=env,
    )


def _format_codex_response(output: str, target: CodexSessionTarget) -> str:
    repo = target.repo_name or Path(target.repo_root).name or target.repo_root
    header = f"Codex -> {repo}\nSession: {target.session_id}"
    body = output.strip()
    if len(body) > CODEX_OUTPUT_LIMIT:
        body = body[: CODEX_OUTPUT_LIMIT - 80].rstrip() + "\n\n[gekuerzt]"
    return f"{header}\n\n{body}".strip()


def _short_process_error(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stderr or "").strip() or (result.stdout or "").strip() or f"exit {result.returncode}"
    text = re.sub(r"\s+", " ", text).strip()
    return text[:600]


__all__ = [
    "CodexCommandRequest",
    "CodexCommandResult",
    "CodexSessionTarget",
    "default_codex_session_roots",
    "execute_codex_admin_command",
    "parse_codex_admin_command",
    "resolve_codex_session_target",
]
