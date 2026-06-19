from __future__ import annotations

import subprocess
from pathlib import Path

from TeeBotus.core.program_history import build_program_history_reply, recent_commits, recent_releases


def test_program_history_uses_last_20_commits_without_releases(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    for index in range(25):
        _commit(repo, f"Feature {index:02d}")
    _git(repo, "remote", "add", "origin", "git@github.com:example/project.git")

    reply = build_program_history_reply(repo)

    assert "- Repo: https://github.com/example/project" in reply
    assert "- Commits: https://github.com/example/project/commits/main" in reply
    assert "Letzte 20 Commits" in reply
    assert "Letzte 5 Commits" not in reply
    assert "Feature 24" in reply
    assert "Feature 05" in reply
    assert "Feature 04" not in reply


def test_program_history_uses_last_5_commits_and_3_releases_when_tags_exist(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    for index in range(8):
        _commit(repo, f"Bugfix {index:02d}")
        if index in {2, 4, 6, 7}:
            _git(repo, "tag", f"v1.0.{index}")

    reply = build_program_history_reply(repo)

    assert "Letzte 5 Commits" in reply
    assert "Letzte 3 Releases" in reply
    assert "Bugfix 07" in reply
    assert "Bugfix 03" in reply
    assert "Bugfix 02" not in reply
    assert "- v1.0.7 Bugfix 07" in reply
    assert "- v1.0.6 Bugfix 06" in reply
    assert "- v1.0.4 Bugfix 04" in reply
    assert "- v1.0.2 Bugfix 02" not in reply


def test_recent_releases_uses_semver_precedence(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    for tag in ("v1.0.9", "v1.0.10-alpha.1", "v1.0.10-alpha.2", "v1.0.10-alpha.10", "v1.0.10"):
        _commit(repo, f"Release {tag}")
        _git(repo, "tag", tag)

    releases = recent_releases(repo, limit=5)

    assert [release.name for release in releases] == [
        "v1.0.10",
        "v1.0.10-alpha.10",
        "v1.0.10-alpha.2",
        "v1.0.10-alpha.1",
        "v1.0.9",
    ]


def test_recent_releases_breaks_equal_semver_precedence_by_tag_name(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    for tag in ("v1.0.0+build.1", "v1.0.0+build.2", "v1.0.0+build.10"):
        _commit(repo, f"Release {tag}")
        _git(repo, "tag", tag)

    releases = recent_releases(repo, limit=3)

    assert [release.name for release in releases] == ["v1.0.0+build.2", "v1.0.0+build.10", "v1.0.0+build.1"]


def test_recent_releases_ignores_non_semver_tags(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    for tag in ("latest", "release-2026-06-19", "v1.0", "v1.0.0"):
        _commit(repo, f"Release {tag}")
        _git(repo, "tag", tag)

    releases = recent_releases(repo, limit=3)

    assert [release.name for release in releases] == ["v1.0.0"]


def test_program_history_uses_configured_limits_in_headings(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    for index in range(6):
        _commit(repo, f"Change {index:02d}")
        if index in {1, 3, 5}:
            _git(repo, "tag", f"v1.2.{index}")

    reply = build_program_history_reply(repo, release_commit_limit=2, release_limit=1)

    assert "Letzte 2 Commits" in reply
    assert "Letzte 1 Release" in reply
    assert "Letzte 5 Commits" not in reply
    assert "Letzte 3 Releases" not in reply
    assert "Change 05" in reply
    assert "Change 04" in reply
    assert "Change 03" not in reply
    assert "- v1.2.5 Change 05" in reply
    assert "- v1.2.3 Change 03" not in reply


def test_recent_history_helpers_honor_zero_limits(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _commit(repo, "Initial")
    _git(repo, "tag", "v1.0.0")

    assert recent_commits(repo, limit=0) == []
    assert recent_releases(repo, limit=0) == []


def test_program_history_reports_intentional_zero_commit_limit(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _commit(repo, "Initial")

    reply = build_program_history_reply(repo, commit_limit=0)

    assert "Letzte 0 Commits" in reply
    assert "- Keine Eintraege angefordert." in reply
    assert "- Keine lokalen Git-Daten gefunden." not in reply


def test_program_history_reports_intentional_zero_release_commit_limit(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _commit(repo, "Initial")
    _git(repo, "tag", "v1.0.0")

    reply = build_program_history_reply(repo, release_commit_limit=0)

    assert "Letzte 0 Commits" in reply
    assert "- Keine Eintraege angefordert." in reply
    assert "Letzte 3 Releases" in reply
    assert "- v1.0.0 Initial" in reply


def test_recent_history_helpers_return_empty_lists_outside_git_repo(tmp_path: Path) -> None:
    assert recent_commits(tmp_path, limit=20) == []
    assert recent_releases(tmp_path, limit=3) == []
    assert "Keine lokalen Git-Daten gefunden." in build_program_history_reply(tmp_path)


def _git_repo(path: Path) -> Path:
    _git(path, "init")
    _git(path, "config", "user.email", "tester@example.invalid")
    _git(path, "config", "user.name", "TeeBotus Test")
    return path


def _commit(repo: Path, message: str) -> None:
    filename = f"{message.lower().replace(' ', '_')}.txt"
    (repo / filename).write_text(message, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, capture_output=True)
