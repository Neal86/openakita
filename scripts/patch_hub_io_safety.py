from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    path = Path("src/openakita/api/routes/hub.py")

    replace_exact(
        path,
        '''import logging\nimport tempfile\nfrom datetime import datetime\nfrom pathlib import Path\n''',
        '''import logging\nimport tempfile\nimport uuid\nfrom datetime import datetime\nfrom io import BytesIO\nfrom pathlib import Path\n''',
        "hub io imports",
    )

    replace_exact(
        path,
        '''def _get_stores():\n    from openakita.config import settings\n\n    root = Path(settings.project_root)\n\n    from openakita.agents.profile import get_profile_store\n\n    profile_store = get_profile_store()\n\n    skills_dir = Path(settings.skills_path)\n    return profile_store, skills_dir, root\n\n\ndef _read_profile_identity_files''',
        '''def _get_stores():\n    from openakita.config import settings\n\n    root = Path(settings.project_root)\n\n    from openakita.agents.profile import get_profile_store\n\n    profile_store = get_profile_store()\n\n    skills_dir = Path(settings.skills_path)\n    return profile_store, skills_dir, root\n\n\ndef _agent_packages_dir() -> Path:\n    from openakita.config import settings\n\n    directory = Path(settings.data_dir) / "agent_packages"\n    directory.mkdir(parents=True, exist_ok=True)\n    return directory\n\n\ndef _safe_export_path(requested: str, *, default_name: str) -> Path:\n    base = _agent_packages_dir().resolve()\n    relative = Path(requested or default_name)\n    if (\n        relative.is_absolute()\n        or relative.drive\n        or relative.root\n        or ".." in relative.parts\n    ):\n        raise HTTPException(\n            status_code=400,\n            detail="output_path must stay inside the OpenAkita agent_packages directory",\n        )\n    target = (base / relative).resolve()\n    try:\n        target.relative_to(base)\n    except ValueError as exc:\n        raise HTTPException(\n            status_code=400,\n            detail="output_path escapes the OpenAkita agent_packages directory",\n        ) from exc\n    target.parent.mkdir(parents=True, exist_ok=True)\n    return target\n\n\nasync def _read_upload_limited(file: UploadFile, *, limit: int) -> bytes:\n    chunks: list[bytes] = []\n    total = 0\n    while True:\n        chunk = await file.read(1024 * 1024)\n        if not chunk:\n            break\n        total += len(chunk)\n        if total > limit:\n            raise HTTPException(\n                status_code=413,\n                detail=f"Uploaded Agent package exceeds {limit} bytes",\n            )\n        chunks.append(chunk)\n    return b"".join(chunks)\n\n\ndef _read_profile_identity_files''',
        "durable package dir and bounded upload helpers",
    )

    replace_exact(
        path,
        '''    profile_store, skills_dir, root = _get_stores()\n    output_dir = root / "data" / "agent_packages"\n\n    packager = AgentPackager(\n''',
        '''    profile_store, skills_dir, _ = _get_stores()\n    output_dir = _agent_packages_dir()\n\n    packager = AgentPackager(\n''',
        "single export durable directory",
    )

    replace_exact(
        path,
        '''    profile_store, skills_dir, root = _get_stores()\n    output_dir = root / "data" / "agent_packages"\n    output_dir.mkdir(parents=True, exist_ok=True)\n\n    packager = AgentPackager(\n''',
        '''    profile_store, skills_dir, _ = _get_stores()\n    output_dir = _agent_packages_dir()\n\n    packager = AgentPackager(\n''',
        "batch export durable directory",
    )

    replace_exact(
        path,
        '''    zip_path = output_dir / "batch_export.zip"\n    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:\n        for p in exported:\n            zf.write(p, p.name)\n\n    return FileResponse(\n        path=str(zip_path),\n''',
        '''    from openakita.utils.atomic_io import safe_write_bytes\n\n    zip_path = output_dir / f"batch_export_{uuid.uuid4().hex}.zip"\n    payload = BytesIO()\n    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:\n        for p in exported:\n            zf.write(p, p.name)\n    safe_write_bytes(\n        zip_path,\n        payload.getvalue(),\n        backup=False,\n        fsync=True,\n        allow_fallback=False,\n    )\n\n    return FileResponse(\n        path=str(zip_path),\n''',
        "unique atomic batch zip",
    )

    replace_exact(
        path,
        '''    if req.output_path:\n        out = Path(req.output_path)\n        out.parent.mkdir(parents=True, exist_ok=True)\n        out.write_text(_json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")\n        return {"ok": True, "path": str(out)}\n''',
        '''    if req.output_path:\n        from openakita.utils.atomic_io import atomic_json_write\n\n        out = _safe_export_path(req.output_path, default_name=f"{profile.id}.json")\n        atomic_json_write(\n            out,\n            export_data,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n        return {"ok": True, "path": str(out)}\n''',
        "safe single JSON export",
    )

    replace_exact(
        path,
        '''    if req.output_path:\n        out = Path(req.output_path)\n        out.parent.mkdir(parents=True, exist_ok=True)\n        out.write_text(_json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")\n        return {"ok": True, "path": str(out)}\n''',
        '''    if req.output_path:\n        from openakita.utils.atomic_io import atomic_json_write\n\n        out = _safe_export_path(\n            req.output_path,\n            default_name=f"agents_batch_{uuid.uuid4().hex}.json",\n        )\n        atomic_json_write(\n            out,\n            result,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n        return {"ok": True, "path": str(out)}\n''',
        "safe batch JSON export",
    )

    replace_exact(
        path,
        '''    from openakita.agents.profile import AgentProfile\n\n    profile_store, skills_dir, _ = _get_stores()\n    content = await file.read()\n    filename = file.filename or ""\n''',
        '''    from openakita.agents.manifest import MAX_PACKAGE_SIZE\n    from openakita.agents.profile import AgentProfile\n\n    profile_store, skills_dir, _ = _get_stores()\n    content = await _read_upload_limited(file, limit=MAX_PACKAGE_SIZE)\n    filename = file.filename or ""\n''',
        "bounded import upload",
    )

    replace_exact(
        path,
        '''    profile_store, skills_dir, _ = _get_stores()\n\n    with tempfile.NamedTemporaryFile(suffix=".akita-agent", delete=False) as tmp:\n        content = await file.read()\n        tmp.write(content)\n''',
        '''    from openakita.agents.manifest import MAX_PACKAGE_SIZE\n\n    profile_store, skills_dir, _ = _get_stores()\n\n    with tempfile.NamedTemporaryFile(suffix=".akita-agent", delete=False) as tmp:\n        content = await _read_upload_limited(file, limit=MAX_PACKAGE_SIZE)\n        tmp.write(content)\n''',
        "bounded inspect upload",
    )


if __name__ == "__main__":
    main()
