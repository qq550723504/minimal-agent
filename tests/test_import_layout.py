from src.agent.domain.capabilities.models import ToolCall, ToolSpec
from src.agent.application.execution.service import execute_plan_items
from src.agent.application.planning.service import plan_task
from src.agent.application.requests import handle_input_async
from src.agent.infrastructure.llm.llm import MockLLM
from src.agent.infrastructure.memory.vector_memory import VectorMemory
from src.agent.infrastructure.mcp.manager import MCPClientManager
from src.agent.infrastructure.plugins.loader import PluginLoader
from src.agent.infrastructure.workflows.workflow_store import WorkflowStore
from src.agent.security.input import sanitize_input


def test_canonical_domain_and_security_imports():
    assert ToolCall is not None
    assert ToolSpec is not None
    assert sanitize_input("hello") == "hello"


def test_canonical_model_and_memory_imports():
    assert MockLLM is not None
    assert VectorMemory is not None


def test_canonical_runtime_infrastructure_imports():
    assert all((WorkflowStore, PluginLoader, MCPClientManager))


def test_canonical_application_imports():
    assert callable(plan_task)
    assert callable(execute_plan_items)


def test_canonical_request_orchestration_import():
    assert callable(handle_input_async)
