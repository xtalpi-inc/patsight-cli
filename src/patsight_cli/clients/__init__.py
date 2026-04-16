"""Remote job client implementations. Import side effects register clients."""

from patsight_cli.clients import patsight as _patsight  # noqa: F401

__all__ = ["_patsight"]
