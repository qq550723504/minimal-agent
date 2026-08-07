from src.agent.memory import get_global_memory
from src.agent.planner import plan_task, _build_rag_prompt
from src.agent.llm import MockLLM, LLMAdapter


def test_plan_with_mock_llm():
    llm = MockLLM()
    steps = plan_task("请总结并回复: 你好。请说明今天的任务。", llm=llm)
    # MockLLM 应把句子拆分成多个 echo 步骤
    assert all(s.startswith("echo: ") for s in steps)


def test_build_rag_prompt():
    prompt = "What is the capital of France?"
    memories = [
        {"text": "Paris is the capital of France.", "metadata": {"source": "wiki"}},
        {"text": "France has many regions."},
    ]

    result = _build_rag_prompt(prompt, memories)
    assert "Relevant memory:" in result
    assert "Paris is the capital of France." in result
    assert "Task:\nWhat is the capital of France?" in result


def test_build_rag_prompt_with_conversation_history():
    prompt = "Summarize the plan"
    memories = []
    history = [
        {"prompt": "第一步：收集需求。"},
        {"prompt": "第二步：设计架构。"},
    ]

    result = _build_rag_prompt(prompt, memories, history)
    assert "System:" in result
    assert "Conversation history:" in result
    assert "第一步：收集需求。" in result
    assert "Task:\nSummarize the plan" in result
    assert "Response format:" in result


def test_build_rag_prompt_structure():
    prompt = "Create a deployment checklist"
    memories = [
        {"text": "Deployment requires environment validation.", "metadata": {"source": "ops"}}
    ]
    result = _build_rag_prompt(prompt, memories)

    assert result.startswith("System:")
    assert "Relevant memory:" in result
    assert "Response format:" in result


def test_plan_task_includes_conversation_history():
    class RecordingLLM(LLMAdapter):
        def __init__(self):
            self.prompt = None

        def plan(self, prompt: str):
            self.prompt = prompt
            return [prompt]

    llm = RecordingLLM()
    mem = get_global_memory()
    mem.add("user42", {"prompt": "Earlier request about deployment."})

    steps = plan_task("Now summarize the deployment plan.", user_id="user42", llm=llm)
    assert steps == [llm.prompt]
    assert "Conversation history:" in llm.prompt
    assert "Earlier request about deployment." in llm.prompt
    assert "Task:\nNow summarize the deployment plan." in llm.prompt


def test_plan_task_skips_default_user_history():
    class RecordingLLM(LLMAdapter):
        def __init__(self):
            self.prompt = None

        def plan(self, prompt: str):
            self.prompt = prompt
            return [prompt]

    llm = RecordingLLM()
    mem = get_global_memory()
    mem.add("default", {"prompt": "Earlier request about deployment."})

    steps = plan_task("Now summarize the deployment plan.", llm=llm)
    assert steps == [llm.prompt]
    assert "Conversation history:" not in llm.prompt
    assert "Earlier request about deployment." not in llm.prompt
    assert "Task:\nNow summarize the deployment plan." in llm.prompt
