"""Credential backend abstraction."""

from abc import ABC, abstractmethod


class CredentialBackendUnavailableError(Exception):
    """Raised when no secret storage provider could be reached."""


class CredentialBackend(ABC):
    @abstractmethod
    def store_secret(self, key: str, secret: str, *, label: str) -> None: ...

    @abstractmethod
    def get_secret(self, key: str) -> str | None: ...

    @abstractmethod
    def delete_secret(self, key: str) -> None: ...

    @abstractmethod
    def unavailable_help_text(self) -> str: ...
