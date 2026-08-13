from __future__ import annotations

import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"{label}: marker changed")


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    begin = text.find(start)
    if begin < 0:
        if replacement.strip() in text:
            return text
        raise SystemExit(f"{label}: start marker missing")
    finish = text.find(end, begin)
    if finish < 0:
        raise SystemExit(f"{label}: end marker missing")
    return text[:begin] + replacement + text[finish:]


def patch_hub() -> None:
    path = Path("src/openakita/api/routes/hub.py")
    text = path.read_text("utf-8")

    text = replace_once(
        text,
        '''        try:\n            data = _json.loads(content)\n        except (ValueError, UnicodeDecodeError) as e:\n            raise HTTPException(400, f"无效的 JSON 文件: {e}")\n\n        if data.get("format") == "akita-agent-batch":\n''',
        '''        try:\n            data = _json.loads(content)\n        except (ValueError, UnicodeDecodeError) as e:\n            raise HTTPException(400, f"无效的 JSON 文件: {e}")\n        if not isinstance(data, dict):\n            raise HTTPException(400, "无效的 Agent JSON：根节点必须是对象")\n\n        if data.get("format") == "akita-agent-batch":\n''',
        "Hub JSON root validation",
    )

    if "def _snapshot_import_identity(" not in text:
        marker = "def _invalidate_imported_profile_runtime(request: Request, profile_id: str) -> None:\n"
        helper = '''def _snapshot_import_identity(\n    profile_store, profile_id: str, identity_files: dict | None\n) -> dict[str, bytes | None]:\n    if not isinstance(identity_files, dict):\n        return {}\n    identity_dir = profile_store.get_profile_dir(profile_id) / "identity"\n    snapshot: dict[str, bytes | None] = {}\n    for filename, content in identity_files.items():\n        if filename not in PROFILE_IDENTITY_FILENAMES or not isinstance(content, str):\n            continue\n        target = identity_dir / filename\n        snapshot[filename] = target.read_bytes() if target.is_file() else None\n    return snapshot\n\n\ndef _restore_imported_profile(\n    profile_store,\n    profile_id: str,\n    previous_profile,\n    identity_snapshot: dict[str, bytes | None],\n) -> None:\n    from openakita.utils.atomic_io import safe_write_bytes\n\n    if previous_profile is None:\n        profile_store.delete(profile_id)\n        return\n    profile_store.save(previous_profile)\n    identity_dir = profile_store.ensure_profile_dir(profile_id) / "identity"\n    for filename, previous in identity_snapshot.items():\n        target = identity_dir / filename\n        if previous is None:\n            target.unlink(missing_ok=True)\n        else:\n            safe_write_bytes(\n                target, previous, backup=False, fsync=True, allow_fallback=False\n            )\n\n\n'''
        if marker not in text:
            raise SystemExit("Hub rollback helper marker changed")
        text = text.replace(marker, helper + marker, 1)

    transaction = '''        imported = []\n        skipped = []\n        committed: list[tuple[str, object | None, dict[str, bytes | None]]] = []\n        try:\n            for item in raw_agents:\n                if isinstance(item, dict) and isinstance(item.get("profile"), dict):\n                    pdata = dict(item.get("profile", {}))\n                    identity_files = item.get("identity_files")\n                else:\n                    pdata = dict(item) if isinstance(item, dict) else {}\n                    identity_files = pdata.pop("identity_files", None)\n                if not pdata:\n                    raise HTTPException(400, "批量 Agent JSON 包含无效条目")\n                pid = pdata.get("id", "")\n                pdata["type"] = "custom"\n                for key in ("ephemeral", "inherit_from", "user_customized", "hidden"):\n                    pdata.pop(key, None)\n\n                if profile_store.exists(pid) and not force:\n                    suffix = 1\n                    while profile_store.exists(f"{pid}-{suffix}"):\n                        suffix += 1\n                    old_id = pid\n                    pid = f"{pid}-{suffix}"\n                    pdata["id"] = pid\n                    skipped.append(f"{old_id} → {pid}")\n\n                try:\n                    profile = AgentProfile.from_dict(pdata)\n                    profile_store.get_profile_dir(profile.id)\n                except (TypeError, ValueError) as exc:\n                    raise HTTPException(\n                        status_code=400, detail=f"Invalid Agent profile: {exc}"\n                    ) from exc\n\n                previous_profile = profile_store.get(profile.id)\n                identity_snapshot = _snapshot_import_identity(\n                    profile_store, profile.id, identity_files\n                )\n                try:\n                    profile_store.save(profile)\n                except ValueError as exc:\n                    raise HTTPException(\n                        status_code=400, detail=f"Invalid Agent profile: {exc}"\n                    ) from exc\n                committed.append((profile.id, previous_profile, identity_snapshot))\n                _write_profile_identity_files(profile_store, profile.id, identity_files)\n                _invalidate_imported_profile_runtime(request, profile.id)\n                imported.append(profile.to_dict())\n\n            if not imported:\n                raise HTTPException(400, "文件中没有可导入的有效 Agent")\n        except Exception:\n            rollback_errors: list[str] = []\n            for committed_id, previous_profile, identity_snapshot in reversed(committed):\n                try:\n                    _restore_imported_profile(\n                        profile_store,\n                        committed_id,\n                        previous_profile,\n                        identity_snapshot,\n                    )\n                except Exception as rollback_exc:\n                    rollback_errors.append(f"{committed_id}: {rollback_exc}")\n            if rollback_errors:\n                logger.error(\n                    "[AgentPackage] JSON import rollback incomplete: %s",\n                    "; ".join(rollback_errors),\n                )\n            raise\n\n'''
    start = "        imported = []\n        skipped = []\n"
    end = "        _reload_skills(request)\n"
    if "committed: list[tuple[str, object | None" not in text:
        text = replace_between(text, start, end, transaction, "Hub transactional JSON import")

    path.write_text(text, "utf-8")


