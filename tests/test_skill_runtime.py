import os
from pathlib import Path

import pytest

from src.agent.capabilities.models import ToolCall, ToolInvocationContext
from src.agent.capabilities.registry import CapabilityRegistry
from src.agent.plugins.catalog import LoadedPlugin, PluginCatalog
from src.agent.plugins.models import PluginManifest
from src.agent.skills.loader import SkillCatalog
from src.agent.skills.reference_tool import register_skill_reference_tool
from src.agent.skills.resolver import SkillResolver


def _catalog(root: Path, skills: list[dict]) -> PluginCatalog:
    manifest = PluginManifest.model_validate(
        {
            "api_version": "minimal-agent/v1",
            "id": "demo",
            "version": "1.0.0",
            "skills": skills,
        }
    )
    paths = {}
    for skill in manifest.skills:
        path = root / skill.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {skill.id}\n", encoding="utf-8")
        paths[skill.id] = path
    return PluginCatalog(
        plugins={
            "demo": LoadedPlugin("demo", root, manifest, paths),
        }
    )


@pytest.fixture
def skill_catalog(tmp_path):
    plugins = _catalog(
        tmp_path,
        [
            {"id": "review", "path": "skills/review/SKILL.md", "triggers": ["review pull request"]},
            {"id": "manual", "path": "skills/manual/SKILL.md", "triggers": ["manual mode"]},
            {"id": "release", "path": "skills/release/SKILL.md", "triggers": ["release"]},
        ],
    )
    return SkillCatalog.from_plugins(plugins)


def test_explicit_skills_suppress_trigger_additions(skill_catalog):
    selected = SkillResolver(skill_catalog, max_active=3).resolve(
        "please review pull request", ["demo.manual"]
    )

    assert [skill.id for skill in selected] == ["demo.manual"]


def test_explicit_empty_skill_list_suppresses_trigger_additions(skill_catalog):
    selected = SkillResolver(skill_catalog, max_active=3).resolve(
        "please review pull request", []
    )

    assert selected == []


def test_trigger_matching_normalizes_full_phrases_and_applies_stable_limit(skill_catalog):
    selected = SkillResolver(skill_catalog, max_active=2).resolve(
        "Please  REVIEW\nPULL request before RELEASE", None
    )

    assert [skill.id for skill in selected] == ["demo.release", "demo.review"]


def test_unknown_explicit_skill_is_rejected(skill_catalog):
    with pytest.raises(ValueError, match="unknown_skill"):
        SkillResolver(skill_catalog).resolve("anything", ["demo.missing"])


@pytest.fixture
def reference_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_SKILL_REFERENCE_BYTES", "64")
    plugins = _catalog(
        tmp_path,
        [{"id": "review", "path": "skills/review/SKILL.md", "triggers": ["review"]}],
    )
    reference = tmp_path / "skills" / "review" / "references" / "guide.md"
    reference.parent.mkdir()
    reference.write_text("Review the diff.", encoding="utf-8")
    registry = CapabilityRegistry()
    register_skill_reference_tool(registry, SkillCatalog.from_plugins(plugins))
    return registry


@pytest.mark.anyio
async def test_reference_tool_rejects_inactive_skill(reference_registry):
    result = await reference_registry.invoke(
        ToolCall(
            call_id="ref-1",
            tool="internal.skill_read_reference",
            arguments={"skill_id": "demo.review", "path": "guide.md"},
        ),
        ToolInvocationContext(active_skill_ids=()),
    )

    assert result.error_code == "inactive_skill"


@pytest.mark.anyio
async def test_reference_tool_reads_only_active_regular_utf8_reference_files(reference_registry):
    result = await reference_registry.invoke(
        ToolCall(
            call_id="ref-1",
            tool="internal.skill_read_reference",
            arguments={"skill_id": "demo.review", "path": "guide.md"},
        ),
        ToolInvocationContext(active_skill_ids=("demo.review",)),
    )

    assert result.content == "Review the diff."


@pytest.mark.anyio
async def test_reference_tool_rejects_unknown_skill_and_extra_arguments(reference_registry):
    unknown = await reference_registry.invoke(
        ToolCall(
            call_id="ref-1",
            tool="internal.skill_read_reference",
            arguments={"skill_id": "demo.missing", "path": "guide.md"},
        ),
        ToolInvocationContext(active_skill_ids=("demo.missing",)),
    )
    extra = await reference_registry.invoke(
        ToolCall(
            call_id="ref-2",
            tool="internal.skill_read_reference",
            arguments={"skill_id": "demo.review", "path": "guide.md", "extra": True},
        ),
        ToolInvocationContext(active_skill_ids=("demo.review",)),
    )

    assert unknown.error_code == "unknown_skill"
    assert extra.error_code == "invalid_tool_arguments"


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["../SKILL.md", "C:/Windows/win.ini"])
async def test_reference_tool_rejects_paths_outside_references(reference_registry, path):
    result = await reference_registry.invoke(
        ToolCall(
            call_id="ref-1",
            tool="internal.skill_read_reference",
            arguments={"skill_id": "demo.review", "path": path},
        ),
        ToolInvocationContext(active_skill_ids=("demo.review",)),
    )

    assert result.error_code == "reference_path_escape"


@pytest.mark.anyio
async def test_reference_tool_checks_byte_limit_before_decoding(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_SKILL_REFERENCE_BYTES", "3")
    plugins = _catalog(tmp_path, [{"id": "review", "path": "skills/review/SKILL.md"}])
    reference = tmp_path / "skills" / "review" / "references" / "large.md"
    reference.parent.mkdir()
    reference.write_bytes(b"\xff\xff\xff\xff")
    registry = CapabilityRegistry()
    register_skill_reference_tool(registry, SkillCatalog.from_plugins(plugins))

    result = await registry.invoke(
        ToolCall(
            call_id="ref-1",
            tool="internal.skill_read_reference",
            arguments={"skill_id": "demo.review", "path": "large.md"},
        ),
        ToolInvocationContext(active_skill_ids=("demo.review",)),
    )

    assert result.error_code == "reference_too_large"


@pytest.mark.anyio
async def test_reference_tool_rejects_linked_reference_file(reference_registry, tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("links are unsupported")
    linked = tmp_path / "skills" / "review" / "references" / "linked.md"
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    try:
        os.symlink(outside, linked)
    except OSError:
        pytest.skip("creating a link requires unavailable privileges")

    result = await reference_registry.invoke(
        ToolCall(
            call_id="ref-1",
            tool="internal.skill_read_reference",
            arguments={"skill_id": "demo.review", "path": "linked.md"},
        ),
        ToolInvocationContext(active_skill_ids=("demo.review",)),
    )

    assert result.error_code == "reference_path_escape"
