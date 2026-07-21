class TrayError(Exception):
    """Base class for safe, domain-specific Tray errors."""


class TrayConfigurationError(TrayError):
    pass


class TrayAuthenticationError(TrayError):
    pass


class TrayConnectionError(TrayError):
    pass


class TrayAPIError(TrayError):
    pass
