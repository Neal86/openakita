from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    manifest = Path("src/openakita/agents/manifest.py")
    replace_exact(
        manifest,
        '''_SEMVER_PATTERN = re.compile(r"^\\d+\\.\\d+\\.\\d+")\n''',
        '''_SEMVER_PATTERN = re.compile(r"^\\d+\\.\\d+\\.\\d+")\n_SKILL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")\n''',
        "safe skill id pattern",
    )
    replace_exact(
        manifest,
        '''        if self.min_platform_version and not _SEMVER_PATTERN.match(self.min_platform_version):\n            errors.append(f"Invalid min_platform_version: {self.min_platform_version!r}")\n\n        return errors\n''',
        '''        if self.min_platform_version and not _SEMVER_PATTERN.match(self.min_platform_version):\n            errors.append(f"Invalid min_platform_version: {self.min_platform_version!r}")\n\n        for field_name, skill_ids in (\n            ("bundled_skills", self.bundled_skills),\n            ("required_builtin_skills", self.required_builtin_skills),\n        ):\n            if not isinstance(skill_ids, list):\n                errors.append(f"{field_name} must be a list")\n                continue\n            for skill_id in skill_ids:\n                if not isinstance(skill_id, str) or not _SKILL_ID_PATTERN.fullmatch(skill_id):\n                    errors.append(f"Invalid {field_name} id: {skill_id!r}")\n\n        if not isinstance(self.required_external_skills, list):\n            errors.append("required_external_skills must be a list")\n        else:\n            for ref in self.required_external_skills:\n                if not isinstance(ref, ExternalSkillRef):\n                    errors.append(f"Invalid external skill reference: {ref!r}")\n                    continue\n                if not _SKILL_ID_PATTERN.fullmatch(ref.id or ""):\n                    errors.append(f"Invalid required_external_skills id: {ref.id!r}")\n                if not isinstance(ref.source, str) or not ref.source.strip():\n                    errors.append(f"External skill source is required for {ref.id!r}")\n\n        return errors\n''',
        "manifest skill id validation",
    )

    packager = Path("src/openakita/agents/packager.py")
    replace_exact(
        packager,
        '''    def _security_check(self, zf: zipfile.ZipFile) -> None:\n        for info in zf.infolist():\n            errors = validate_file_safety(info.filename)\n            if errors:\n                raise PackageError(f"Security violation: {'; '.join(errors)}")\n            if info.file_size > MAX_SINGLE_FILE_SIZE:\n                raise PackageError(f"File too large: {info.filename} ({info.file_size} bytes)")\n            if info.is_dir():\n                continue\n            if info.external_attr >> 16 & 0o120000 == 0o120000:\n                raise PackageError(f"Symlinks not allowed: {info.filename}")\n''',
        '''    def _security_check(self, zf: zipfile.ZipFile) -> None:\n        total_uncompressed = 0\n        seen_names: set[str] = set()\n        for info in zf.infolist():\n            errors = validate_file_safety(info.filename)\n            if errors:\n                raise PackageError(f"Security violation: {'; '.join(errors)}")\n            normalized_name = info.filename.replace("\\\\", "/")\n            if normalized_name in seen_names:\n                raise PackageError(f"Duplicate ZIP member not allowed: {info.filename}")\n            seen_names.add(normalized_name)\n            if info.file_size > MAX_SINGLE_FILE_SIZE:\n                raise PackageError(f"File too large: {info.filename} ({info.file_size} bytes)")\n            total_uncompressed += info.file_size\n            if total_uncompressed > MAX_PACKAGE_SIZE:\n                raise PackageError(\n                    f"Package expands beyond safety limit: {total_uncompressed} bytes "\n                    f"(max {MAX_PACKAGE_SIZE})"\n                )\n            if info.is_dir():\n                continue\n            if info.external_attr >> 16 & 0o120000 == 0o120000:\n                raise PackageError(f"Symlinks not allowed: {info.filename}")\n        bad_member = zf.testzip()\n        if bad_member is not None:\n            raise PackageError(f"Corrupt ZIP member: {bad_member}")\n''',
        "zip expansion and duplicate member safety",
    )
    replace_exact(
        packager,
        '''            (identity_dir / filename).write_text(content, encoding="utf-8")\n\n    def _validate_file(self, package_path: Path) -> None:\n''',
        '''            from openakita.utils.atomic_io import safe_write\n\n            safe_write(\n                identity_dir / filename,\n                content,\n                backup=True,\n                fsync=True,\n                allow_fallback=False,\n            )\n\n    def _validate_file(self, package_path: Path) -> None:\n''',
        "atomic packaged identity install",
    )
    replace_exact(
        packager,
        '''        (skill_dir / self._ORIGIN_FILE).write_text(\n            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"\n        )\n''',
        '''        from openakita.utils.atomic_io import atomic_json_write\n\n        atomic_json_write(\n            skill_dir / self._ORIGIN_FILE,\n            data,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n''',
        "atomic skill origin write",
    )

    test = Path("tests/api/test_agent_package_safety.py")
    test.write_text(
        '''import json\nimport zipfile\n\nimport pytest\n\nfrom openakita.agents.manifest import AgentManifest, ExternalSkillRef, ManifestAuthor\nfrom openakita.agents.packager import AgentInstaller, PackageError\nfrom openakita.agents.profile import ProfileStore\n\n\n@pytest.mark.parametrize(\n    "skill_id",\n    ["/tmp/escape", "../escape", "..\\\\escape", "C:\\\\escape", "bad/name"],\n)\ndef test_manifest_rejects_path_like_skill_ids(skill_id):\n    manifest = AgentManifest(\n        id="safe-agent",\n        name="Safe",\n        description="Safe agent",\n        author=ManifestAuthor(name="tester"),\n        bundled_skills=[skill_id],\n    )\n    assert any("bundled_skills" in error for error in manifest.validate())\n\n\ndef test_manifest_rejects_unsafe_external_skill_id():\n    manifest = AgentManifest(\n        id="safe-agent",\n        name="Safe",\n        description="Safe agent",\n        author=ManifestAuthor(name="tester"),\n        required_external_skills=[ExternalSkillRef(id="/tmp/escape", source="owner/repo")],\n    )\n    assert any("required_external_skills" in error for error in manifest.validate())\n\n\ndef test_installer_rejects_absolute_bundled_skill_before_write(tmp_path):\n    package = tmp_path / "unsafe.akita-agent"\n    manifest = {\n        "spec_version": "1.1",\n        "id": "safe-agent",\n        "name": "Safe",\n        "description": "Safe agent",\n        "version": "1.0.0",\n        "author": {"name": "tester"},\n        "bundled_skills": ["/tmp/escape"],\n    }\n    profile = {"id": "safe-agent", "name": "Safe", "description": "Safe agent"}\n    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:\n        archive.writestr("manifest.json", json.dumps(manifest))\n        archive.writestr("profile.json", json.dumps(profile))\n        archive.writestr("skills//tmp/escape/SKILL.md", "# unsafe")\n\n    skills = tmp_path / "skills"\n    installer = AgentInstaller(ProfileStore(tmp_path / "agents"), skills)\n    with pytest.raises(PackageError, match="Invalid manifest"):\n        installer.install(package)\n    assert not (tmp_path / "escape").exists()\n\n\ndef test_security_check_rejects_excessive_total_expansion(tmp_path, monkeypatch):\n    from openakita.agents import packager as packager_module\n\n    package = tmp_path / "bomb.akita-agent"\n    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:\n        archive.writestr("manifest.json", "{}")\n        archive.writestr("profile.json", "{}")\n        archive.writestr("a.txt", "a" * 16)\n        archive.writestr("b.txt", "b" * 16)\n\n    monkeypatch.setattr(packager_module, "MAX_PACKAGE_SIZE", 20)\n    installer = AgentInstaller(ProfileStore(tmp_path / "agents"), tmp_path / "skills")\n    with zipfile.ZipFile(package, "r") as archive:\n        with pytest.raises(PackageError, match="expands beyond safety limit"):\n            installer._security_check(archive)\n\n\ndef test_security_check_rejects_duplicate_members(tmp_path):\n    package = tmp_path / "duplicate.akita-agent"\n    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:\n        archive.writestr("manifest.json", "{}")\n        archive.writestr("profile.json", "{}")\n        archive.writestr("same.txt", "first")\n        archive.writestr("same.txt", "second")\n\n    installer = AgentInstaller(ProfileStore(tmp_path / "agents"), tmp_path / "skills")\n    with zipfile.ZipFile(package, "r") as archive:\n        with pytest.raises(PackageError, match="Duplicate ZIP member"):\n            installer._security_check(archive)\n''',
        "utf-8",
    )


if __name__ == "__main__":
    main()
