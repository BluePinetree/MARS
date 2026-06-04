from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class ProjectFileSpec:
    path: str
    purpose: str
    required_symbols: List[str] = field(default_factory=list)
    mutable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectFileSpec":
        return cls(
            path=str(data.get("path", "")),
            purpose=str(data.get("purpose", "")),
            required_symbols=[str(symbol) for symbol in data.get("required_symbols", []) or []],
            mutable=bool(data.get("mutable", False)),
        )


@dataclass(slots=True)
class ProjectManifest:
    scaffold_type: str
    description: str
    entrypoint: str
    mutable_files: List[str] = field(default_factory=list)
    patch_only_after_bootstrap: bool = True
    files: List[ProjectFileSpec] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["files"] = [spec.to_dict() for spec in self.files]
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectManifest":
        files = [ProjectFileSpec.from_dict(item) for item in data.get("files", []) if isinstance(item, dict)]
        return cls(
            scaffold_type=str(data.get("scaffold_type", "")),
            description=str(data.get("description", "")),
            entrypoint=str(data.get("entrypoint", "")),
            mutable_files=[str(path) for path in data.get("mutable_files", []) or []],
            patch_only_after_bootstrap=bool(data.get("patch_only_after_bootstrap", True)),
            files=files,
            metadata=dict(data.get("metadata", {}) or {}),
        )
