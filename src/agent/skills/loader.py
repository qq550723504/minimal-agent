"""Build a deterministic Skill catalog from already-validated plugins."""

from dataclasses import dataclass, field

from src.agent.plugins.catalog import PluginCatalog

from .models import SkillDefinition


@dataclass(frozen=True)
class SkillCatalog:
    skills: dict[str, SkillDefinition] = field(default_factory=dict)

    @classmethod
    def from_plugins(cls, plugins: PluginCatalog) -> "SkillCatalog":
        skills: dict[str, SkillDefinition] = {}
        for plugin_id, plugin in plugins.plugins.items():
            for manifest_skill in plugin.manifest.skills:
                full_id = _namespaced_skill_id(plugin_id, manifest_skill.id)
                if full_id in skills:
                    raise ValueError("duplicate_skill_id")
                skills[full_id] = SkillDefinition(
                    id=full_id,
                    plugin_id=plugin_id,
                    skill_id=manifest_skill.id,
                    path=plugin.skill_paths[manifest_skill.id],
                    triggers=tuple(manifest_skill.triggers),
                )
        return cls(skills)

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self.skills.get(skill_id)

    def sorted(self) -> list[SkillDefinition]:
        return [self.skills[skill_id] for skill_id in sorted(self.skills)]


def _namespaced_skill_id(plugin_id: str, skill_id: str) -> str:
    """Keep legacy IDs readable while escaping dots in either segment."""

    return f"{_encode_segment(plugin_id)}.{_encode_segment(skill_id)}"


def _encode_segment(value: str) -> str:
    if "." not in value:
        return value
    # ``~`` is outside the manifest identifier alphabet, so the encoding
    # cannot collide with an unencoded administrator-provided segment.
    return f"~{value.encode('utf-8').hex()}"