def patch_skill_store() -> None:
    path = Path("src/openakita/hub/skill_store_client.py")
    text = path.read_text("utf-8")

    manifest_start = text.find("from ..agents.manifest import (")
    config_marker = "from ..config import settings\n"
    config_pos = text.find(config_marker, manifest_start)
    if manifest_start < 0 or config_pos < 0:
        raise SystemExit("Skill Store import markers changed")
    canonical_manifest = '''from ..agents.manifest import (\n    MAX_PACKAGE_SIZE,\n    MAX_SINGLE_FILE_SIZE,\n    validate_external_skill_source,\n    validate_file_safety,\n)\n'''
    text = text[:manifest_start] + canonical_manifest + text[config_pos:]
    text = re.sub(
        r"(?:from \.\.utils\.atomic_io import atomic_json_write, safe_write\n)+",
        "from ..utils.atomic_io import atomic_json_write, safe_write\n",
        text,
        count=1,
    )

    write_origin = '''    @staticmethod\n    def _write_origin(skill_dir: Path, install_url: str) -> None:\n        """Persist mandatory provenance before a staged Skill becomes active."""\n        origin = {\n            "source": install_url,\n            "type": "platform_store",\n            "installed_at": datetime.now(UTC).isoformat(),\n        }\n        skill_md = skill_dir / "SKILL.md"\n        if skill_md.exists():\n            try:\n                import yaml\n\n                match = re.match(\n                    r"^---\\s*\\n(.*?)\\n---",\n                    skill_md.read_text("utf-8"),\n                    re.DOTALL,\n                )\n                if match:\n                    frontmatter = yaml.safe_load(match.group(1)) or {}\n                    if frontmatter.get("version"):\n                        origin["version"] = frontmatter["version"]\n            except Exception as exc:\n                logger.debug("Unable to read Skill version metadata: %s", exc)\n        atomic_json_write(\n            skill_dir / ".openakita-origin.json",\n            origin,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n        safe_write(\n            skill_dir / ".openakita-source",\n            install_url,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n\n'''
    text = replace_between(
        text,
        "    @staticmethod\n    def _write_origin(skill_dir: Path, install_url: str) -> None:\n",
        "    async def install_skill(\n",
        write_origin,
        "Skill Store provenance",
    )

    zip_func_start = text.find("    async def _install_via_zip_fallback(")
    zip_func_end = text.find("    @staticmethod\n    def _replace_skill_directory", zip_func_start)
    if zip_func_start < 0 or zip_func_end < 0:
        raise SystemExit("Skill Store ZIP fallback markers changed")
    zip_func = text[zip_func_start:zip_func_end]
    old_extract_start = zip_func.find("            with zipfile.ZipFile(io.BytesIO(data)) as zf:\n")
    old_extract_end = zip_func.find("\n            children = list(tmp_parent.iterdir())", old_extract_start)
    if old_extract_start < 0 or old_extract_end < 0:
        raise SystemExit("Skill Store ZIP extraction marker changed")
    safe_extract = '''            with zipfile.ZipFile(io.BytesIO(data)) as zf:\n                total = 0\n                seen: set[str] = set()\n                for info in zf.infolist():\n                    errors = validate_file_safety(info.filename)\n                    if errors:\n                        raise RuntimeError(\n                            f"Unsafe GitHub Skill ZIP member: {'; '.join(errors)}"\n                        )\n                    key = "/".join(\n                        part.rstrip(" .").casefold()\n                        for part in info.filename.replace("\\\\", "/").split("/")\n                    )\n                    if key in seen:\n                        raise RuntimeError(\n                            f"Duplicate GitHub Skill ZIP member: {info.filename}"\n                        )\n                    seen.add(key)\n                    if info.file_size > MAX_SINGLE_FILE_SIZE:\n                        raise RuntimeError(\n                            f"GitHub Skill ZIP member too large: {info.filename}"\n                        )\n                    total += info.file_size\n                    if total > MAX_PACKAGE_SIZE:\n                        raise RuntimeError("GitHub Skill ZIP expands beyond safety limit")\n                    if info.external_attr >> 16 & 0o120000 == 0o120000:\n                        raise RuntimeError(\n                            f"GitHub Skill ZIP symlink not allowed: {info.filename}"\n                        )\n                bad_member = zf.testzip()\n                if bad_member is not None:\n                    raise RuntimeError(f"Corrupt GitHub Skill ZIP member: {bad_member}")\n                zf.extractall(tmp_parent)\n'''
    zip_func = zip_func[:old_extract_start] + safe_extract + zip_func[old_extract_end:]
    text = text[:zip_func_start] + zip_func + text[zip_func_end:]

    copy_method = '''    @staticmethod\n    def _copy_skill_tree(source: Path, target: Path) -> None:\n        """Copy a Skill tree without Git metadata, symlinks or oversized payloads."""\n        target.mkdir(parents=True, exist_ok=True)\n        total = 0\n        for item in source.rglob("*"):\n            rel = item.relative_to(source)\n            if ".git" in rel.parts:\n                continue\n            if item.is_symlink():\n                raise RuntimeError(f"Skill symlink not allowed: {item}")\n            dest = target / rel\n            if item.is_dir():\n                dest.mkdir(parents=True, exist_ok=True)\n                continue\n            if not item.is_file():\n                continue\n            size = item.stat().st_size\n            if size > MAX_SINGLE_FILE_SIZE:\n                raise RuntimeError(f"Skill file too large: {item}")\n            total += size\n            if total > MAX_PACKAGE_SIZE:\n                raise RuntimeError("Skill tree exceeds safety limit")\n            dest.parent.mkdir(parents=True, exist_ok=True)\n            with item.open("rb") as src, dest.open("wb") as out:\n                shutil.copyfileobj(src, out, length=1024 * 1024)\n\n'''
    text = replace_between(
        text,
        "    @staticmethod\n    def _copy_skill_tree(source: Path, target: Path) -> None:\n",
        "    @staticmethod\n    def _extract_skill_from_repo",
        copy_method,
        "Skill Store safe tree copy",
    )

    extract_method = '''    @staticmethod\n    def _extract_skill_from_repo(tmp_dir: Path, skill_name: str, skill_dir: Path) -> bool:\n        """Extract only a directory that actually contains a Skill definition."""\n        skill_md_at_root = tmp_dir / "SKILL.md"\n        if skill_md_at_root.exists():\n            SkillStoreClient._copy_skill_tree(tmp_dir, skill_dir)\n            return True\n\n        candidates = [\n            skill_name,\n            f"skills/{skill_name}",\n            f"tools/{skill_name}",\n            f"packages/{skill_name}",\n        ]\n        seen: set[str] = set()\n        for rel in candidates:\n            rel_norm = rel.replace("\\\\", "/").strip("/")\n            if not rel_norm or rel_norm in seen:\n                continue\n            seen.add(rel_norm)\n            candidate = tmp_dir / rel_norm\n            if candidate.is_dir() and (candidate / "SKILL.md").exists():\n                SkillStoreClient._copy_skill_tree(candidate, skill_dir)\n                return True\n\n        for skill_md in tmp_dir.rglob("SKILL.md"):\n            if skill_md.parent.name == skill_name:\n                SkillStoreClient._copy_skill_tree(skill_md.parent, skill_dir)\n                return True\n\n        return False\n\n'''
    text = replace_between(
        text,
        "    @staticmethod\n    def _extract_skill_from_repo(tmp_dir: Path, skill_name: str, skill_dir: Path) -> bool:\n",
        "    async def rate(\n",
        extract_method,
        "Skill Store require SKILL.md",
    )

    path.write_text(text, "utf-8")


def patch_packager() -> None:
    path = Path("src/openakita/agents/packager.py")
    text = path.read_text("utf-8")

    text = replace_once(
        text,
        '''            profile_data = json.loads(zf.read("profile.json"))\n\n            profile_id = manifest.id\n''',
        '''            profile_data = json.loads(zf.read("profile.json"))\n            if not isinstance(profile_data, dict):\n                raise PackageError("Invalid profile.json: root must be an object")\n\n            profile_id = manifest.id\n''',
        "Agent package profile JSON root",
    )

    canonical_helpers = '''    def _snapshot_identity_files(\n        self, zf: zipfile.ZipFile, profile_id: str\n    ) -> dict[str, bytes | None]:\n        members = {\n            Path(name).name\n            for name in zf.namelist()\n            if name.startswith("identity/")\n            and not name.endswith("/")\n            and Path(name).name in PROFILE_IDENTITY_FILENAMES\n        }\n        if not members:\n            return {}\n        identity_dir = self.profile_store.get_profile_dir(profile_id) / "identity"\n        snapshot: dict[str, bytes | None] = {}\n        for filename in members:\n            target = identity_dir / filename\n            snapshot[filename] = target.read_bytes() if target.is_file() else None\n        return snapshot\n\n    def _snapshot_skill_targets(\n        self, manifest: AgentManifest, transaction_dir: Path\n    ) -> dict[Path, Path | None]:\n        import shutil\n\n        targets: list[Path] = [\n            self.skills_dir / "custom" / skill_name\n            for skill_name in manifest.bundled_skills\n        ]\n        targets.extend(\n            self.skills_dir / "community" / ref.id\n            for ref in manifest.required_external_skills\n        )\n        snapshot: dict[Path, Path | None] = {}\n        for index, target in enumerate(dict.fromkeys(targets)):\n            if target.exists() and not target.is_dir():\n                raise PackageError(f"Skill target is not a directory: {target}")\n            if not target.exists():\n                snapshot[target] = None\n                continue\n            backup = transaction_dir / f"skill-{index}"\n            shutil.copytree(target, backup, symlinks=True)\n            snapshot[target] = backup\n        return snapshot\n\n    @staticmethod\n    def _restore_skill_targets(snapshot: dict[Path, Path | None]) -> None:\n        import shutil\n\n        for target, backup in reversed(list(snapshot.items())):\n            if target.exists():\n                if target.is_dir():\n                    shutil.rmtree(target)\n                else:\n                    target.unlink()\n            if backup is not None and backup.exists():\n                target.parent.mkdir(parents=True, exist_ok=True)\n                backup.replace(target)\n\n    def _restore_profile_after_failed_install(\n        self,\n        profile_id: str,\n        previous_profile: AgentProfile | None,\n        identity_snapshot: dict[str, bytes | None],\n    ) -> None:\n        if previous_profile is None:\n            self.profile_store.delete(profile_id)\n            return\n\n        self.profile_store.save(previous_profile)\n        identity_dir = self.profile_store.ensure_profile_dir(profile_id) / "identity"\n        for filename, previous in identity_snapshot.items():\n            target = identity_dir / filename\n            if previous is None:\n                target.unlink(missing_ok=True)\n            else:\n                safe_write_bytes(\n                    target,\n                    previous,\n                    backup=False,\n                    fsync=True,\n                    allow_fallback=False,\n                )\n\n'''
    first = text.find("    def _snapshot_identity_files(\n")
    install_identity = text.find("    def _install_identity_files(", first)
    if first < 0 or install_identity < 0:
        raise SystemExit("Agent installer transaction helper markers changed")
    text = text[:first] + canonical_helpers + text[install_identity:]

    identity_method = '''    def _install_identity_files(self, zf: zipfile.ZipFile, profile_id: str) -> None:\n        identity_members = [\n            name\n            for name in zf.namelist()\n            if name.startswith("identity/")\n            and not name.endswith("/")\n            and Path(name).name in PROFILE_IDENTITY_FILENAMES\n        ]\n        if not identity_members:\n            return\n\n        profile_dir = self.profile_store.ensure_profile_dir(profile_id)\n        identity_dir = profile_dir / "identity"\n        identity_dir.mkdir(parents=True, exist_ok=True)\n        for member in identity_members:\n            filename = Path(member).name\n            try:\n                content = zf.read(member).decode("utf-8")\n                safe_write(\n                    identity_dir / filename,\n                    content,\n                    backup=True,\n                    fsync=True,\n                    allow_fallback=False,\n                )\n            except Exception as exc:\n                raise PackageError(\n                    f"Failed to install identity file {member!r} for profile {profile_id}: {exc}"\n                ) from exc\n\n'''
    text = replace_between(
        text,
        "    def _install_identity_files(self, zf: zipfile.ZipFile, profile_id: str) -> None:\n",
        "    def _validate_file(self, package_path: Path) -> None:\n",
        identity_method,
        "Agent installer identity transaction",
    )

    path.write_text(text, "utf-8")


