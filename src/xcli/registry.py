from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Type

from xcli.exceptions import RegistryError

if TYPE_CHECKING:
    from xcli.base import RemoteJobClient


class ClientRegistry:
    """Pluggable registry for remote job backends. Built-in: ``patsight`` (PatSight patent extraction)."""

    _registry: Dict[str, Type["RemoteJobClient"]] = {}

    @classmethod
    def register(cls, client_type: str):
        def decorator(client_cls: Type["RemoteJobClient"]):
            if client_type in cls._registry:
                raise RegistryError(f"Client type '{client_type}' already registered")
            cls._registry[client_type] = client_cls
            client_cls.client_type = client_type  # type: ignore[attr-defined]
            return client_cls

        return decorator

    @classmethod
    def get_client_class(cls, client_type: str) -> Type["RemoteJobClient"]:
        client_cls = cls._registry.get(client_type)
        if client_cls is None:
            available = ", ".join(sorted(cls._registry)) or "none"
            raise RegistryError(
                f"Unknown client type '{client_type}'. Available: {available}"
            )
        return client_cls

    @classmethod
    def create(cls, client_type: str, **kwargs: Any) -> "RemoteJobClient":
        client_cls = cls.get_client_class(client_type)
        return client_cls(**kwargs)

    @classmethod
    def list_clients(cls) -> list[str]:
        return sorted(cls._registry.keys())
