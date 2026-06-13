#!/usr/bin/env python3
"""Summarize learned YouTube parser misses and promotion candidates."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from TeeBotus.bot import (  # noqa: E402
    YOUTUBE_PARSER_MISSES_FILENAME,
    _normalize_youtube_option_formulation,
    _parse_youtube_local_options,
    _youtube_option_formulation_tokens,
)


def _load_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.exists():
        return entries
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            entries.append(
                {
                    "path": str(path),
                    "line": line_number,
                    "error": f"invalid json: {exc}",
                }
            )
            continue
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["path"] = str(path)
            payload["line"] = line_number
            entries.append(payload)
    return entries


def _miss_paths(instances_dir: Path) -> list[Path]:
    return sorted(instances_dir.glob(f"*/data/{YOUTUBE_PARSER_MISSES_FILENAME}"))


def _promotion_suggestion(
    *,
    tokens: list[str],
    parser_now: tuple[bool | None, bool | None],
    llm_options: dict[str, int],
) -> dict[str, Any] | None:
    if None not in parser_now:
        return None
    target = _dominant_llm_options(llm_options)
    if target is None:
        return None
    missing: list[str] = []
    if parser_now[0] is None:
        missing.append("live_output")
    if parser_now[1] is None:
        missing.append("send_to_llm")
    token_pattern = ""
    if tokens:
        token_pattern = r"\b" + "".join(rf"(?=.*\b{re_escape(token)}\b)" for token in tokens)
    return {
        "missing_fields": missing,
        "target_live_output": target[0],
        "target_send_to_llm": target[1],
        "tokens": tokens,
        "token_pattern_hint": token_pattern if tokens else "",
        "summary": (
            f"add parser coverage for {', '.join(missing)} -> "
            f"(live_output={target[0]}, send_to_llm={target[1]}) using tokens: {', '.join(tokens) or '-'}"
        ),
    }


def _dominant_llm_options(llm_options: dict[str, int]) -> tuple[bool, bool] | None:
    if not llm_options:
        return None
    value, _count = max(llm_options.items(), key=lambda item: (item[1], item[0]))
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list) or len(payload) != 2:
        return None
    if not all(isinstance(item, bool) for item in payload):
        return None
    return payload[0], payload[1]


def re_escape(value: str) -> str:
    return "".join(f"\\{char}" if not char.isalnum() else char for char in value)


def build_report(instances_dir: Path = ROOT / "instances") -> dict[str, Any]:
    all_entries: list[dict[str, Any]] = []
    for path in _miss_paths(instances_dir):
        all_entries.extend(_load_entries(path))

    malformed = [entry for entry in all_entries if "error" in entry]
    valid = [entry for entry in all_entries if "error" not in entry]
    groups: dict[str, dict[str, Any]] = {}
    for entry in valid:
        formulation = str(entry.get("formulation") or "")
        normalized = _normalize_youtube_option_formulation(formulation)
        if not normalized:
            continue
        group = groups.setdefault(
            normalized,
            {
                "formulation": formulation,
                "normalized_formulation": normalized,
                "tokens": sorted(_youtube_option_formulation_tokens(normalized)),
                "count": 0,
                "contexts": Counter(),
                "parser_options": Counter(),
                "llm_options": Counter(),
                "sources": [],
            },
        )
        group["count"] += 1
        group["contexts"][str(entry.get("context") or "")] += 1
        parser_pair = (entry.get("parser_live_output"), entry.get("parser_send_to_llm"))
        llm_pair = (entry.get("llm_live_output"), entry.get("llm_send_to_llm"))
        group["parser_options"][json.dumps(parser_pair, sort_keys=True)] += 1
        group["llm_options"][json.dumps(llm_pair, sort_keys=True)] += 1
        group["sources"].append({"path": entry.get("path"), "line": entry.get("line")})

    grouped = []
    for group in groups.values():
        parser_now = _parse_youtube_local_options(group["formulation"], instance_name="")
        contexts = dict(group["contexts"])
        parser_options = dict(group["parser_options"])
        llm_options = dict(group["llm_options"])
        suggestion = _promotion_suggestion(
            tokens=group["tokens"],
            parser_now=parser_now,
            llm_options=llm_options,
        )
        grouped.append(
            {
                "formulation": group["formulation"],
                "normalized_formulation": group["normalized_formulation"],
                "tokens": group["tokens"],
                "count": group["count"],
                "contexts": contexts,
                "parser_options": parser_options,
                "llm_options": llm_options,
                "base_parser_now": list(parser_now),
                "needs_parser_promotion": None in parser_now,
                "promotion_suggestion": suggestion,
                "sources": group["sources"],
            }
        )
    grouped.sort(key=lambda item: (-int(item["count"]), str(item["normalized_formulation"])))

    return {
        "instances_dir": str(instances_dir),
        "files": [str(path) for path in _miss_paths(instances_dir)],
        "entry_count": len(valid),
        "malformed_count": len(malformed),
        "malformed": malformed,
        "group_count": len(grouped),
        "promotion_candidate_count": sum(1 for item in grouped if item["needs_parser_promotion"]),
        "groups": grouped,
    }


def _print_text(report: dict[str, Any]) -> None:
    print("YouTube parser misses report")
    print(f"Instances dir: {report['instances_dir']}")
    print(f"Files: {len(report['files'])}")
    print(f"Entries: {report['entry_count']}")
    print(f"Malformed: {report['malformed_count']}")
    print(f"Groups: {report['group_count']}")
    print(f"Promotion candidates: {report['promotion_candidate_count']}")
    for group in report["groups"]:
        marker = "PROMOTE" if group["needs_parser_promotion"] else "covered"
        print()
        print(f"[{marker}] x{group['count']} {group['formulation']}")
        print(f"  base_parser_now={tuple(group['base_parser_now'])}")
        print(f"  tokens={', '.join(group['tokens']) or '-'}")
        print(f"  contexts={group['contexts']}")
        print(f"  llm_options={group['llm_options']}")
        if group["promotion_suggestion"]:
            print(f"  suggestion={group['promotion_suggestion']['summary']}")


def build_regression_cases(report: dict[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for group in report["groups"]:
        suggestion = group.get("promotion_suggestion")
        if not suggestion:
            continue
        cases.append(
            {
                "text": group["formulation"],
                "expected": [
                    suggestion["target_live_output"],
                    suggestion["target_send_to_llm"],
                ],
                "missing_fields": suggestion["missing_fields"],
                "tokens": suggestion["tokens"],
                "count": group["count"],
                "sources": group["sources"],
            }
        )
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize YouTube parser miss logs.")
    parser.add_argument("--instances-dir", type=Path, default=ROOT / "instances")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--regression-json", action="store_true", help="Print compact regression cases for promotion candidates.")
    args = parser.parse_args(argv)

    report = build_report(args.instances_dir)
    if args.regression_json:
        print(json.dumps(build_regression_cases(report), ensure_ascii=False, indent=2, sort_keys=True))
    elif args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
