from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    path = Path("src/openakita/hermes/lifecycle.py")
    replace_exact(
        path,
        '''    async def remove(self, instance: HermesInstance, *, delete_data: bool = False) -> None:\n        if instance.mode == HermesInstanceMode.SHARED:\n            raise ContainerManagerError("不能删除默认共享实例")\n        if not self.is_native(instance) and HermesContainerManager.available():\n            await self.containers.remove(instance, delete_data=delete_data)\n        self.instances.delete(instance.id)\n        get_hermes_store().delete(instance.id)\n''',
        '''    async def remove(self, instance: HermesInstance, *, delete_data: bool = False) -> None:\n        if instance.mode == HermesInstanceMode.SHARED:\n            raise ContainerManagerError("不能删除默认共享实例")\n        if not self.is_native(instance):\n            if not HermesContainerManager.available():\n                raise ContainerManagerError(\n                    "Docker socket unavailable; cannot safely remove Hermes container"\n                )\n            await self.containers.remove(instance, delete_data=delete_data)\n        self.instances.delete(instance.id)\n        get_hermes_store().delete(instance.id)\n''',
        "Hermes lifecycle remove",
    )

    path = Path("src/openakita/hermes/container_manager.py")
    replace_exact(
        path,
        '''    async def remove(self, instance: HermesInstance, *, delete_data: bool = False) -> None:\n        self._validate(instance)\n        await self._run("rm", "-f", instance.container_name, check=False)\n        if delete_data:\n            await self._run("volume", "rm", instance.volume_name, check=False)\n''',
        '''    async def remove(self, instance: HermesInstance, *, delete_data: bool = False) -> None:\n        self._validate(instance)\n        state = await self.inspect(instance)\n        if state["exists"]:\n            await self._run("rm", "-f", instance.container_name)\n        if delete_data:\n            # A requested data deletion is part of the operation contract. Do\n            # not report success if Docker refuses to remove the volume.\n            await self._run("volume", "rm", instance.volume_name)\n''',
        "container remove",
    )

    test = Path("tests/hermes/test_remove_safety.py")
    test.write_text(
        '''import pytest\n\nfrom openakita.hermes.container_manager import ContainerManagerError, HermesContainerManager\nfrom openakita.hermes.execution import HermesInstance, HermesInstanceMode, HermesInstanceStore\nfrom openakita.hermes.lifecycle import HermesLifecycleService\nfrom openakita.hermes.store import HermesNodeStore\n\n\ndef _instance(instance_id: str = "dedicated-a") -> HermesInstance:\n    return HermesInstance(\n        id=instance_id,\n        name=instance_id,\n        mode=HermesInstanceMode.DEDICATED,\n        base_url=f"http://openakita-hermes-{instance_id}:8642",\n    )\n\n\n@pytest.mark.asyncio\nasync def test_docker_instance_is_not_forgotten_when_docker_unavailable(tmp_path, monkeypatch):\n    service = HermesLifecycleService()\n    service.instances = HermesInstanceStore(tmp_path / "instances.json")\n    node_store = HermesNodeStore(tmp_path / "nodes.json")\n    monkeypatch.setattr("openakita.hermes.lifecycle.get_hermes_store", lambda: node_store)\n    monkeypatch.setattr(HermesContainerManager, "available", staticmethod(lambda: False))\n\n    instance = _instance()\n    service.instances.upsert(instance)\n    service._register_node(instance)\n\n    with pytest.raises(ContainerManagerError, match="Docker socket unavailable"):\n        await service.remove(instance)\n\n    assert service.instances.get(instance.id) is not None\n    assert node_store.get(instance.id) is not None\n\n\n@pytest.mark.asyncio\nasync def test_native_instance_can_be_removed_without_docker(tmp_path, monkeypatch):\n    service = HermesLifecycleService()\n    service.instances = HermesInstanceStore(tmp_path / "instances.json")\n    node_store = HermesNodeStore(tmp_path / "nodes.json")\n    monkeypatch.setattr("openakita.hermes.lifecycle.get_hermes_store", lambda: node_store)\n    monkeypatch.setattr(HermesContainerManager, "available", staticmethod(lambda: False))\n\n    instance = HermesInstance(\n        id="dedicated-native",\n        name="Native",\n        mode=HermesInstanceMode.DEDICATED,\n        base_url="native://dedicated-native",\n    )\n    service.instances.upsert(instance)\n    service._register_node(instance)\n    await service.remove(instance)\n\n    assert service.instances.get(instance.id) is None\n    assert node_store.get(instance.id) is None\n\n\n@pytest.mark.asyncio\nasync def test_container_remove_propagates_rm_failure(monkeypatch):\n    manager = HermesContainerManager()\n    instance = _instance("dedicated-rm")\n\n    async def inspect(_instance):\n        return {"exists": True, "running": True}\n\n    async def run(*args, **kwargs):\n        if args[:2] == ("rm", "-f"):\n            raise ContainerManagerError("rm failed")\n        return 0, "", ""\n\n    monkeypatch.setattr(manager, "inspect", inspect)\n    monkeypatch.setattr(manager, "_run", run)\n\n    with pytest.raises(ContainerManagerError, match="rm failed"):\n        await manager.remove(instance)\n\n\n@pytest.mark.asyncio\nasync def test_container_remove_propagates_volume_failure(monkeypatch):\n    manager = HermesContainerManager()\n    instance = _instance("dedicated-volume")\n\n    async def inspect(_instance):\n        return {"exists": False, "running": False}\n\n    async def run(*args, **kwargs):\n        if args[:2] == ("volume", "rm"):\n            raise ContainerManagerError("volume failed")\n        return 0, "", ""\n\n    monkeypatch.setattr(manager, "inspect", inspect)\n    monkeypatch.setattr(manager, "_run", run)\n\n    with pytest.raises(ContainerManagerError, match="volume failed"):\n        await manager.remove(instance, delete_data=True)\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
