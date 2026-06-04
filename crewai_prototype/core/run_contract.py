"""Run-level contract metadata — scaffold type, CLI args, required symbols."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CliArgSpec:
    name: str
    description: str
    required: bool = False
    aliases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CliArgSpec":
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            required=bool(data.get("required", False)),
            aliases=list(data.get("aliases") or []),
        )


@dataclass
class RunContract:
    scaffold_type: str
    entrypoint: str
    mutable_module: str
    cli_args: list[CliArgSpec]
    required_symbols: dict[str, list[str]]
    required_artifacts: list[str]
    result_json_schema: dict[str, Any]
    validation_metadata_schema: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RunContract":
        raw_args = data.get("cli_args") or []
        cli_args = [
            CliArgSpec.from_dict(a) if isinstance(a, dict) else a
            for a in raw_args
        ]
        return cls(
            scaffold_type=data.get("scaffold_type", ""),
            entrypoint=data.get("entrypoint", ""),
            mutable_module=data.get("mutable_module", ""),
            cli_args=cli_args,
            required_symbols=data.get("required_symbols") or {},
            required_artifacts=data.get("required_artifacts") or [],
            result_json_schema=data.get("result_json_schema") or {},
            validation_metadata_schema=data.get("validation_metadata_schema") or {},
            notes=list(data.get("notes") or []),
        )
