class Denied(Exception):
    """A domain decision; transport adapters choose its HTTP/MCP representation."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


class IntegrationError(Exception):
    """A safe integration failure without provider payloads or credentials."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)
