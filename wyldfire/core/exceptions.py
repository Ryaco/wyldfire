"""Custom exception types for Wyldfire."""

class WyldError(Exception):
    """Base error for user-facing errors.
    
    Renders as:
    Error: <what> (<how to fix>)
    """
    def __init__(self, message: str, suggestion: str | None = None, exit_code: int = 1):
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion
        self.exit_code = exit_code

    def __str__(self) -> str:
        if self.suggestion:
            return f"Error: {self.message} ({self.suggestion})"
        return f"Error: {self.message}"


class ProjectNotFoundError(WyldError):
    def __init__(self):
        super().__init__(
            "not in a wyld project",
            "run 'wyld init' to create one here, or cd to a wyld project directory"
        )


class FireNotSelectedError(WyldError):
    def __init__(self):
        super().__init__(
            "no fire selected",
            "pass --fire <name> or checkout one with 'wyld fire checkout <name>'"
        )
