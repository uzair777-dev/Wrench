"""Exception hierarchy for forge operations."""


class ForgeError(Exception):
    """Root exception for all forge-layer failures."""


class ForgeAdapterNotFoundError(ForgeError):
    """Raised when registry.get_adapter_for_account() cannot resolve a provider."""

    def __init__(self, provider: str):
        super().__init__(f"No forge adapter registered for provider {provider!r}")
        self.provider = provider


class ForgeUnreachableError(ForgeError):
    """Raised when instance URL cannot be reached (DNS, connection, timeout, SSL)."""

    def __init__(self, instance_url: str, cause: str):
        super().__init__(f"Can't reach {instance_url}: {cause}")
        self.instance_url = instance_url
        self.cause = cause


class ForgeAuthenticationError(ForgeError):
    """HTTP 401 — Stored token is invalid, revoked, or expired."""


class ForgeInsufficientScopeError(ForgeError):
    """HTTP 403 — Token is valid but lacks permissions for the requested operation."""

    def __init__(self, message: str, *, scope_hint: str = ""):
        super().__init__(message)
        self.scope_hint = scope_hint


class ForgeRateLimitedError(ForgeError):
    """HTTP 429 — Provider rate limit exceeded."""

    def __init__(self, retry_after_seconds: int):
        super().__init__(f"Rate limited — retry in {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds
