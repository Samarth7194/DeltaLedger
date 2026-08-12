from __future__ import annotations

from app.evaluation.real_sec import cli_main


def main(argv: list[str] | None = None) -> int:
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
