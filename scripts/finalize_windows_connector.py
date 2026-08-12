#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str, *, optional: bool = False) -> None:
    target = ROOT / path
    text = target.read_text("utf-8")
    if new in text:
        return
    if old not in text:
        if optional:
            return
        raise RuntimeError(f"marker missing in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), "utf-8")


def fix_frontend_api() -> None:
    path = ROOT / "apps/setup-center/src/components/WindowsConnectorPanel.tsx"
    text = path.read_text("utf-8")
    old_sig = '''function ResourceCard({\n  node,\n  resource,\n  profiles,\n  reload,\n}: {\n  node: NodeInfo;\n  resource: Resource;\n  profiles: AgentProfile[];\n  reload: () => Promise<void>;\n}) {'''
    new_sig = '''function ResourceCard({\n  api,\n  node,\n  resource,\n  profiles,\n  reload,\n}: {\n  api: string;\n  node: NodeInfo;\n  resource: Resource;\n  profiles: AgentProfile[];\n  reload: () => Promise<void>;\n}) {'''
    if new_sig not in text:
        if old_sig not in text:
            raise RuntimeError("ResourceCard signature marker missing")
        text = text.replace(old_sig, new_sig, 1)
    text = text.replace("`${DEFAULT_API}/api/windows-connector/grants`", "`${api}/api/windows-connector/grants`")
    text = text.replace("`${DEFAULT_API}/api/windows-connector/grants/${encodeURIComponent(grantId)}`", "`${api}/api/windows-connector/grants/${encodeURIComponent(grantId)}`")
    old_render = '<ResourceCard key={resource.id} node={node} resource={resource} profiles={profiles} reload={load} />'
    new_render = '<ResourceCard key={resource.id} api={api} node={node} resource={resource} profiles={profiles} reload={load} />'
    text = text.replace(old_render, new_render)
    path.write_text(text, "utf-8")


def add_launch_tool() -> None:
    path = ROOT / "src/openakita/windows_connector/tools.py"
    text = path.read_text("utf-8")
    if '"name": "windows_launch_app"' not in text:
        marker = '''    {\n        "name": "windows_close_app",\n        "category": "Windows Connector",\n'''
        block = '''    {\n        "name": "windows_launch_app",\n        "category": "Windows Connector",\n        "description": "Launch another instance of an authorized Windows application using the exact executable path discovered for that grant. Requires launch permission.",\n        "input_schema": {"type": "object", "properties": _base_properties(), "required": ["node_id", "resource_id"]},\n    },\n'''
        if marker not in text:
            raise RuntimeError("windows_close_app marker missing")
        text = text.replace(marker, block + marker, 1)
    if '"windows_launch_app": "launch"' not in text:
        text = text.replace('    "windows_browser_type": "browser_type",\n', '    "windows_browser_type": "browser_type",\n    "windows_launch_app": "launch",\n', 1)
    if '"windows_launch_app": ApprovalClass.EXEC_CAPABLE' not in text:
        text = text.replace('        "windows_browser_type": ApprovalClass.EXEC_CAPABLE,\n', '        "windows_browser_type": ApprovalClass.EXEC_CAPABLE,\n        "windows_launch_app": ApprovalClass.EXEC_CAPABLE,\n', 1)
    path.write_text(text, "utf-8")


def add_generic_pairing_aliases() -> None:
    path = ROOT / "src/openakita/api/routes/windows_connector.py"
    text = path.read_text("utf-8")
    if "class PairingCreatePayload" not in text:
        marker = "\n\nclass GrantPayload(BaseModel):\n"
        models = '''\n\nclass PairingCreatePayload(BaseModel):\n    node_name: str = Field(default="Windows 电脑", min_length=1, max_length=100)\n    ttl_seconds: int = Field(default=3600, ge=60, le=3600)\n\n\nclass PairingConsumePayload(BaseModel):\n    code: str = Field(min_length=6, max_length=20)\n\n\nclass PairingClosePayload(BaseModel):\n    code: str = Field(min_length=6, max_length=20)\n'''
        if marker not in text:
            raise RuntimeError("GrantPayload marker missing")
        text = text.replace(marker, models + marker, 1)
    if '@router.post("/pairing-code")' not in text:
        marker = '\n\n@router.get("/nodes")\n'
        routes = '''\n\n@router.post("/pairing-code")\nasync def create_pairing_code(body: PairingCreatePayload) -> dict[str, Any]:\n    code = await wechat_desktop_manager.create_pairing_code(body.node_name, body.ttl_seconds)\n    return {"code": code, "expires_in": body.ttl_seconds}\n\n\n@router.post("/pairing-code/close")\nasync def close_pairing_code(body: PairingClosePayload) -> dict[str, bool]:\n    return {"ok": True, "closed": await wechat_desktop_manager.cancel_pairing_code(body.code)}\n\n\n@router.post("/pair")\nasync def pair_connector(body: PairingConsumePayload) -> dict[str, str]:\n    try:\n        node_id, node_token, node_name = await wechat_desktop_manager.consume_pairing_code(body.code)\n    except ValueError as exc:\n        raise HTTPException(status_code=400, detail="配对码无效或已过期") from exc\n    return {"node_id": node_id, "node_token": node_token, "node_name": node_name}\n'''
        if marker not in text:
            raise RuntimeError("nodes route marker missing")
        text = text.replace(marker, routes + marker, 1)
    path.write_text(text, "utf-8")


def point_connector_at_generic_pair_api() -> None:
    path = ROOT / "src/openakita/wechat_desktop/connector_bundle/app.py"
    text = path.read_text("utf-8")
    text = text.replace('requests.post(f"{url}/api/wechat-desktop/pair",', 'requests.post(f"{url}/api/windows-connector/pair",')
    path.write_text(text, "utf-8")


def exempt_generic_pair_endpoint() -> None:
    replace(
        "src/openakita/api/auth.py",
        '        "/api/wechat-desktop/pair",\n',
        '        "/api/wechat-desktop/pair",\n        "/api/windows-connector/pair",\n',
    )


def harden_executor() -> None:
    replace(
        "src/openakita/windows_connector/executor.py",
        "import os\nimport subprocess\n",
        "import os\nimport re\nimport subprocess\nimport time\n",
    )
    replace(
        "src/openakita/windows_connector/executor.py",
        '''        if fingerprint:\n            for item in resources:\n                if item.get("fingerprint") == fingerprint:\n                    return item\n        raise RuntimeError("resource is no longer available")\n''',
        '''        if fingerprint:\n            matches = [item for item in resources if item.get("fingerprint") == fingerprint]\n            if len(matches) == 1:\n                return matches[0]\n            if len(matches) > 1:\n                raise ConnectorPermissionError("resource fingerprint is ambiguous; refresh the grant")\n        raise RuntimeError("resource is no longer available")\n''',
    )
    replace(
        "src/openakita/windows_connector/executor.py",
        '''        if str(grant.get("resource_id") or "") != resource_id and str(grant.get("fingerprint") or "") != fingerprint:\n            raise ConnectorPermissionError("grant does not match requested resource")\n''',
        '''        grant_resource_id = str(grant.get("resource_id") or "")\n        grant_fingerprint = str(grant.get("fingerprint") or "")\n        if grant_resource_id != resource_id:\n            if not fingerprint or grant_fingerprint != fingerprint:\n                raise ConnectorPermissionError("grant does not match requested resource")\n            matches = [item for item in self.resources() if item.get("fingerprint") == fingerprint]\n            if len(matches) != 1 or str(matches[0].get("id") or "") != resource_id:\n                raise ConnectorPermissionError("grant fallback identity is ambiguous or stale")\n''',
    )
    replace(
        "src/openakita/windows_connector/executor.py",
        '''    @staticmethod\n    def _focus(hwnd: int) -> None:\n        if os.name != "nt" or not hwnd:\n            return\n        user32 = ctypes.windll.user32\n        user32.ShowWindow(hwnd, 9)\n        user32.SetForegroundWindow(hwnd)\n\n    @staticmethod\n    def _uia_window(resource: dict[str, Any]):\n''',
        '''    @staticmethod\n    def _focus(hwnd: int) -> None:\n        if os.name != "nt" or not hwnd:\n            raise RuntimeError("authorized Windows window is unavailable")\n        user32 = ctypes.windll.user32\n        if not user32.IsWindow(hwnd):\n            raise RuntimeError("authorized Windows window is no longer available")\n        user32.ShowWindow(hwnd, 9)\n        if not user32.SetForegroundWindow(hwnd):\n            raise RuntimeError("could not focus the authorized Windows window")\n        for _ in range(5):\n            if int(user32.GetForegroundWindow()) == int(hwnd):\n                return\n            time.sleep(0.03)\n        raise RuntimeError("authorized Windows window did not receive foreground focus")\n\n    @staticmethod\n    def _uia_window(resource: dict[str, Any]):\n''',
    )
    replace(
        "src/openakita/windows_connector/executor.py",
        '        return Desktop(backend="uia").window(title_re=f".*{title}.*")\n',
        '        return Desktop(backend="uia").window(title_re=f".*{re.escape(title)}.*")\n',
    )
    replace(
        "src/openakita/windows_connector/executor.py",
        '''        except Exception:\n            from PIL import ImageGrab\n\n            image = ImageGrab.grab(all_screens=True)\n''',
        '''        except Exception as exc:\n            try:\n                window = self._uia_window(resource)\n                rect = window.rectangle()\n                if rect.width() <= 0 or rect.height() <= 0:\n                    raise RuntimeError("authorized window has no capturable area")\n                from PIL import ImageGrab\n\n                image = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)\n            except Exception as fallback_exc:\n                raise RuntimeError("unable to capture only the authorized window") from fallback_exc\n''',
    )
    replace(
        "src/openakita/windows_connector/executor.py",
        '''        x, y = int(args.get("x") or 0), int(args.get("y") or 0)\n        if not x and not y:\n            raise ValueError("target or x/y is required")\n        from pywinauto import mouse\n\n''',
        '''        x, y = int(args.get("x") or 0), int(args.get("y") or 0)\n        if not x and not y:\n            raise ValueError("target or x/y is required")\n        rect = window.rectangle()\n        if not (rect.left <= x < rect.right and rect.top <= y < rect.bottom):\n            raise ConnectorPermissionError("click coordinates are outside the authorized window")\n        from pywinauto import mouse\n\n''',
    )
    replace(
        "src/openakita/windows_connector/executor.py",
        '''        if action == "scroll":\n            self._select_uia_tab(resource)\n            from pywinauto import mouse\n            mouse.scroll(coords=(int(args.get("x") or 0), int(args.get("y") or 0)), wheel_dist=int(args.get("amount") or -3))\n            return {"ok": True, "result": {"scrolled": True}}\n''',
        '''        if action == "scroll":\n            self._select_uia_tab(resource)\n            window = self._uia_window(resource)\n            rect = window.rectangle()\n            x = int(args.get("x") if args.get("x") is not None else (rect.left + rect.right) // 2)\n            y = int(args.get("y") if args.get("y") is not None else (rect.top + rect.bottom) // 2)\n            if not (rect.left <= x < rect.right and rect.top <= y < rect.bottom):\n                raise ConnectorPermissionError("scroll coordinates are outside the authorized window")\n            self._focus(int(resource.get("hwnd") or 0))\n            from pywinauto import mouse\n\n            mouse.scroll(coords=(x, y), wheel_dist=int(args.get("amount") or -3))\n            return {"ok": True, "result": {"scrolled": True, "coords": [x, y]}}\n''',
    )


def harden_resource_identity() -> None:
    replace(
        "src/openakita/windows_connector/app_discovery.py",
        '''        fingerprint = _fingerprint(kind, exe_path or lowered, account_name or title)\n        rows.append(\n            {\n                "id": _resource_id(kind, int(pid.value), int(hwnd), title),\n                "fingerprint": fingerprint,\n''',
        '''        stable_identity = _fingerprint(kind, exe_path or lowered, account_name or title)\n        volatile_window_id = _fingerprint(kind, int(pid.value), int(hwnd), title)\n        fingerprint = stable_identity\n        rows.append(\n            {\n                "id": _resource_id(kind, int(pid.value), int(hwnd), title),\n                "fingerprint": fingerprint,\n                "stable_identity": stable_identity,\n                "volatile_window_id": volatile_window_id,\n''',
    )
    replace(
        "src/openakita/windows_connector/app_discovery.py",
        '''        fingerprint = _fingerprint("browser_tab", browser_name, url or title)\n        rows.append(\n            {\n                "id": _resource_id("browser_tab", browser_name, port, tab_id),\n                "fingerprint": fingerprint,\n''',
        '''        stable_identity = _fingerprint("browser_tab", browser_name, title or url)\n        volatile_window_id = _fingerprint("browser_tab", browser_name, port, tab_id)\n        fingerprint = stable_identity\n        rows.append(\n            {\n                "id": _resource_id("browser_tab", browser_name, port, tab_id),\n                "fingerprint": fingerprint,\n                "stable_identity": stable_identity,\n                "volatile_window_id": volatile_window_id,\n''',
    )
    replace(
        "src/openakita/windows_connector/app_discovery.py",
        '''        fingerprint = _fingerprint("browser_tab", exe_path or process_name, title)\n        rows.append(\n            {\n                "id": _resource_id("browser_tab", hwnd, index, title),\n                "fingerprint": fingerprint,\n''',
        '''        stable_identity = _fingerprint("browser_tab", exe_path or process_name, title)\n        volatile_window_id = _fingerprint("browser_tab", hwnd, index, title)\n        fingerprint = stable_identity\n        rows.append(\n            {\n                "id": _resource_id("browser_tab", hwnd, index, title),\n                "fingerprint": fingerprint,\n                "stable_identity": stable_identity,\n                "volatile_window_id": volatile_window_id,\n''',
    )


def harden_manager_identity_and_state() -> None:
    replace(
        "src/openakita/windows_connector/manager.py",
        'STATE_PATH = Path("data/windows_connector/state.json")\nLOCAL_NODE_ID = "local"\n',
        '''def _default_state_path() -> Path:\n    explicit = os.environ.get("OPENAKITA_DATA_DIR", "").strip()\n    if explicit:\n        return Path(explicit).expanduser().resolve() / "windows_connector" / "state.json"\n    return Path.home() / ".openakita" / "data" / "windows_connector" / "state.json"\n\n\nSTATE_PATH = _default_state_path()\nLEGACY_STATE_PATH = Path("data/windows_connector/state.json")\nLOCAL_NODE_ID = "local"\n''',
    )
    replace(
        "src/openakita/windows_connector/manager.py",
        '''    fingerprint: str\n    kind: str\n''',
        '''    fingerprint: str\n    kind: str\n    stable_identity: str = ""\n    volatile_window_id: str = ""\n''',
    )
    replace(
        "src/openakita/windows_connector/manager.py",
        '''    fingerprint: str\n    remark: str = ""\n''',
        '''    fingerprint: str\n    stable_identity: str = ""\n    remark: str = ""\n''',
    )
    replace(
        "src/openakita/windows_connector/manager.py",
        '''        self._local_executor = WindowsCommandExecutor()\n        self._load()\n''',
        '''        self._local_executor = WindowsCommandExecutor()\n        self._migrate_legacy_state()\n        self._load()\n''',
    )
    replace(
        "src/openakita/windows_connector/manager.py",
        '''    @property\n    def local_available(self) -> bool:\n''',
        '''    def _migrate_legacy_state(self) -> None:\n        if self.path.exists() or self.path == LEGACY_STATE_PATH or not LEGACY_STATE_PATH.exists():\n            return\n        try:\n            self.path.parent.mkdir(parents=True, exist_ok=True)\n            self.path.write_bytes(LEGACY_STATE_PATH.read_bytes())\n        except OSError:\n            pass\n\n    @property\n    def local_available(self) -> bool:\n''',
    )
    replace(
        "src/openakita/windows_connector/manager.py",
        '            "version": 2,\n',
        '            "version": 3,\n',
    )
    replace(
        "src/openakita/windows_connector/manager.py",
        '''        result: list[dict[str, Any]] = []\n        for item in rows:\n            raw = asdict(item)\n            raw["grants"] = [\n                self._grant_dict(grant)\n                for grant in grants\n                if grant.node_id == node_id\n                and (grant.resource_id == item.id or grant.fingerprint == item.fingerprint)\n            ]\n            result.append(raw)\n''',
        '''        identity_counts: dict[str, int] = {}\n        for item in rows:\n            identity = item.stable_identity or item.fingerprint\n            identity_counts[identity] = identity_counts.get(identity, 0) + 1\n        result: list[dict[str, Any]] = []\n        for item in rows:\n            identity = item.stable_identity or item.fingerprint\n            raw = asdict(item)\n            raw["grants"] = [\n                self._grant_dict(grant)\n                for grant in grants\n                if grant.node_id == node_id\n                and (\n                    grant.resource_id == item.id\n                    or (\n                        identity_counts.get(identity) == 1\n                        and (grant.stable_identity or grant.fingerprint) == identity\n                    )\n                )\n            ]\n            result.append(raw)\n''',
    )
    replace(
        "src/openakita/windows_connector/manager.py",
        '''                fingerprint=resource.fingerprint,\n                remark=str(raw.get("remark") or "").strip(),\n''',
        '''                fingerprint=resource.fingerprint,\n                stable_identity=resource.stable_identity or resource.fingerprint,\n                remark=str(raw.get("remark") or "").strip(),\n''',
    )
    replace(
        "src/openakita/windows_connector/manager.py",
        '''            candidates = [\n                grant\n                for grant in self._grants.values()\n                if grant.node_id == node_id\n                and grant.agent_profile_id == agent_profile_id\n                and (grant.resource_id == resource.id or grant.fingerprint == resource.fingerprint)\n            ]\n''',
        '''            exact = [\n                grant\n                for grant in self._grants.values()\n                if grant.node_id == node_id\n                and grant.agent_profile_id == agent_profile_id\n                and grant.resource_id == resource.id\n            ]\n            candidates = exact\n            if not candidates:\n                identity = resource.stable_identity or resource.fingerprint\n                collisions = [\n                    item for item in resources.values()\n                    if (item.stable_identity or item.fingerprint) == identity\n                ]\n                if len(collisions) == 1:\n                    candidates = [\n                        grant\n                        for grant in self._grants.values()\n                        if grant.node_id == node_id\n                        and grant.agent_profile_id == agent_profile_id\n                        and (grant.stable_identity or grant.fingerprint) == identity\n                    ]\n''',
    )


def fix_hermes_capability_category_check() -> None:
    replace(
        "src/openakita/hermes/capability_bridge.py",
        '''    if not _tool_allowed(profile, tool_name=tool_name):\n        return json.dumps({"error": f"Tool '{tool_name}' is not enabled for Agent '{profile_id}'"}, ensure_ascii=False)\n''',
        '''    windows_tool_names: set[str] = set()\n    try:\n        from openakita.windows_connector.tools import WINDOWS_CONNECTOR_TOOLS\n\n        for raw in WINDOWS_CONNECTOR_TOOLS:\n            normalized = _to_hermes_schema(raw)\n            if normalized:\n                windows_tool_names.add(str(normalized["name"]))\n    except Exception:\n        pass\n    category = "Windows Connector" if tool_name in windows_tool_names else ""\n    if not _tool_allowed(profile, tool_name=tool_name, category=category):\n        return json.dumps({"error": f"Tool '{tool_name}' is not enabled for Agent '{profile_id}'"}, ensure_ascii=False)\n''',
    )


def normalize_native_hermes_instances() -> None:
    replace(
        "src/openakita/hermes/lifecycle.py",
        '''    @staticmethod\n    def is_native(instance: HermesInstance) -> bool:\n        return instance.base_url.startswith("native://")\n''',
        '''    @classmethod\n    def is_native(cls, instance: HermesInstance) -> bool:\n        return instance.base_url.startswith("native://") or cls.native_default()\n\n    def normalize_instance(self, instance: HermesInstance) -> HermesInstance:\n        if not self.native_default() or instance.base_url.startswith("native://"):\n            return instance\n        normalized = replace(instance, base_url=self._native_url(instance.id))\n        if instance.enabled:\n            normalized = self._native_state(normalized)\n        self.instances.upsert(normalized)\n        self._register_node(normalized)\n        return normalized\n''',
    )
    replace(
        "src/openakita/api/routes/execution_instances.py",
        '''def _native_info(instance) -> dict:\n    is_native = instance.base_url.startswith("native://") or HermesLifecycleService.native_default()\n''',
        '''def _normalized_instance(instance):\n    return HermesLifecycleService().normalize_instance(instance)\n\n\ndef _native_info(instance) -> dict:\n    instance = _normalized_instance(instance)\n    is_native = HermesLifecycleService.is_native(instance)\n''',
    )
    replace(
        "src/openakita/api/routes/execution_instances.py",
        '''    if instance.base_url.startswith("native://"):\n        if not NativeHermesRuntime.available():\n''',
        '''    instance = _normalized_instance(instance)\n    if HermesLifecycleService.is_native(instance):\n        if not NativeHermesRuntime.available():\n''',
    )
    replace(
        "src/openakita/api/routes/execution_instances.py",
        '''    if instance.base_url.startswith("native://") or HermesLifecycleService.native_default():\n        return {"logs": _native_logs(instance, tail)}\n''',
        '''    instance = _normalized_instance(instance)\n    if HermesLifecycleService.is_native(instance):\n        return {"logs": _native_logs(instance, tail)}\n''',
    )


def remove_stale_runtime_routing_script() -> None:
    path = ROOT / "scripts/finalize_windows_agent_runtime_routing.py"
    if path.exists():
        path.unlink()


def add_regression_tests() -> None:
    path = ROOT / "tests/windows_connector/test_security_regressions.py"
    path.write_text(
        '''from __future__ import annotations\n\nimport asyncio\nfrom pathlib import Path\nfrom types import SimpleNamespace\n\nimport pytest\n\nfrom openakita.windows_connector.executor import ConnectorPermissionError, WindowsCommandExecutor\nfrom openakita.windows_connector.manager import WindowsConnectorManager\n\n\ndef test_executor_rejects_ambiguous_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:\n    executor = WindowsCommandExecutor()\n    monkeypatch.setattr(executor, "resources", lambda: [\n        {"id": "a", "fingerprint": "same"},\n        {"id": "b", "fingerprint": "same"},\n    ])\n    with pytest.raises(ConnectorPermissionError):\n        executor._resource("missing", "same")\n\n\ndef test_uia_title_regex_is_escaped(monkeypatch: pytest.MonkeyPatch) -> None:\n    captured = {}\n\n    class Desktop:\n        def __init__(self, backend: str) -> None:\n            assert backend == "uia"\n\n        def window(self, **kwargs):\n            captured.update(kwargs)\n            return object()\n\n    import sys\n\n    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=Desktop))\n    WindowsCommandExecutor._uia_window({"title": "a[1].*", "hwnd": 0})\n    assert captured["title_re"] == r".*a\\[1\\]\\.\\*.*"\n\n\ndef test_manager_fingerprint_fallback_requires_unique_live_resource(tmp_path: Path) -> None:\n    manager = WindowsConnectorManager(tmp_path / "state.json")\n\n    async def scenario() -> None:\n        await manager.sync_resources("n1", [\n            {"id": "r1", "fingerprint": "same", "stable_identity": "same", "kind": "app", "app_name": "A"},\n            {"id": "r2", "fingerprint": "same", "stable_identity": "same", "kind": "app", "app_name": "A"},\n        ])\n        await manager.upsert_grant({"node_id": "n1", "agent_profile_id": "agent", "resource_id": "r1"})\n        with pytest.raises(PermissionError):\n            await manager._resolve_grant("n1", "agent", "r2", "inspect")\n\n    asyncio.run(scenario())\n''',
        "utf-8",
    )


def main() -> None:
    fix_frontend_api()
    add_launch_tool()
    add_generic_pairing_aliases()
    point_connector_at_generic_pair_api()
    exempt_generic_pair_endpoint()
    harden_executor()
    harden_resource_identity()
    harden_manager_identity_and_state()
    fix_hermes_capability_category_check()
    normalize_native_hermes_instances()
    remove_stale_runtime_routing_script()
    add_regression_tests()
    print("Windows Connector finalization applied")


if __name__ == "__main__":
    main()
