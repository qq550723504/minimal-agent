"""Deterministic Skill selection without LLM-based routing."""

from .loader import SkillCatalog
from .models import SkillDefinition
from src.agent import config


def normalize_trigger(value: str) -> str:
    """Case-fold and collapse whitespace so phrase matching is deterministic."""

    return " ".join(value.casefold().strip().split())


class SkillResolver:
    def __init__(self, catalog: SkillCatalog, max_active: int | None = None):
        if max_active is None:
            max_active = config.MAX_ACTIVE_SKILLS
        if max_active <= 0:
            raise ValueError("max_active must be positive")
        self.catalog = catalog
        self.max_active = max_active

    def resolve(
        self, prompt: str, explicit_ids: list[str] | None
    ) -> list[SkillDefinition]:
        if explicit_ids is not None:
            return self._resolve_explicit(explicit_ids)

        normalized = normalize_trigger(prompt)
        matches = [
            skill
            for skill in self.catalog.sorted()
            if any(normalize_trigger(trigger) in normalized for trigger in skill.triggers)
        ]
        return matches[: self.max_active]

    def _resolve_explicit(self, explicit_ids: list[str]) -> list[SkillDefinition]:
        selected: list[SkillDefinition] = []
        seen: set[str] = set()
        for skill_id in explicit_ids:
            if skill_id in seen:
                continue
            skill = self.catalog.get(skill_id)
            if skill is None:
                raise ValueError("unknown_skill")
            selected.append(skill)
            seen.add(skill_id)
        return selected[: self.max_active]
