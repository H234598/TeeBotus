from __future__ import annotations

import builtins

from TeeBotus.admin.accounts_report import runtime_report_env
from TeeBotus.runtime.dotenv import load_dotenv_defaults, load_project_dotenv_for_instances, project_root_for_instances_dir


def test_load_dotenv_defaults_preserves_process_values(tmp_path) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "KEEP=from_file",
                "NEW_VALUE=plain",
                'export QUOTED_VALUE="quoted value"',
                "EMPTY_VALUE=",
            ]
        ),
        encoding="utf-8",
    )
    env = {"KEEP": "from_process"}

    result = load_dotenv_defaults(dotenv_path, environ=env)

    assert result.exists is True
    assert env["KEEP"] == "from_process"
    assert env["NEW_VALUE"] == "plain"
    assert env["QUOTED_VALUE"] == "quoted value"
    assert env["EMPTY_VALUE"] == ""
    assert result.loaded_keys == ("EMPTY_VALUE", "NEW_VALUE", "QUOTED_VALUE")
    assert result.preserved_keys == ("KEEP",)


def test_load_dotenv_defaults_reports_missing_file_without_mutating_env(tmp_path) -> None:
    env = {"EXISTING": "value"}

    result = load_dotenv_defaults(tmp_path / ".env", environ=env)

    assert result.exists is False
    assert result.loaded_keys == ()
    assert result.preserved_keys == ()
    assert env == {"EXISTING": "value"}


def test_fallback_parser_handles_export_quotes_and_inline_comments(tmp_path, monkeypatch) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "# comment",
                "PLAIN=value # trailing comment",
                "HASH_IN_VALUE=value#not-comment",
                'DOUBLE_QUOTED="value # literal"',
                "SINGLE_QUOTED='single # literal'",
                "export EXPORTED=enabled",
                "IGNORED_WITHOUT_VALUE",
            ]
        ),
        encoding="utf-8",
    )
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "dotenv":
            raise ImportError("force fallback parser")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    env: dict[str, str] = {}

    result = load_dotenv_defaults(dotenv_path, environ=env)

    assert result.exists is True
    assert env == {
        "DOUBLE_QUOTED": "value # literal",
        "EXPORTED": "enabled",
        "HASH_IN_VALUE": "value#not-comment",
        "PLAIN": "value",
        "SINGLE_QUOTED": "single # literal",
    }


def test_project_dotenv_loads_from_instances_ancestor_even_for_nested_paths(tmp_path) -> None:
    repo = tmp_path / "TeeBotus"
    nested_accounts = repo / "instances" / "Depressionsbot" / "data" / "accounts"
    nested_accounts.mkdir(parents=True)
    (repo / ".env").write_text("FROM_PROJECT_ENV=loaded\n", encoding="utf-8")

    assert project_root_for_instances_dir(repo / "instances") == repo
    assert project_root_for_instances_dir(nested_accounts) == repo

    env: dict[str, str] = {}
    result = load_project_dotenv_for_instances(nested_accounts, environ=env)

    assert result.path == repo / ".env"
    assert result.exists is True
    assert env["FROM_PROJECT_ENV"] == "loaded"


def test_project_dotenv_accepts_project_root_as_instances_dir_fallback(tmp_path) -> None:
    repo = tmp_path / "TeeBotus"
    repo.mkdir()
    (repo / ".env").write_text("FROM_PROJECT_ROOT=loaded\n", encoding="utf-8")

    env: dict[str, str] = {}
    result = load_project_dotenv_for_instances(repo, environ=env)

    assert project_root_for_instances_dir(repo) == repo
    assert result.path == repo / ".env"
    assert env["FROM_PROJECT_ROOT"] == "loaded"


def test_runtime_report_env_loads_project_dotenv_as_defaults(tmp_path) -> None:
    repo = tmp_path / "TeeBotus"
    instances_dir = repo / "instances"
    instances_dir.mkdir(parents=True)
    (repo / ".env").write_text(
        "\n".join(
            [
                "TEEBOTUS_RUNTIME_CHANNELS=telegram,signal",
                "PRESERVE_ME=from_file",
            ]
        ),
        encoding="utf-8",
    )

    env = runtime_report_env(instances_dir, base_env={"PRESERVE_ME": "from_process"})

    assert env["TEEBOTUS_RUNTIME_CHANNELS"] == "telegram,signal"
    assert env["PRESERVE_ME"] == "from_process"
