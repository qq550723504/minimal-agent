"""Immutable runtime records for declarative plugin Skills."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillDefinition:
    """A validated Skill exposed with a globally namespaced identifier."""

    id: str
    plugin_id: str
    skill_id: str
    path: Path
    triggers: tuple[str, ...]

    @property
    def root(self) -> Path:
        """Directory containing the Skill's validated ``SKILL.md`` file."""

        return self.path.parent
