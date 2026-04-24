import patsight_cli  # noqa: F401 — side-effect: register clients
from patsight_cli.registry import ClientRegistry


def test_patsight_registered() -> None:
    assert "patsight" in ClientRegistry.list_clients()