def patch_native_runtime() -> None:
    path = Path("src/openakita/hermes/native_runtime.py")
    text = path.read_text("utf-8")

    text = replace_once(
        text,
        '''            result = await asyncio.to_thread(_execute)\n        return {\n''',
        '''            worker_task = asyncio.create_task(asyncio.to_thread(_execute))\n            cancelled: asyncio.CancelledError | None = None\n            result: dict[str, Any] | None = None\n            try:\n                result = await asyncio.shield(worker_task)\n            except asyncio.CancelledError as exc:\n                cancelled = exc\n            finally:\n                if not worker_task.done():\n                    try:\n                        result = await asyncio.shield(worker_task)\n                    except asyncio.CancelledError:\n                        result = await worker_task\n                elif result is None and not worker_task.cancelled():\n                    result = worker_task.result()\n                if cancelled is not None:\n                    raise cancelled\n            if result is None:\n                raise NativeHermesExecutionError("Hermes conversation produced no result")\n        return {\n''',
        "Native Hermes non-stream cancellation",
    )

    text = replace_once(
        text,
        "            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()\n",
        "            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=128)\n            stream_closed = threading.Event()\n",
        "Native Hermes bounded queue",
    )
    text = replace_once(
        text,
        "            emitted_delta = threading.Event()\n\n            def _on_delta(delta: Any) -> None:\n",
        '''            emitted_delta = threading.Event()\n\n            def _enqueue(event: dict[str, Any] | None) -> None:\n                if stream_closed.is_set():\n                    return\n                future = asyncio.run_coroutine_threadsafe(queue.put(event), loop)\n                while not stream_closed.is_set():\n                    try:\n                        future.result(timeout=0.5)\n                        return\n                    except TimeoutError:\n                        continue\n                    except Exception:\n                        return\n                future.cancel()\n\n            def _on_delta(delta: Any) -> None:\n''',
        "Native Hermes stream backpressure helper",
    )
    text = replace_once(
        text,
        '''                    loop.call_soon_threadsafe(\n                        queue.put_nowait,\n                        {"type": "text_delta", "content": text, "runtime": "native"},\n                    )\n''',
        '''                    _enqueue(\n                        {"type": "text_delta", "content": text, "runtime": "native"}\n                    )\n''',
        "Native Hermes delta backpressure",
    )
    text = replace_once(
        text,
        '''                        loop.call_soon_threadsafe(\n                            queue.put_nowait,\n                            {"type": "final", "content": str(final), "runtime": "native"},\n                        )\n                except NativeHermesUnavailable as exc:\n                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error_kind": "unavailable", "error": str(exc), "runtime": "native"})\n                except Exception as exc:\n                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error_kind": "execution", "error": str(exc), "runtime": "native"})\n                finally:\n                    loop.call_soon_threadsafe(queue.put_nowait, None)\n''',
        '''                        _enqueue(\n                            {"type": "final", "content": str(final), "runtime": "native"}\n                        )\n                except NativeHermesUnavailable as exc:\n                    _enqueue(\n                        {\n                            "type": "error",\n                            "error_kind": "unavailable",\n                            "error": str(exc),\n                            "runtime": "native",\n                        }\n                    )\n                except Exception as exc:\n                    _enqueue(\n                        {\n                            "type": "error",\n                            "error_kind": "execution",\n                            "error": str(exc),\n                            "runtime": "native",\n                        }\n                    )\n                finally:\n                    _enqueue(None)\n''',
        "Native Hermes worker backpressure",
    )
    text = replace_once(
        text,
        '''            finally:\n                if not worker_task.done():\n''',
        '''            finally:\n                stream_closed.set()\n                if not worker_task.done():\n''',
        "Native Hermes stream cancellation signal",
    )

    path.write_text(text, "utf-8")


def patch_shared_gateway() -> None:
    path = Path("deploy/hermes/shared_gateway.py")
    text = path.read_text("utf-8")

    prune = '''    def prune_dead(self) -> None:\n        for profile_id, child in list(self.children.items()):\n            if child.process.poll() is not None:\n                self.children.pop(profile_id, None)\n                self._dispose(child)\n                lock = self.locks.get(profile_id)\n                if lock is not None and not lock.locked():\n                    self.locks.pop(profile_id, None)\n\n    def _drop_idle_lock(self, profile_id: str, lock: asyncio.Lock) -> None:\n        current = self.locks.get(profile_id)\n        if current is lock and not lock.locked() and profile_id not in self.children:\n            self.locks.pop(profile_id, None)\n\n'''
    text = replace_between(
        text,
        "    def prune_dead(self) -> None:\n",
        "    async def ensure(self, profile_id: str) -> Child:\n",
        prune,
        "Shared Hermes duplicate lock cleanup",
    )

    text = replace_once(
        text,
        '''            if len(self.children) >= MAX_CHILDREN:\n                raise HTTPException(status_code=503, detail="共享实例已达到最大 Agent 数")\n''',
        '''            if len(self.children) >= MAX_CHILDREN:\n                asyncio.get_running_loop().call_soon(\n                    self._drop_idle_lock, profile_id, lock\n                )\n                raise HTTPException(status_code=503, detail="共享实例已达到最大 Agent 数")\n''',
        "Shared Hermes max-child lock cleanup",
    )
    text = replace_once(
        text,
        '''            if RUNTIME_ROOT not in home.parents:\n                raise HTTPException(status_code=400, detail="invalid Agent id")\n            workspace = home / "workspace"\n            workspace.mkdir(parents=True, exist_ok=True)\n            port = free_port(profile_id)\n''',
        '''            if RUNTIME_ROOT not in home.parents:\n                shutil.rmtree(home, ignore_errors=True)\n                asyncio.get_running_loop().call_soon(\n                    self._drop_idle_lock, profile_id, lock\n                )\n                raise HTTPException(status_code=400, detail="invalid Agent id")\n            workspace = home / "workspace"\n            workspace.mkdir(parents=True, exist_ok=True)\n            try:\n                port = free_port(profile_id)\n            except Exception:\n                shutil.rmtree(home, ignore_errors=True)\n                asyncio.get_running_loop().call_soon(\n                    self._drop_idle_lock, profile_id, lock\n                )\n                raise\n''',
        "Shared Hermes pre-spawn cleanup",
    )
    text = replace_once(
        text,
        '''            except Exception:\n                log_handle.close()\n                shutil.rmtree(home, ignore_errors=True)\n                raise\n''',
        '''            except Exception:\n                log_handle.close()\n                shutil.rmtree(home, ignore_errors=True)\n                asyncio.get_running_loop().call_soon(\n                    self._drop_idle_lock, profile_id, lock\n                )\n                raise\n''',
        "Shared Hermes spawn lock cleanup",
    )
    text = replace_once(
        text,
        '''                    if process.poll() is not None:\n                        self.children.pop(profile_id, None)\n                        self._dispose(child)\n                        raise HTTPException(status_code=502, detail=f"Hermes Agent {profile_id} 启动失败")\n''',
        '''                    if process.poll() is not None:\n                        self.children.pop(profile_id, None)\n                        self._dispose(child)\n                        asyncio.get_running_loop().call_soon(\n                            self._drop_idle_lock, profile_id, lock\n                        )\n                        raise HTTPException(\n                            status_code=502, detail=f"Hermes Agent {profile_id} 启动失败"\n                        )\n''',
        "Shared Hermes failed-start lock cleanup",
    )
    text = replace_once(
        text,
        '''            self.stop(profile_id)\n            raise HTTPException(status_code=504, detail=f"Hermes Agent {profile_id} 启动超时")\n''',
        '''            self.stop(profile_id)\n            asyncio.get_running_loop().call_soon(\n                self._drop_idle_lock, profile_id, lock\n            )\n            raise HTTPException(status_code=504, detail=f"Hermes Agent {profile_id} 启动超时")\n''',
        "Shared Hermes timeout lock cleanup",
    )

    path.write_text(text, "utf-8")


def patch_windows_data_dir() -> None:
    path = Path("src/openakita/api/routes/windows_connector.py")
    text = path.read_text("utf-8")
    text = replace_once(
        text,
        '''def _data_dir() -> Path:\n    configured = os.environ.get("OPENAKITA_DATA_DIR", "").strip()\n    if configured:\n        return Path(configured).expanduser().resolve()\n    return Path.home() / ".openakita" / "data"\n''',
        '''def _data_dir() -> Path:\n    configured = os.environ.get("OPENAKITA_DATA_DIR", "").strip()\n    if configured:\n        return Path(configured).expanduser().resolve()\n    try:\n        from openakita.config import settings\n\n        return Path(settings.data_dir).resolve()\n    except Exception:\n        return Path.home() / ".openakita" / "data"\n''',
        "Windows Connector durable data dir",
    )
    path.write_text(text, "utf-8")


def main() -> None:
    patch_hub()
    patch_skill_store()
    patch_packager()
    patch_native_runtime()
    patch_shared_gateway()
    patch_windows_data_dir()


if __name__ == "__main__":
    main()
