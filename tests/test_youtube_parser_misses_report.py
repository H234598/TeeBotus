import json
import subprocess
import sys
from importlib import util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "youtube_parser_misses_report.py"
SCRIPT_SPEC = util.spec_from_file_location("youtube_parser_misses_report", SCRIPT_PATH)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
youtube_parser_misses_report = util.module_from_spec(SCRIPT_SPEC)
sys.modules[SCRIPT_SPEC.name] = youtube_parser_misses_report
SCRIPT_SPEC.loader.exec_module(youtube_parser_misses_report)


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False, sort_keys=True) for entry in entries) + "\n",
        encoding="utf-8",
    )


def test_youtube_parser_misses_report_groups_and_marks_promotion_candidates(tmp_path: Path) -> None:
    miss_path = tmp_path / "instances" / "Demo" / "data" / "YouTube_Parser_Misses.jsonl"
    _write_jsonl(
        miss_path,
        [
            {
                "context": "pending-options",
                "formulation": "Mach das ohne Gelaber unterwegs, LLM ja <youtube-url>",
                "parser_live_output": None,
                "parser_send_to_llm": True,
                "llm_live_output": False,
                "llm_send_to_llm": True,
            },
            {
                "context": "initial-request",
                "formulation": "Mach das ohne Gelaber unterwegs, LLM ja <youtube-url>",
                "parser_live_output": None,
                "parser_send_to_llm": True,
                "llm_live_output": False,
                "llm_send_to_llm": True,
            },
            {
                "context": "pending-options",
                "formulation": "live aus, llm ja",
                "parser_live_output": False,
                "parser_send_to_llm": True,
                "llm_live_output": False,
                "llm_send_to_llm": True,
            },
        ],
    )
    with miss_path.open("a", encoding="utf-8") as file:
        file.write("{broken\n")

    report = youtube_parser_misses_report.build_report(tmp_path / "instances")

    assert report["entry_count"] == 3
    assert report["malformed_count"] == 1
    assert report["group_count"] == 2
    assert report["promotion_candidate_count"] == 1

    first = report["groups"][0]
    assert first["count"] == 2
    assert first["needs_parser_promotion"] is True
    assert first["base_parser_now"] == [None, True]
    assert first["contexts"] == {"pending-options": 1, "initial-request": 1}
    assert first["tokens"] == ["gelaber", "llm", "unterwegs"]
    assert first["promotion_suggestion"]["missing_fields"] == ["live_output"]
    assert first["promotion_suggestion"]["target_live_output"] is False
    assert first["promotion_suggestion"]["target_send_to_llm"] is True
    assert first["promotion_suggestion"]["tokens"] == ["gelaber", "llm", "unterwegs"]
    assert "gelaber" in first["promotion_suggestion"]["token_pattern_hint"]

    covered = report["groups"][1]
    assert covered["needs_parser_promotion"] is False
    assert covered["base_parser_now"] == [False, True]
    assert covered["promotion_suggestion"] is None

    cases = youtube_parser_misses_report.build_regression_cases(report)
    assert cases == [
        {
            "text": "Mach das ohne Gelaber unterwegs, LLM ja <youtube-url>",
            "expected": [False, True],
            "missing_fields": ["live_output"],
            "tokens": ["gelaber", "llm", "unterwegs"],
            "count": 2,
            "sources": first["sources"],
        }
    ]
    snippet = youtube_parser_misses_report.build_pytest_snippet(report)
    assert "@pytest.mark.parametrize" in snippet
    assert "Mach das ohne Gelaber unterwegs, LLM ja <youtube-url>" in snippet
    assert "(False, True)" in snippet


def test_youtube_parser_misses_report_cli_runs_from_repo_root(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--instances-dir",
            str(tmp_path / "instances"),
            "--json",
        ],
        cwd=SCRIPT_PATH.parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["entry_count"] == 0
    assert payload["group_count"] == 0


def test_youtube_parser_misses_report_cli_regression_json(tmp_path: Path) -> None:
    miss_path = tmp_path / "instances" / "Demo" / "data" / "YouTube_Parser_Misses.jsonl"
    _write_jsonl(
        miss_path,
        [
            {
                "context": "pending-options",
                "formulation": "Mach das ohne Gelaber unterwegs, LLM ja <youtube-url>",
                "parser_live_output": None,
                "parser_send_to_llm": True,
                "llm_live_output": False,
                "llm_send_to_llm": True,
            }
        ],
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--instances-dir",
            str(tmp_path / "instances"),
            "--regression-json",
        ],
        cwd=SCRIPT_PATH.parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload[0]["text"] == "Mach das ohne Gelaber unterwegs, LLM ja <youtube-url>"
    assert payload[0]["expected"] == [False, True]


def test_youtube_parser_misses_report_cli_pytest_snippet(tmp_path: Path) -> None:
    miss_path = tmp_path / "instances" / "Demo" / "data" / "YouTube_Parser_Misses.jsonl"
    _write_jsonl(
        miss_path,
        [
            {
                "context": "pending-options",
                "formulation": "Mach das ohne Gelaber unterwegs, LLM ja <youtube-url>",
                "parser_live_output": None,
                "parser_send_to_llm": True,
                "llm_live_output": False,
                "llm_send_to_llm": True,
            }
        ],
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--instances-dir",
            str(tmp_path / "instances"),
            "--pytest-snippet",
        ],
        cwd=SCRIPT_PATH.parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "from TeeBotus.bot import _parse_youtube_local_options" in result.stdout
    assert "Mach das ohne Gelaber unterwegs, LLM ja <youtube-url>" in result.stdout
    assert "(False, True)" in result.stdout
