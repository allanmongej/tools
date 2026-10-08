"""Errors reported by the CLI as structured diagnostics."""


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
