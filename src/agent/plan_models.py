import json
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PLAN_TOOL_NAME_PATTERN = r"^[a-z0-9][a-z0-9_.-]*$"


class ToolCallPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["tool_call"]
    call_id: str = Field(min_length=1, max_length=128)
    tool: str = Field(pattern=PLAN_TOOL_NAME_PATTERN)
    arguments: dict[str, Any]


PlanItem = str | ToolCallPlan


def _serialize_text_safe_item(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    return str(item)


def normalize_plan_items(items: Sequence[Any]) -> list[PlanItem]:
    normalized: list[PlanItem] = []
    for item in items:
        if isinstance(item, str):
            normalized.append(item)
            continue
        if isinstance(item, dict):
            if item.get("kind") == "tool_call":
                normalized.append(ToolCallPlan.model_validate(item))
                continue
            normalized.append(_serialize_text_safe_item(item))
            continue
        normalized.append(_serialize_text_safe_item(item))
    return normalized


def normalize_plan_items_text(items: Sequence[Any]) -> list[str]:
    return [_serialize_text_safe_item(item) for item in items]


def coerce_plan_items(items: Sequence[Any]) -> list[PlanItem]:
    try:
        return normalize_plan_items(items)
    except ValidationError:
        return normalize_plan_items_text(items)
