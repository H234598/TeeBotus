from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from TeeBotus.core.status import github_commit_history_url
from TeeBotus.core.version_notifications import DEFAULT_REPO_URL, github_repo_url

SEMVER_TAG_RE = re.compile(
    r"^v?"
    r"(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"$"
)


@dataclass(frozen=True)
class GitSummaryItem:
    name: str
    summary: str

    def line(self) -> str:
        if self.summary:
            return f"- {self.name} {self.summary}"
        return f"- {self.name}"


@dataclass(frozen=True)
class _SemVerTag:
    item: GitSummaryItem
    sort_key: tuple[object, ...]


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
        lines.extend(
            [
                _section_title(release_commit_limit, singular="Commit", plural="Commits"),
                *_item_lines(commits),
                "",
                _section_title(release_limit, singular="Release", plural="Releases"),
                *_item_lines(releases),
            ]
        )
    else:
        lines.extend([_section_title(commit_limit, singular="Commit", plural="Commits"), *_item_lines(commits)])
    return "\n".join(lines).rstrip()


def recent_commits(project_root: Path, *, limit: int) -> list[GitSummaryItem]:
    if limit <= 0:
        return []
    output = _run_git(project_root, "log", "-n", str(limit), "--pretty=format:%h%x09%s")
    return _parse_items(output)


def recent_releases(project_root: Path, *, limit: int) -> list[GitSummaryItem]:
    if limit <= 0:
        return []
    output = _run_git(
        project_root,
        "for-each-ref",
        "--format=%(refname:short)%09%(subject)",
        "refs/tags",
    )
    semver_tags = [_tag for item in _parse_items(output) if (_tag := _parse_semver_tag(item)) is not None]
    semver_tags.sort(key=lambda tag: tag.sort_key, reverse=True)
    return [tag.item for tag in semver_tags[:limit]]


def _item_lines(items: list[GitSummaryItem]) -> list[str]:
    if not items:
        return ["- Keine lokalen Git-Daten gefunden."]
    return [item.line() for item in items]


def _section_title(limit: int, *, singular: str, plural: str) -> str:
    noun = singular if limit == 1 else plural
    return f"Letzte {max(0, limit)} {noun}"


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


def _parse_semver_tag(item: GitSummaryItem) -> _SemVerTag | None:
    match = SEMVER_TAG_RE.fullmatch(item.name)
    if match is None:
        return None
    prerelease = match.group("prerelease")
    prerelease_key: tuple[object, ...]
    if prerelease is None:
        prerelease_key = (1,)
    else:
        prerelease_key = (0, *(_encode_prerelease_identifier(identifier) for identifier in prerelease.split(".")))
    return _SemVerTag(
        item=item,
        sort_key=(
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
            prerelease_key,
        ),
    )


def _encode_prerelease_identifier(identifier: str) -> tuple[int, int, str]:
    if identifier.isdigit():
        return (0, int(identifier), "")
    return (1, 0, identifier)


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
