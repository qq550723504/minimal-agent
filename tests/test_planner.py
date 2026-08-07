from src.agent.planner import plan_task
from src.agent.llm import MockLLM


def test_plan_with_mock_llm():
    llm = MockLLM()
    steps = plan_task("请总结并回复: 你好。请说明今天的任务。", llm=llm)
    # MockLLM 应把句子拆分成多个 echo 步骤
    assert all(s.startswith("echo: ") for s in steps)
