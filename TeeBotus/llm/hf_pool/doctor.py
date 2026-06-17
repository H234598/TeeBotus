from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from TeeBotus.llm.hf_pool.health import check_hf_pool, format_hf_pool_status_lines
from TeeBotus.llm.hf_pool.state import SQLiteHFPoolRuntimeStateStore, default_hf_pool_state_path


def main(argv: Sequence[str] | None = None, *, opener: Any | None = None, models_opener: Any | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m TeeBotus.llm.hf_pool.doctor")
    parser.add_argument("--config", default="", help="Path to config/hf_pool.yaml.")
    parser.add_argument("--pool", default="default", help="Pool name to inspect.")
    parser.add_argument("--live", action="store_true", help="Run explicit live HF checks for configured targets.")
    parser.add_argument("--validate-models", action="store_true", help="Fetch optional /v1/models metadata and validate configured target models.")
    parser.add_argument("--state-db", default="", help="SQLite state DB for cooldown/usage data. Defaults to XDG state dir when --live is used.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    kwargs = {"pool_name": args.pool, "live": args.live, "validate_models": args.validate_models}
    if args.config:
        kwargs["config_path"] = args.config
    if args.live or args.state_db:
        state_path = Path(args.state_db).expanduser() if args.state_db else default_hf_pool_state_path()
        kwargs["state_store"] = SQLiteHFPoolRuntimeStateStore(state_path)
    if opener is not None:
        kwargs["opener"] = opener
    if models_opener is not None:
        kwargs["models_opener"] = models_opener
    health = check_hf_pool(**kwargs)
    for line in format_hf_pool_status_lines(health):
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
