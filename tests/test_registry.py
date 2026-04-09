import xcli  # noqa: F401 — side-effect: register clients
from xcli.registry import ClientRegistry


def test_patsight_registered() -> None:
    assert "patsight" in ClientRegistry.list_clients()
