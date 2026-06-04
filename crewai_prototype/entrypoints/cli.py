"""CLI entrypoint for the V3 CrewAI-native research runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from entrypoints.init import initialize_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CrewAI V3 research runtime CLI")
    parser.add_argument("--input", type=str, help="Path to a JSON research request file")
    parser.add_argument("--topic", dest="topic", type=str, help="Research topic")
    parser.add_argument("--goal", dest="goal", type=str, help="Research goal")
    parser.add_argument("--domain", dest="domain", type=str, help="Research domain")
    parser.add_argument("--profile", dest="profile", type=str,
                        choices=["vision_classification", "tabular_supervised",
                                 "timeseries_forecasting", "generic_script"],
                        help="Scaffold profile")
    parser.add_argument("--max-iterations", type=int, default=3,
                        help="Maximum iteration count (default 3)")
    parser.add_argument("--primary-metric", type=str, default="accuracy",
                        help="Primary evaluation metric")
    return parser


def _load_input_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Input file must be a JSON object: {path}")
    return payload


def _build_research_input(args: argparse.Namespace) -> dict[str, Any]:
    payload = _load_input_file(args.input)
    overrides: dict[str, Any] = {
        "research_topic": args.topic,
        "research_goal": args.goal,
        "research_domain": args.domain,
        "profile": args.profile,
        "max_iterations": args.max_iterations,
        "primary_metric": args.primary_metric,
    }
    for key, value in overrides.items():
        if value is not None:
            payload[key] = value
    return payload


def run_cli(argv: list[str] | None = None) -> dict[str, Any]:
    """Execute a research run through the V3 coordinator (blocking)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    research_input = _build_research_input(args)

    if not research_input.get("research_topic"):
        parser.error("--topic (or research_topic in --input file) is required")

    services = initialize_runtime()
    result = services.coordinator.run_sync(research_input)
    print(f"[cli] run complete: run_id={result.get('run_id')} report={result.get('report_path')}")
    return result
