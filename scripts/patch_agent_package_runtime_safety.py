from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    path = Path("src/openakita/agents/packager.py")

    replace_exact(
        path,
        '''    validate_file_safety,\n)\nfrom .profile import AgentProfile, ProfileStore\n''',
        '''    validate_external_skill_source,\n    validate_file_safety,\n)\nfrom .profile import AgentProfile, ProfileStore\nfrom openakita.utils.atomic_io import atomic_json_write, safe_write, safe_write_bytes\n''',
        "atomic io and external source imports",
    )

    replace_exact(
        path,
        '''        for skill_name in candidate_skills or []:\n            skill_path = self._find_skill(skill_name)\n''',
        '''        for skill_name in candidate_skills or []:\n            if not isinstance(skill_name, str) or not re.fullmatch(\n                r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", skill_name\n            ):\n                raise PackageError(f"Unsafe skill identifier: {skill_name!r}")\n            skill_path = self._find_skill(skill_name)\n''',
        "validate local skill ids before path joins",
    )

    replace_exact(
        path,
        '''                        if file.is_file():\n                            arcname = f"skills/{skill_name}/{file.relative_to(skill_path)}"\n                            zf.write(file, arcname)\n''',
        '''                        if file.is_symlink():\n                            raise PackageError(f"Symlinks not allowed in bundled skill: {file}")\n                        if file.is_file():\n                            if file.stat().st_size > MAX_SINGLE_FILE_SIZE:\n                                raise PackageError(\n                                    f"File too large: {file} ({file.stat().st_size} bytes)"\n                                )\n                            arcname = f"skills/{skill_name}/{file.relative_to(skill_path)}"\n                            zf.write(file, arcname)\n''',
        "reject local skill symlinks",
    )

    replace_exact(
        path,
        '''        self.output_dir.mkdir(parents=True, exist_ok=True)\n        output_path = self.output_dir / f"{slug_id}.akita-agent"\n        output_path.write_bytes(buf.getvalue())\n''',
        '''        self.output_dir.mkdir(parents=True, exist_ok=True)\n        output_path = self.output_dir / f"{slug_id}.akita-agent"\n        safe_write_bytes(\n            output_path,\n            buf.getvalue(),\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n''',
        "atomic package output",
    )

    replace_exact(
        path,
        '''            (identity_dir / filename).write_text(content, encoding="utf-8")\n\n    def _validate_file(self, package_path: Path) -> None:\n''',
        '''            safe_write(\n                identity_dir / filename,\n                content,\n                backup=True,\n                fsync=True,\n                allow_fallback=False,\n            )\n\n    def _validate_file(self, package_path: Path) -> None:\n''',
        "atomic packaged identity install",
    )

    replace_exact(
        path,
        '''    def _security_check(self, zf: zipfile.ZipFile) -> None:\n        for info in zf.infolist():\n            errors = validate_file_safety(info.filename)\n            if errors:\n                raise PackageError(f"Security violation: {'; '.join(errors)}")\n            if info.file_size > MAX_SINGLE_FILE_SIZE:\n                raise PackageError(f"File too large: {info.filename} ({info.file_size} bytes)")\n            if info.is_dir():\n                continue\n            if info.external_attr >> 16 & 0o120000 == 0o120000:\n                raise PackageError(f"Symlinks not allowed: {info.filename}")\n''',
        '''    def _security_check(self, zf: zipfile.ZipFile) -> None:\n        total_uncompressed = 0\n        seen_names: set[str] = set()\n        for info in zf.infolist():\n            errors = validate_file_safety(info.filename)\n            if errors:\n                raise PackageError(f"Security violation: {'; '.join(errors)}")\n            normalized_name = info.filename.replace("\\\\", "/")\n            if normalized_name in seen_names:\n                raise PackageError(f"Duplicate ZIP member not allowed: {info.filename}")\n            seen_names.add(normalized_name)\n            if info.file_size > MAX_SINGLE_FILE_SIZE:\n                raise PackageError(f"File too large: {info.filename} ({info.file_size} bytes)")\n            total_uncompressed += info.file_size\n            if total_uncompressed > MAX_PACKAGE_SIZE:\n                raise PackageError(\n                    f"Package expands beyond safety limit: {total_uncompressed} bytes "\n                    f"(max {MAX_PACKAGE_SIZE})"\n                )\n            if info.is_dir():\n                continue\n            if info.external_attr >> 16 & 0o120000 == 0o120000:\n                raise PackageError(f"Symlinks not allowed: {info.filename}")\n        bad_member = zf.testzip()\n        if bad_member is not None:\n            raise PackageError(f"Corrupt ZIP member: {bad_member}")\n''',
        "zip expansion duplicate and CRC safety",
    )

    replace_exact(
        path,
        '''        (skill_dir / self._ORIGIN_FILE).write_text(\n            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"\n        )\n''',
        '''        atomic_json_write(\n            skill_dir / self._ORIGIN_FILE,\n            data,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n''',
        "atomic skill origin write",
    )

    replace_exact(
        path,
        '''            target_dir = custom_skills_dir / skill_name\n            target_dir.mkdir(parents=True, exist_ok=True)\n\n            for filename in skill_files:\n                rel_path = filename[len(skill_prefix) :]\n                target_file = target_dir / rel_path\n                target_file.parent.mkdir(parents=True, exist_ok=True)\n                target_file.write_bytes(zf.read(filename))\n\n            self._write_origin(\n                target_dir,\n                source="bundled",\n                version=incoming_ver,\n                origin_type="bundled",\n                agent_id=agent_id,\n            )\n''',
        '''            import tempfile\n\n            target_dir = custom_skills_dir / skill_name\n            with tempfile.TemporaryDirectory(\n                dir=custom_skills_dir, prefix=f".{skill_name}.stage-"\n            ) as stage_root:\n                staging_dir = Path(stage_root) / "skill"\n                staging_dir.mkdir(parents=True, exist_ok=True)\n                for filename in skill_files:\n                    rel_path = filename[len(skill_prefix) :]\n                    target_file = staging_dir / rel_path\n                    target_file.parent.mkdir(parents=True, exist_ok=True)\n                    safe_write_bytes(\n                        target_file,\n                        zf.read(filename),\n                        backup=False,\n                        fsync=True,\n                        allow_fallback=False,\n                    )\n\n                self._write_origin(\n                    staging_dir,\n                    source="bundled",\n                    version=incoming_ver,\n                    origin_type="bundled",\n                    agent_id=agent_id,\n                )\n                self._replace_skill_directory(staging_dir, target_dir)\n''',
        "transactional bundled skill install",
    )

    replace_exact(
        path,
        '''    def _install_from_source(self, skill_id: str, source: str) -> Path:\n        """Fetch a skill from its source and return the install dir.\n\n        Best-effort GitHub clone implementation.\n        """\n        import subprocess\n        import tempfile\n\n        if "@" in source:\n''',
        '''    def _replace_skill_directory(self, staging_dir: Path, target_dir: Path) -> None:\n        """Swap a fully prepared skill directory into place with rollback."""\n        import shutil\n        import uuid\n\n        backup_dir = target_dir.with_name(f".{target_dir.name}.backup-{uuid.uuid4().hex}")\n        had_existing = target_dir.exists()\n        if had_existing:\n            target_dir.replace(backup_dir)\n        try:\n            staging_dir.replace(target_dir)\n        except Exception:\n            if had_existing and backup_dir.exists() and not target_dir.exists():\n                backup_dir.replace(target_dir)\n            raise\n        else:\n            if backup_dir.exists():\n                shutil.rmtree(backup_dir)\n\n    def _install_from_source(self, skill_id: str, source: str) -> Path:\n        """Fetch a skill from an approved GitHub source and return the install dir."""\n        import subprocess\n        import tempfile\n\n        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", skill_id):\n            raise PackageError(f"Unsafe external skill identifier: {skill_id!r}")\n        if not validate_external_skill_source(source):\n            raise PackageError(f"Unsafe external skill source: {source!r}")\n\n        if "@" in source:\n''',
        "external source validation and directory swap helper",
    )

    replace_exact(
        path,
        '''        target_dir = self.skills_dir / "community" / skill_id\n        target_dir.mkdir(parents=True, exist_ok=True)\n\n        with tempfile.TemporaryDirectory() as tmpdir:\n            subprocess.run(\n                ["git", "clone", "--depth=1", repo_url, tmpdir],\n                check=True,\n                capture_output=True,\n                timeout=60,\n            )\n\n            src_skill = Path(tmpdir) / skill_name\n            if not src_skill.exists():\n                src_skill = Path(tmpdir) / "skills" / skill_name\n            if not src_skill.exists():\n                raise FileNotFoundError(f"Skill directory '{skill_name}' not found in {repo_url}")\n\n            skill_md = src_skill / "SKILL.md"\n            if not skill_md.exists():\n                raise FileNotFoundError(f"SKILL.md not found in {src_skill}")\n\n            for file in src_skill.rglob("*"):\n                if file.is_file():\n                    dest = target_dir / file.relative_to(src_skill)\n                    dest.parent.mkdir(parents=True, exist_ok=True)\n                    dest.write_bytes(file.read_bytes())\n\n        return target_dir\n''',
        '''        community_dir = self.skills_dir / "community"\n        community_dir.mkdir(parents=True, exist_ok=True)\n        target_dir = community_dir / skill_id\n\n        with tempfile.TemporaryDirectory() as tmpdir:\n            subprocess.run(\n                ["git", "clone", "--depth=1", repo_url, tmpdir],\n                check=True,\n                capture_output=True,\n                timeout=60,\n            )\n\n            src_skill = Path(tmpdir) / skill_name\n            if not src_skill.exists():\n                src_skill = Path(tmpdir) / "skills" / skill_name\n            if not src_skill.exists():\n                raise FileNotFoundError(f"Skill directory '{skill_name}' not found in {repo_url}")\n\n            skill_md = src_skill / "SKILL.md"\n            if not skill_md.exists():\n                raise FileNotFoundError(f"SKILL.md not found in {src_skill}")\n\n            with tempfile.TemporaryDirectory(\n                dir=community_dir, prefix=f".{skill_id}.stage-"\n            ) as stage_root:\n                staging_dir = Path(stage_root) / "skill"\n                staging_dir.mkdir(parents=True, exist_ok=True)\n                total_size = 0\n                for file in src_skill.rglob("*"):\n                    if file.is_symlink():\n                        raise PackageError(f"Symlinks not allowed in external skill: {file}")\n                    if not file.is_file():\n                        continue\n                    size = file.stat().st_size\n                    if size > MAX_SINGLE_FILE_SIZE:\n                        raise PackageError(f"External skill file too large: {file} ({size} bytes)")\n                    total_size += size\n                    if total_size > MAX_PACKAGE_SIZE:\n                        raise PackageError(\n                            f"External skill exceeds safety limit: {total_size} bytes"\n                        )\n                    dest = staging_dir / file.relative_to(src_skill)\n                    dest.parent.mkdir(parents=True, exist_ok=True)\n                    safe_write_bytes(\n                        dest,\n                        file.read_bytes(),\n                        backup=False,\n                        fsync=True,\n                        allow_fallback=False,\n                    )\n\n                self._replace_skill_directory(staging_dir, target_dir)\n\n        return target_dir\n''',
        "transactional external skill install",
    )


if __name__ == "__main__":
    main()
