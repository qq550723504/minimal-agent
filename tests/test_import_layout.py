from src.agent.domain.capabilities.models import ToolCall, ToolSpec
from src.agent.infrastructure.llm.llm import MockLLM
from src.agent.infrastructure.memory.vector_memory import VectorMemory
from src.agent.security.input import sanitize_input


def test_canonical_domain_and_security_imports():
    assert ToolCall is not None
    assert ToolSpec is not None
    assert sanitize_input("hello") == "hello"


def test_canonical_model_and_memory_imports():
    assert MockLLM is not None
    assert VectorMemory is not None
