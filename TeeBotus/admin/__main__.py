from __future__ import annotations

import sys

from TeeBotus.admin.accounts_report import main as accounts_report_main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Usage: python -m TeeBotus.admin accounts {report|migrate} [options]", file=sys.stderr)
        return 2
    return accounts_report_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
