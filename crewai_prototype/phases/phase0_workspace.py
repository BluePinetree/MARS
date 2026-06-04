"""phases/phase0_workspace.py — Workspace directory setup (Phase 0).

Sets up the output directory for a run. If the user specifies a path it is
used directly; otherwise a timestamped directory under DEFAULT_OUTPUT_BASE
is created.

Output: WorkspaceConfig
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Optional

from core.handoff_models import WorkspaceConfig
from pipeline_config.constants import DEFAULT_OUTPUT_BASE


_BASE = Path(__file__).parent.parent  # crewai_prototype/


def _slug(topic: str) -> str:
    """Convert research topic to a safe directory name fragment."""
    s = topic.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s).strip("_")
    return s[:40]


def setup_workspace(
    research_topic: str,
    user_path: Optional[str] = None,
    run_id: Optional[str] = None,
) -> WorkspaceConfig:
    """Create the workspace directory tree and return WorkspaceConfig.

    Args:
        research_topic: Used to generate the default directory name.
        user_path:       If provided, use this as the root (absolute or relative
                         to crewai_prototype/).
        run_id:          If None, a UUID4 is generated.

    Returns:
        WorkspaceConfig with all paths as absolute strings.

    Raises:
        PermissionError: If the directory is not writable.
        ValueError:      If the path is outside the allowed base.
    """
    if run_id is None:
        run_id = uuid.uuid4().hex[:12]

    user_specified = user_path is not None

    if user_path:
        root = Path(user_path)
        if not root.is_absolute():
            root = _BASE / user_path
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        slug = _slug(research_topic)
        dir_name = f"run_{ts}_{slug}_{run_id[:6]}"
        root = _BASE / DEFAULT_OUTPUT_BASE / dir_name

    workspace_dir = root / "workspace"
    paper_dir     = root / "paper"
    handoff_dir   = root / "handoff"
    logs_dir      = root / "logs"
    results_dir   = workspace_dir / "results"
    src_dir       = workspace_dir / "src"

    for d in (workspace_dir, paper_dir, handoff_dir, logs_dir, results_dir, src_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Verify the directory is writable
    probe = root / ".write_probe"
    try:
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        raise PermissionError(f"Workspace directory not writable: {root}") from exc

    return WorkspaceConfig(
        run_id=run_id,
        root_dir=str(root.resolve()),
        workspace_dir=str(workspace_dir.resolve()),
        paper_dir=str(paper_dir.resolve()),
        handoff_dir=str(handoff_dir.resolve()),
        logs_dir=str(logs_dir.resolve()),
        user_specified=user_specified,
    )
