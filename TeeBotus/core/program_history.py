from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from TeeBotus.core.status import github_commit_history_url
from TeeBotus.core.version_notifications import DEFAULT_REPO_URL, github_repo_url


@dataclass(frozen=True)
class GitSummaryItem:
    name: str
    summary: str

    def line(self) -> str:
        if self.summary:
            return f"- {self.name} {self.summary}"
        return f"- {self.name}"


def build_program_history_reply(
    project_root: Path | None = None,
    *,
    commit_limit: int = 20,
    release_commit_limit: int = 5,
    release_limit: int = 3,
) -> str:
    root = project_root or Path(__file__).resolve().parents[2]
    repo_url = github_repo_url(root) or DEFAULT_REPO_URL
    commit_history_url = github_commit_history_url(root)
    releases = recent_releases(root, limit=release_limit)
    commits = recent_commits(root, limit=release_commit_limit if releases else commit_limit)

    lines = [
        "GitHub",
        f"- Repo: {repo_url}",
        f"- Commits: {commit_history_url}",
        "",
    ]
    if releases:
        lines.extend(["Letzte 5 Commits", *_item_lines(commits), "", "Letzte 3 Releases", *_item_lines(releases)])
    else:
        lines.extend(["Letzte 20 Commits", *_item_lines(commits)])
    return "\n".join(lines).rstrip()


def recent_commits(project_root: Path, *, limit: int) -> list[GitSummaryItem]:
    output = _run_git(project_root, "log", "-n", str(max(1, limit)), "--pretty=format:%h%x09%s")
    return _parse_items(output)


def recent_releases(project_root: Path, *, limit: int) -> list[GitSummaryItem]:
    output = _run_git(
        project_root,
        "for-each-ref",
        "--sort=-version:refname",
        f"--count={max(1, limit)}",
        "--format=%(refname:short)%09%(subject)",
        "refs/tags",
    )
    return _parse_items(output)


def _item_lines(items: list[GitSummaryItem]) -> list[str]:
    if not items:
        return ["- Keine lokalen Git-Daten gefunden."]
    return [item.line() for item in items]


def _parse_items(output: str) -> list[GitSummaryItem]:
    items: list[GitSummaryItem] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        name, separator, summary = line.partition("\t")
        if not separator:
            summary = ""
        items.append(GitSummaryItem(name=name.strip(), summary=summary.strip()))
    return items


def _run_git(project_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout
