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


@pytest.mark.asyncio
async def test_container_inspect_daemon_failure_is_not_missing(monkeypatch):
    manager = HermesContainerManager()
    instance = _instance("dedicated-daemon")

    async def run(*args, **kwargs):
        assert args[0] == "inspect"
        return 1, "", "Cannot connect to the Docker daemon"

    monkeypatch.setattr(manager, "_run", run)
    with pytest.raises(ContainerManagerError, match="Cannot connect"):
        await manager.inspect(instance)


@pytest.mark.asyncio
async def test_container_inspect_only_explicit_missing_is_missing(monkeypatch):
    manager = HermesContainerManager()
    instance = _instance("dedicated-gone")

    async def run(*args, **kwargs):
        assert args[0] == "inspect"
        return 1, "", f"Error: No such object: {instance.container_name}"

    monkeypatch.setattr(manager, "_run", run)
    state = await manager.inspect(instance)
    assert state == {"exists": False, "running": False, "status": "missing"}


@pytest.mark.asyncio
async def test_volume_inspect_daemon_failure_propagates(monkeypatch):
    manager = HermesContainerManager()
    instance = _instance("dedicated-volume-daemon")

    async def inspect(_instance):
        return {"exists": False, "running": False}

    async def run(*args, **kwargs):
        if args[:2] == ("volume", "inspect"):
            return 1, "", "Cannot connect to the Docker daemon"
        raise AssertionError(f"unexpected docker call: {args}")

    monkeypatch.setattr(manager, "inspect", inspect)
    monkeypatch.setattr(manager, "_run", run)
    with pytest.raises(ContainerManagerError, match="Cannot connect"):
        await manager.remove(instance, delete_data=True)


@pytest.mark.asyncio
async def test_network_inspect_daemon_failure_propagates(monkeypatch):
    manager = HermesContainerManager()
    calls = []

    async def run(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("network", "inspect"):
            return 1, "", "Cannot connect to the Docker daemon"
        raise AssertionError(f"unexpected docker call: {args}")

    monkeypatch.setattr(manager, "_run", run)
    with pytest.raises(ContainerManagerError, match="Cannot connect"):
        await manager.ensure_network("openakita")
    assert calls == [("network", "inspect", "openakita")]


@pytest.mark.asyncio
async def test_missing_network_is_created(monkeypatch):
    manager = HermesContainerManager()
    calls = []

    async def run(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("network", "inspect"):
            return 1, "", "Error: network openakita not found"
        if args[:2] == ("network", "create"):
            return 0, "openakita", ""
        raise AssertionError(f"unexpected docker call: {args}")

    monkeypatch.setattr(manager, "_run", run)
    await manager.ensure_network("openakita")
    assert calls == [
        ("network", "inspect", "openakita"),
        ("network", "create", "openakita"),
    ]


def test_docker_desktop_cli_counts_as_available_on_windows(monkeypatch):
    from openakita.hermes import container_manager as module

    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(module.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.shutil, "which", lambda name: "C:/Docker/docker.exe" if name == "docker" else None)
    assert HermesContainerManager.available()


def test_linux_without_socket_does_not_assume_cli_means_daemon(monkeypatch):
    from openakita.hermes import container_manager as module

    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(module.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/bin/docker")
    assert not HermesContainerManager.available()
