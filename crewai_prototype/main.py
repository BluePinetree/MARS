"""V3 CrewAI-native bootstrap entrypoint for the research runtime."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    """Parse the top-level bootstrap arguments."""
    parser = argparse.ArgumentParser(description="CrewAI research runtime bootstrap")
    parser.add_argument(
        "--mode",
        choices=("api", "cli"),
        default="api",
        help="Bootstrap mode",
    )
    args, remaining = parser.parse_known_args(argv)
    return args, remaining


def _run_api() -> None:
    from entrypoints.api import run_api

    run_api()


def _run_cli(argv: list[str] | None = None) -> None:
    from entrypoints.cli import run_cli

    run_cli(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Dispatch to the V2 API or CLI launcher."""
    args, remaining = parse_args(list(argv) if argv is not None else None)
    if args.mode == "cli":
        _run_cli(remaining)
        return
    _run_api()


if __name__ == "__main__":
    main()
