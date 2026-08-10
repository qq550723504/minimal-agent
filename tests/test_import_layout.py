from src.agent.domain.capabilities.models import ToolCall, ToolSpec
from src.agent.security.input import sanitize_input


def test_canonical_domain_and_security_imports():
    assert ToolCall is not None
    assert ToolSpec is not None
    assert sanitize_input("hello") == "hello"
