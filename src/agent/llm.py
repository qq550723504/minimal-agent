from typing import List


class LLMAdapter:
    """LLM 适配器接口：实现 `plan(prompt) -> List[str]` 即可被 Planner 使用。"""

    def plan(self, prompt: str) -> List[str]:
        raise NotImplementedError()


class MockLLM(LLMAdapter):
    """简单的本地规划模拟器：将输入按句子拆分并产生 echo 步骤。"""

    def plan(self, prompt: str) -> List[str]:
        # 最简单的启发式：按句号/问号分句，去除空段
        import re

        parts = [p.strip() for p in re.split(r"[。.?!]", prompt) if p.strip()]
        if not parts:
            return [f"echo: {prompt}"]
        return [f"echo: {p}" for p in parts]


__all__ = ["LLMAdapter", "MockLLM"]
