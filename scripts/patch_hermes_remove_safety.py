from pathlib import Path


def main() -> None:
    path = Path("src/openakita/hermes/lifecycle.py")
    text = path.read_text("utf-8")
    old = '''    async def remove(self, instance: HermesInstance, *, delete_data: bool = False) -> None:\n        if instance.mode == HermesInstanceMode.SHARED:\n            raise ContainerManagerError("不能删除默认共享实例")\n        if not self.is_native(instance) and HermesContainerManager.available():\n            await self.containers.remove(instance, delete_data=delete_data)\n        self.instances.delete(instance.id)\n        get_hermes_store().delete(instance.id)\n'''
    new = '''    async def remove(self, instance: HermesInstance, *, delete_data: bool = False) -> None:\n        if instance.mode == HermesInstanceMode.SHARED:\n            raise ContainerManagerError("不能删除默认共享实例")\n        if not self.is_native(instance):\n            if not HermesContainerManager.available():\n                raise ContainerManagerError(\n                    "Docker socket unavailable; cannot safely remove Hermes container"\n                )\n            await self.containers.remove(instance, delete_data=delete_data)\n        self.instances.delete(instance.id)\n        get_hermes_store().delete(instance.id)\n'''
    if old not in text:
        if new in text:
            return
        raise SystemExit("Hermes remove marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")

    test = Path("tests/hermes/test_remove_safety.py")
    test.write_text(
        '''import pytest\n\nfrom openakita.hermes.container_manager import ContainerManagerError, HermesContainerManager\nfrom openakita.hermes.execution import HermesInstance, HermesInstanceMode, HermesInstanceStore\nfrom openakita.hermes.lifecycle import HermesLifecycleService\nfrom openakita.hermes.store import HermesNodeStore\n\n\n@pytest.mark.asyncio\nasync def test_docker_instance_is_not_forgotten_when_docker_unavailable(tmp_path, monkeypatch):\n    service = HermesLifecycleService()\n    service.instances = HermesInstanceStore(tmp_path / "instances.json")\n    node_store = HermesNodeStore(tmp_path / "nodes.json")\n    monkeypatch.setattr("openakita.hermes.lifecycle.get_hermes_store", lambda: node_store)\n    monkeypatch.setattr(HermesContainerManager, "available", staticmethod(lambda: False))\n\n    instance = HermesInstance(\n        id="dedicated-a",\n        name="A",\n        mode=HermesInstanceMode.DEDICATED,\n        base_url="http://openakita-hermes-dedicated-a:8642",\n    )\n    service.instances.upsert(instance)\n    service._register_node(instance)\n\n    with pytest.raises(ContainerManagerError, match="Docker socket unavailable"):\n        await service.remove(instance)\n\n    assert service.instances.get(instance.id) is not None\n    assert node_store.get(instance.id) is not None\n\n\n@pytest.mark.asyncio\nasync def test_native_instance_can_be_removed_without_docker(tmp_path, monkeypatch):\n    service = HermesLifecycleService()\n    service.instances = HermesInstanceStore(tmp_path / "instances.json")\n    node_store = HermesNodeStore(tmp_path / "nodes.json")\n    monkeypatch.setattr("openakita.hermes.lifecycle.get_hermes_store", lambda: node_store)\n    monkeypatch.setattr(HermesContainerManager, "available", staticmethod(lambda: False))\n\n    instance = HermesInstance(\n        id="dedicated-native",\n        name="Native",\n        mode=HermesInstanceMode.DEDICATED,\n        base_url="native://dedicated-native",\n    )\n    service.instances.upsert(instance)\n    service._register_node(instance)\n    await service.remove(instance)\n\n    assert service.instances.get(instance.id) is None\n    assert node_store.get(instance.id) is None\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
