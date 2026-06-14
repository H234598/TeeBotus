#!/usr/bin/env python3
"""Report countable YouTube live/LLM parser combination statistics."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_PATH = ROOT / "TeeBotus" / "bot.py"
LEGACY_BOT_PATH = ROOT / "TeeBotus" / "legacy_bot.py"


def _literal_assignment(source: str, name: str) -> str:
    match = re.search(rf'{name}\s*=\s*r[f]?"([^"]+)"', source)
    if not match:
        raise RuntimeError(f"Could not find regex literal assignment for {name}.")
    return match.group(1)


def _pipe_count(pattern: str) -> int:
    return len([part for part in pattern.split("|") if part])


def build_stats() -> dict[str, object]:
    source = BOT_PATH.read_text(encoding="utf-8")
    source_path = BOT_PATH
    if "yes_words" not in source and LEGACY_BOT_PATH.exists():
        source = LEGACY_BOT_PATH.read_text(encoding="utf-8")
        source_path = LEGACY_BOT_PATH
    yes_words = _literal_assignment(source, "yes_words")
    no_words = _literal_assignment(source, "no_words")
    live_name = _literal_assignment(source, "live_name")
    live_delivery = _literal_assignment(source, "live_delivery")
    during_words = _literal_assignment(source, "during_words")
    llm_name = _literal_assignment(source, "llm_name")
    llm_actions = _literal_assignment(source, "llm_actions")
    send_verbs = _literal_assignment(source, "send_verbs")

    yes_count = _pipe_count(yes_words)
    no_count = _pipe_count(no_words)
    bool_word_count = yes_count + no_count

    # These are lexical atom counts for the current regex grammar. They are not
    # intended to count every accepted sentence, because several parser branches
    # accept arbitrary text spans or repeated filler words.
    live_name_atoms = 12
    live_delivery_atoms = 29
    during_word_atoms = 12
    live_negative_prefix_atoms = 8
    live_no_value_atoms = 15
    live_yes_value_atoms = 15
    live_end_time_atoms = 5
    live_end_delivery_atoms = 9
    live_prompt_atoms = 4

    live_false_atoms = (
        live_negative_prefix_atoms * live_name_atoms
        + live_name_atoms * live_no_value_atoms
        + 3 * live_negative_prefix_atoms * during_word_atoms * live_delivery_atoms
        + 2 * live_end_time_atoms * live_end_delivery_atoms
    )
    live_true_atoms = (
        live_name_atoms * live_yes_value_atoms
        + live_prompt_atoms * live_name_atoms
        + live_delivery_atoms * during_word_atoms
        + during_word_atoms * live_delivery_atoms
        + 2 * live_name_atoms
    )

    llm_name_atoms = _pipe_count(llm_name)
    llm_target_atoms = 7 * 4 * llm_name_atoms
    llm_action_atoms = 22
    send_verb_atoms = 21
    llm_negative_prefix_atoms = 8
    llm_no_value_atoms = 15
    llm_yes_value_atoms = yes_count
    llm_false_atoms = (
        llm_negative_prefix_atoms * llm_target_atoms
        + llm_name_atoms * llm_no_value_atoms
        + 2 * llm_action_atoms
        + 6 * (llm_action_atoms + llm_name_atoms)
        + 4 * 5
    )
    llm_true_atoms = (
        llm_target_atoms * llm_yes_value_atoms
        + 6 * 4 * llm_name_atoms
        + 4 * 4 * llm_name_atoms
        + 1
        + send_verb_atoms * llm_target_atoms
        + llm_target_atoms * (12 + llm_action_atoms)
        + 7 * llm_action_atoms
        + llm_action_atoms * 7
        + 2 * 7 * 5
        + 6 * 5
        + 3 * 7
    )

    structured_without_separator_atoms = 3 * bool_word_count * 2 * bool_word_count
    structured_with_separator_atoms = 3 * 3 * bool_word_count * 2 * 3 * bool_word_count
    first_two_bool_token_atoms = bool_word_count * bool_word_count

    result_state_count = 3 * 3
    executable_result_state_count = 2 * 2
    countable_lower_bound_atoms = (
        structured_with_separator_atoms
        + first_two_bool_token_atoms
        + live_false_atoms
        + live_true_atoms
        + llm_false_atoms
        + llm_true_atoms
    )

    return {
        "source": str(source_path.relative_to(ROOT)),
        "language_is_infinite": True,
        "infinite_reasons": [
            "bounded arbitrary text spans such as .{0,60}, .{0,80}, and .{0,100}",
            "unbounded repeated LLM negative filler words",
            "instance-local learned phrases from YouTube_Parser_Misses.jsonl",
            "optional LLM fallback can classify new phrasing at runtime",
        ],
        "result_states": {
            "live_output_values": 3,
            "send_to_llm_values": 3,
            "total": result_state_count,
            "executable_total": executable_result_state_count,
        },
        "word_atoms": {
            "yes_words": yes_count,
            "no_words": no_count,
            "bool_words": bool_word_count,
            "live_name": live_name_atoms,
            "live_delivery": live_delivery_atoms,
            "during_words": during_word_atoms,
            "llm_name": llm_name_atoms,
            "llm_target": llm_target_atoms,
            "llm_actions": llm_action_atoms,
            "send_verbs": send_verb_atoms,
        },
        "countable_atoms": {
            "structured_without_separator": structured_without_separator_atoms,
            "structured_with_separator": structured_with_separator_atoms,
            "first_two_bool_tokens": first_two_bool_token_atoms,
            "live_false": live_false_atoms,
            "live_true": live_true_atoms,
            "live_total": live_false_atoms + live_true_atoms,
            "llm_false": llm_false_atoms,
            "llm_true": llm_true_atoms,
            "llm_total": llm_false_atoms + llm_true_atoms,
            "lower_bound_total": countable_lower_bound_atoms,
        },
        "regex_literals": {
            "yes_words": yes_words,
            "no_words": no_words,
            "live_name": live_name,
            "live_delivery": live_delivery,
            "during_words": during_words,
            "llm_name": llm_name,
            "llm_actions": llm_actions,
            "send_verbs": send_verbs,
        },
    }


def _print_text(stats: dict[str, object]) -> None:
    result_states = stats["result_states"]
    word_atoms = stats["word_atoms"]
    countable_atoms = stats["countable_atoms"]
    assert isinstance(result_states, dict)
    assert isinstance(word_atoms, dict)
    assert isinstance(countable_atoms, dict)

    print("YouTube live/LLM parser statistics")
    print(f"Source: {stats['source']}")
    print("Accepted concrete phrasing count: infinite")
    print("Reasons:")
    for reason in stats["infinite_reasons"]:
        print(f"- {reason}")
    print()
    print("Result states:")
    print(f"- total tri-state pairs: {result_states['total']}")
    print(f"- executable boolean pairs: {result_states['executable_total']}")
    print()
    print("Word atoms:")
    for key, value in word_atoms.items():
        print(f"- {key}: {value}")
    print()
    print("Countable regex atoms:")
    for key, value in countable_atoms.items():
        print(f"- {key}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report countable YouTube parser combination statistics.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    stats = build_stats()
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_text(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
