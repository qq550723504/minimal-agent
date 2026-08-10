import json
import re
from typing import Any, List, Union

from src.agent.domain.planning.models import PlanItem, ToolCallPlan, coerce_plan_items, normalize_plan_items


def _normalize_plan_item(item: Any) -> Any:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return item
    return item


def parse_plan_output(text: str) -> List[Union[str, dict]]:
    """尝试从模型输出中解析 JSON 数组；失败时回退到简单分句。"""
    if not text or not text.strip():
        return []

    # 尝试提取 JSON 数组
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, list):
                normalized = [_normalize_plan_item(item) for item in parsed if isinstance(item, (str, dict))]
                return normalized
        except json.JSONDecodeError:
            pass

    parts = [p.strip() for p in re.split(r"[\r\n]+|[。.?!]", text) if p.strip()]
    if not parts:
        return [text.strip()]
    return parts


def parse_structured_plan_output(text: str) -> list[PlanItem]:
    return coerce_plan_items(parse_plan_output(text))


class LLMAdapter:
    """LLM 适配器接口：实现 `plan(prompt) -> List[Any]` 即可被 Planner 使用。"""

    def plan(self, prompt: str) -> List[Any]:
        raise NotImplementedError()


class MockLLM(LLMAdapter):
    """简单的本地规划模拟器：将输入按句子拆分并产生 echo 步骤。

    当提示包含 `Response format:` 指令时，MockLLM 会模拟结构化规划返回，直接输出步骤列表。
    """

    def plan(self, prompt: str) -> List[str]:
        if "Response format:" in prompt:
            task_text = prompt
            if "Task:\n" in prompt:
                task_text = prompt.split("Task:\n", 1)[1]
            if "Response format:" in task_text:
                task_text = task_text.split("Response format:", 1)[0]
            parts = [p.strip() for p in re.split(r"[。.!?\n]+", task_text) if p.strip()]
            if parts:
                return [f"echo: {p}" for p in parts]

        if prompt.strip().startswith("["):
            try:
                parsed = json.loads(prompt)
                if isinstance(parsed, list) and all(isinstance(item, (str, dict)) for item in parsed):
                    return parsed
            except json.JSONDecodeError:
                pass

        parts = [p.strip() for p in re.split(r"[。.?!]", prompt) if p.strip()]
        if not parts:
            return [f"echo: {prompt}"]
        return [f"echo: {p}" for p in parts]


__all__ = [
    "LLMAdapter",
    "MockLLM",
    "ToolCallPlan",
    "normalize_plan_items",
    "parse_plan_output",
    "parse_structured_plan_output",
]
