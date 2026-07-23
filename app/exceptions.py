class TrayError(Exception):
    """Base class for safe, domain-specific Tray errors."""


class TrayConfigurationError(TrayError):
    pass


class TrayAuthenticationError(TrayError):
    pass


class TrayConnectionError(TrayError):
    pass


class TrayAPIError(TrayError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        diagnostics: dict | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.diagnostics = diagnostics or {}


class TrayValidationError(TrayError):
    pass
