from __future__ import annotations


class DeltaLedgerError(Exception):
    """Base error for expected application failures."""


class ExternalServiceError(DeltaLedgerError):
    """Raised when an external dependency fails."""


class SecClientError(ExternalServiceError):
    """Raised for SEC client failures."""


class UnsafeSecUrlError(SecClientError):
    """Raised when a URL does not point to an allowed SEC host."""


class ObjectStorageError(ExternalServiceError):
    """Raised for object storage failures."""


class ObjectNotFoundError(ObjectStorageError):
    """Raised when an object is missing from storage."""


class DuplicateResourceError(DeltaLedgerError):
    """Raised when idempotency or uniqueness checks fail."""
