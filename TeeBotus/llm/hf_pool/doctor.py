from __future__ import annotations

import argparse
from collections.abc import Sequence

from TeeBotus.llm.hf_pool.health import check_hf_pool, format_hf_pool_status_lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m TeeBotus.llm.hf_pool.doctor")
    parser.add_argument("--config", default="", help="Path to config/hf_pool.yaml.")
    parser.add_argument("--pool", default="default", help="Pool name to inspect.")
    parser.add_argument("--live", action="store_true", help="Reserved for explicit live HF checks.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    kwargs = {"pool_name": args.pool}
    if args.config:
        kwargs["config_path"] = args.config
    health = check_hf_pool(**kwargs)
    for line in format_hf_pool_status_lines(health):
        print(line)
    if args.live:
        print("hf_pool_live status=skipped reason=live_executor_not_enabled")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
