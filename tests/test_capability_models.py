import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from src.agent.capabilities.models import ToolCall, ToolSpec, ToolSource


def test_tool_spec_requires_retry_semantics():
    with pytest.raises(ValidationError):
        ToolSpec(
            name="demo.read",
            input_schema={"type": "object"},
            source=ToolSource.LOCAL,
        )


def test_tool_call_rejects_non_object_arguments():
    with pytest.raises(ValidationError):
        ToolCall(call_id="call-1", tool="demo.read", arguments=["bad"])


def test_tool_execution_error_exposes_metadata_without_secret_message():
    from src.agent.capabilities.errors import ToolExecutionError

    error = ToolExecutionError(
        error_code="remote_failure",
        retryable=True,
        unknown_outcome=True,
        message="Authorization: Bearer secret-token",
    )

    assert error.error_code == "remote_failure"
    assert error.retryable is True
    assert error.unknown_outcome is True
    assert "secret-token" not in str(error)


def test_config_rejects_non_positive_tool_result_limit():
    environment = os.environ | {"AGENT_MAX_TOOL_RESULT_BYTES": "0"}

    result = subprocess.run(
        [sys.executable, "-c", "import src.agent.config"],
        capture_output=True,
        env=environment,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "AGENT_MAX_TOOL_RESULT_BYTES must be positive" in result.stderr
