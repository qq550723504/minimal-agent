class ToolExecutionError(Exception):
    """A tool failure with stable, non-sensitive execution metadata."""

    def __init__(
        self,
        error_code: str,
        *,
        retryable: bool = False,
        unknown_outcome: bool = False,
        message: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.retryable = retryable
        self.unknown_outcome = unknown_outcome
        self.message = message
        super().__init__(f"tool execution failed: {error_code}")
