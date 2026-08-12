import pytest

from openakita.hermes.container_manager import ContainerManagerError, HermesContainerManager
from openakita.hermes.execution import HermesInstance, HermesInstanceMode, HermesInstanceStore
from openakita.hermes.lifecycle import HermesLifecycleService
from openakita.hermes.store import HermesNodeStore


def _instance(instance_id: str = "dedicated-a") -> HermesInstance:
    return HermesInstance(
        id=instance_id,
        name=instance_id,
        mode=HermesInstanceMode.DEDICATED,
        base_url=f"http://openakita-hermes-{instance_id}:8642",
    )


@pytest.mark.asyncio
async def test_docker_instance_is_not_forgotten_when_docker_unavailable(tmp_path, monkeypatch):
    service = HermesLifecycleService()
    service.instances = HermesInstanceStore(tmp_path / "instances.json")
    node_store = HermesNodeStore(tmp_path / "nodes.json")
    monkeypatch.setattr("openakita.hermes.lifecycle.get_hermes_store", lambda: node_store)
    monkeypatch.setattr(HermesContainerManager, "available", staticmethod(lambda: False))

    instance = _instance()
    service.instances.upsert(instance)
    service._register_node(instance)

    with pytest.raises(ContainerManagerError, match="Docker socket unavailable"):
        await service.remove(instance)

    assert service.instances.get(instance.id) is not None
    assert node_store.get(instance.id) is not None


@pytest.mark.asyncio
async def test_native_instance_can_be_removed_without_docker(tmp_path, monkeypatch):
    service = HermesLifecycleService()
    service.instances = HermesInstanceStore(tmp_path / "instances.json")
    node_store = HermesNodeStore(tmp_path / "nodes.json")
    monkeypatch.setattr("openakita.hermes.lifecycle.get_hermes_store", lambda: node_store)
    monkeypatch.setattr(HermesContainerManager, "available", staticmethod(lambda: False))

    instance = HermesInstance(
        id="dedicated-native",
        name="Native",
        mode=HermesInstanceMode.DEDICATED,
        base_url="native://dedicated-native",
    )
    service.instances.upsert(instance)
    service._register_node(instance)
    await service.remove(instance)

    assert service.instances.get(instance.id) is None
    assert node_store.get(instance.id) is None


@pytest.mark.asyncio
async def test_container_remove_propagates_rm_failure(monkeypatch):
    manager = HermesContainerManager()
    instance = _instance("dedicated-rm")

    async def inspect(_instance):
        return {"exists": True, "running": True}

    async def run(*args, **kwargs):
        if args[:2] == ("rm", "-f"):
            raise ContainerManagerError("rm failed")
        return 0, "", ""

    monkeypatch.setattr(manager, "inspect", inspect)
    monkeypatch.setattr(manager, "_run", run)

    with pytest.raises(ContainerManagerError, match="rm failed"):
        await manager.remove(instance)


@pytest.mark.asyncio
async def test_container_remove_propagates_volume_failure(monkeypatch):
    manager = HermesContainerManager()
    instance = _instance("dedicated-volume")

    async def inspect(_instance):
        return {"exists": False, "running": False}

    async def run(*args, **kwargs):
        if args[:2] == ("volume", "inspect"):
            return 0, "{}", ""
        if args[:2] == ("volume", "rm"):
            raise ContainerManagerError("volume failed")
        return 0, "", ""

    monkeypatch.setattr(manager, "inspect", inspect)
    monkeypatch.setattr(manager, "_run", run)

    with pytest.raises(ContainerManagerError, match="volume failed"):
        await manager.remove(instance, delete_data=True)


@pytest.mark.asyncio
async def test_missing_volume_is_already_clean(monkeypatch):
    manager = HermesContainerManager()
    instance = _instance("dedicated-missing-volume")
    calls = []

    async def inspect(_instance):
        return {"exists": False, "running": False}

    async def run(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("volume", "inspect"):
            return 1, "", "No such volume"
        raise AssertionError(f"unexpected docker call: {args}")

    monkeypatch.setattr(manager, "inspect", inspect)
    monkeypatch.setattr(manager, "_run", run)
    await manager.remove(instance, delete_data=True)
    assert calls == [("volume", "inspect", instance.volume_name)]
