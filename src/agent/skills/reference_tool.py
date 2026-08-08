"""Read the bounded, non-executable references of an active Skill."""

import os
from pathlib import Path
from typing import Any

from src.agent.capabilities.errors import ToolExecutionError
from src.agent.capabilities.models import ToolSource, ToolSpec
from src.agent.capabilities.registry import CapabilityRegistry

from .loader import SkillCatalog


_TOOL_NAME = "internal.skill_read_reference"
_DEFAULT_MAX_REFERENCE_BYTES = 262_144


def register_skill_reference_tool(
    registry: CapabilityRegistry, catalog: SkillCatalog
) -> None:
    """Register the built-in reference reader against a fixed Skill catalog."""

    max_reference_bytes = _max_reference_bytes()

    def read_reference(arguments: dict[str, Any], context: Any) -> str:
        skill_id = arguments["skill_id"]
        skill = catalog.get(skill_id)
        if skill is None:
            raise ToolExecutionError("unknown_skill")
        if skill_id not in context.active_skill_ids:
            raise ToolExecutionError("inactive_skill")

        path = _reference_path(skill.root / "references", arguments["path"])
        try:
            with path.open("rb") as reference_file:
                data = reference_file.read(max_reference_bytes + 1)
        except OSError as error:
            raise ToolExecutionError("reference_unreadable") from error
        if len(data) > max_reference_bytes:
            raise ToolExecutionError("reference_too_large")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ToolExecutionError("reference_not_utf8") from error

    registry.register(
        ToolSpec(
            name=_TOOL_NAME,
            description="Read a UTF-8 reference file from an active Skill.",
            input_schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "minLength": 1},
                    "path": {"type": "string", "minLength": 1},
                },
                "required": ["skill_id", "path"],
                "additionalProperties": False,
            },
            source=ToolSource.LOCAL,
            side_effects=False,
            idempotent=True,
        ),
        read_reference,
    )


def _max_reference_bytes() -> int:
    try:
        limit = int(
            os.getenv("AGENT_MAX_SKILL_REFERENCE_BYTES", str(_DEFAULT_MAX_REFERENCE_BYTES))
        )
    except ValueError as error:
        raise ValueError("AGENT_MAX_SKILL_REFERENCE_BYTES must be an integer") from error
    if limit <= 0:
        raise ValueError("AGENT_MAX_SKILL_REFERENCE_BYTES must be positive")
    return limit


def _reference_path(references_root: Path, relative_path: str) -> Path:
    candidate_relative = Path(relative_path)
    if candidate_relative.is_absolute() or _is_link_or_junction(references_root):
        raise ToolExecutionError("reference_path_escape")

    current = references_root
    for part in candidate_relative.parts:
        current = current / part
        if current.exists() and _is_link_or_junction(current):
            raise ToolExecutionError("reference_path_escape")

    try:
        root = references_root.resolve(strict=True)
        candidate = (references_root / candidate_relative).resolve(strict=True)
        candidate.relative_to(root)
    except FileNotFoundError as error:
        raise ToolExecutionError("reference_missing") from error
    except (OSError, ValueError) as error:
        raise ToolExecutionError("reference_path_escape") from error

    if not candidate.is_file():
        raise ToolExecutionError("reference_not_file")
    return candidate


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (bool(is_junction()) if is_junction else False)
