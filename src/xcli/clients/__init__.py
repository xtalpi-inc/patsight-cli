"""Remote job client implementations. Import side effects register clients."""

from xcli.clients import patsight as _patsight  # noqa: F401

__all__ = ["_patsight"]
