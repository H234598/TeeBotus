from __future__ import annotations

import sys

from TeeBotus.admin.accounts_report import *  # noqa: F403
from TeeBotus.admin.accounts_report import main as _accounts_report_main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return _accounts_report_main(["accounts", *args])


if __name__ == "__main__":
    raise SystemExit(main())
