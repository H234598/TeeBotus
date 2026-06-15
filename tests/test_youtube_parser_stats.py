import sys
from importlib import util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "youtube_parser_stats.py"
SCRIPT_SPEC = util.spec_from_file_location("youtube_parser_stats", SCRIPT_PATH)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
youtube_parser_stats = util.module_from_spec(SCRIPT_SPEC)
sys.modules[SCRIPT_SPEC.name] = youtube_parser_stats
SCRIPT_SPEC.loader.exec_module(youtube_parser_stats)


def test_youtube_parser_stats_reports_infinite_language_and_countable_atoms() -> None:
    stats = youtube_parser_stats.build_stats()

    assert stats["language_is_infinite"] is True
    assert stats["llm_fallback"] == {
        "default_enabled": False,
        "config_key": "youtube_option_llm_fallback",
        "cost_free_standard_path": True,
    }
    assert "optional LLM fallback can classify new phrasing at runtime" not in stats["infinite_reasons"]
    assert "optional LLM fallback can classify new phrasing only when youtube_option_llm_fallback is enabled" in stats["infinite_reasons"]
    assert stats["result_states"] == {
        "live_output_values": 3,
        "send_to_llm_values": 3,
        "total": 9,
        "executable_total": 4,
    }
    assert stats["word_atoms"]["bool_words"] == 21
    assert stats["word_atoms"]["live_name"] == 12
    assert stats["word_atoms"]["llm_target"] == 252
    assert stats["countable_atoms"]["structured_with_separator"] == 23814
    assert stats["countable_atoms"]["live_total"] == 9666
    assert stats["countable_atoms"]["llm_total"] == 20075
    assert stats["countable_atoms"]["lower_bound_total"] == 53996
