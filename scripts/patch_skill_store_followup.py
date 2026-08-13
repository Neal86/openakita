from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    path = Path("src/openakita/hub/skill_store_client.py")
    replace_exact(
        path,
        '''    @staticmethod\n    def _write_origin(skill_dir: Path, install_url: str) -> None:\n        """Write provenance files to track skill source."""\n        try:\n            origin = {\n                "source": install_url,\n                "type": "platform_store",\n                "installed_at": datetime.now(UTC).isoformat(),\n            }\n            skill_md = skill_dir / "SKILL.md"\n            if skill_md.exists():\n                import re\n\n                import yaml\n\n                m = re.match(r"^---\\s*\\n(.*?)\\n---", skill_md.read_text("utf-8"), re.DOTALL)\n                if m:\n                    fm = yaml.safe_load(m.group(1)) or {}\n                    if fm.get("version"):\n                        origin["version"] = fm["version"]\n            atomic_json_write(\n                skill_dir / ".openakita-origin.json",\n                origin,\n                backup=True,\n                fsync=True,\n                allow_fallback=False,\n            )\n            # Also write .openakita-source for compatibility with bridge/frontend matching\n            safe_write(\n                skill_dir / ".openakita-source",\n                install_url,\n                backup=True,\n                fsync=True,\n                allow_fallback=False,\n            )\n        except Exception as e:\n            logger.debug(f"Failed to write origin tracking: {e}")\n''',
        '''    @staticmethod\n    def _write_origin(skill_dir: Path, install_url: str) -> None:\n        """Write mandatory provenance metadata into a prepared staging Skill."""\n        origin = {\n            "source": install_url,\n            "type": "platform_store",\n            "installed_at": datetime.now(UTC).isoformat(),\n        }\n        skill_md = skill_dir / "SKILL.md"\n        if skill_md.exists():\n            try:\n                import yaml\n\n                match = re.match(\n                    r"^---\\s*\\n(.*?)\\n---",\n                    skill_md.read_text("utf-8"),\n                    re.DOTALL,\n                )\n                if match:\n                    frontmatter = yaml.safe_load(match.group(1)) or {}\n                    if frontmatter.get("version"):\n                        origin["version"] = frontmatter["version"]\n            except Exception as exc:\n                logger.debug("Unable to read Skill version metadata: %s", exc)\n        atomic_json_write(\n            skill_dir / ".openakita-origin.json",\n            origin,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n        safe_write(\n            skill_dir / ".openakita-source",\n            install_url,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n''',
        "mandatory provenance write",
    )
    replace_exact(
        path,
        '''            with zipfile.ZipFile(io.BytesIO(data)) as zf:\n                for name in zf.namelist():\n                    normalized = os.path.normpath(name)\n                    if name.startswith("/") or name.startswith("\\\\") or normalized.startswith(".."):\n                        raise RuntimeError(f"Zip Slip detected: dangerous member '{name}'")\n                zf.extractall(tmp_parent)\n''',
        '''            with zipfile.ZipFile(io.BytesIO(data)) as zf:\n                total = 0\n                seen: set[str] = set()\n                for info in zf.infolist():\n                    errors = validate_file_safety(info.filename)\n                    if errors:\n                        raise RuntimeError(\n                            f"Unsafe GitHub Skill ZIP member: {'; '.join(errors)}"\n                        )\n                    key = "/".join(\n                        part.rstrip(" .").casefold()\n                        for part in info.filename.replace("\\\\", "/").split("/")\n                    )\n                    if key in seen:\n                        raise RuntimeError(\n                            f"Duplicate GitHub Skill ZIP member: {info.filename}"\n                        )\n                    seen.add(key)\n                    if info.file_size > MAX_SINGLE_FILE_SIZE:\n                        raise RuntimeError(\n                            f"GitHub Skill ZIP member too large: {info.filename}"\n                        )\n                    total += info.file_size\n                    if total > MAX_PACKAGE_SIZE:\n                        raise RuntimeError("GitHub Skill ZIP expands beyond safety limit")\n                    if info.external_attr >> 16 & 0o120000 == 0o120000:\n                        raise RuntimeError(\n                            f"GitHub Skill ZIP symlink not allowed: {info.filename}"\n                        )\n                bad_member = zf.testzip()\n                if bad_member is not None:\n                    raise RuntimeError(f"Corrupt GitHub Skill ZIP member: {bad_member}")\n                zf.extractall(tmp_parent)\n''',
        "GitHub fallback archive validation",
    )
    replace_exact(
        path,
        '''        for item in source.rglob("*"):\n            if item.is_symlink():\n                raise RuntimeError(f"Skill symlink not allowed: {item}")\n            rel = item.relative_to(source)\n            dest = target / rel\n''',
        '''        for item in source.rglob("*"):\n            rel = item.relative_to(source)\n            if ".git" in rel.parts:\n                continue\n            if item.is_symlink():\n                raise RuntimeError(f"Skill symlink not allowed: {item}")\n            dest = target / rel\n''',
        "ignore Git metadata during safe copy",
    )


if __name__ == "__main__":
    main()
