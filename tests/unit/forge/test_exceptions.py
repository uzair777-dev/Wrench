"""Unit tests for forge exception hierarchy."""

from wrench.forge.exceptions import (
    ForgeAdapterNotFoundError,
    ForgeAuthenticationError,
    ForgeError,
    ForgeInsufficientScopeError,
    ForgeRateLimitedError,
    ForgeUnreachableError,
)


def test_exception_inheritance():
    assert issubclass(ForgeAdapterNotFoundError, ForgeError)
    assert issubclass(ForgeUnreachableError, ForgeError)
    assert issubclass(ForgeAuthenticationError, ForgeError)
    assert issubclass(ForgeInsufficientScopeError, ForgeError)
    assert issubclass(ForgeRateLimitedError, ForgeError)


def test_forge_adapter_not_found_error():
    err = ForgeAdapterNotFoundError("custom_forge")
    assert "custom_forge" in str(err)
    assert err.provider == "custom_forge"


def test_forge_unreachable_error():
    err = ForgeUnreachableError("https://forge.example.com", "Connection refused")
    assert "https://forge.example.com" in str(err)
    assert "Connection refused" in str(err)
    assert err.instance_url == "https://forge.example.com"
    assert err.cause == "Connection refused"


def test_forge_insufficient_scope_error():
    err = ForgeInsufficientScopeError("Missing scope", scope_hint="needs 'repo' scope")
    assert "Missing scope" in str(err)
    assert err.scope_hint == "needs 'repo' scope"


def test_forge_rate_limited_error():
    err = ForgeRateLimitedError(120)
    assert "120s" in str(err)
    assert err.retry_after_seconds == 120
