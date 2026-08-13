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
        '''    return FileResponse(\n        path=str(zip_path),\n        media_type="application/zip",\n        filename=f"agents_batch_{len(exported)}.zip",\n    )\n''',
        '''    from starlette.background import BackgroundTask\n\n    return FileResponse(\n        path=str(zip_path),\n        media_type="application/zip",\n        filename=f"agents_batch_{len(exported)}.zip",\n        background=BackgroundTask(zip_path.unlink, missing_ok=True),\n    )\n''',
        "batch export cleanup",
    )
    replace_exact(
        path,
        '''        if data.get("format") == "akita-agent-batch":\n            raw_agents = data.get("agents", [])\n        elif isinstance(data.get("profile"), dict):\n            raw_agents = [data]\n        elif data.get("format") == "akita-agent":\n            raw_agents = [{}]\n        else:\n            raise HTTPException(400, "无法识别的 JSON 格式，缺少 profile 或 agents 字段")\n''',
        '''        if data.get("format") == "akita-agent-batch":\n            raw_agents = data.get("agents")\n            if not isinstance(raw_agents, list) or not raw_agents:\n                raise HTTPException(400, "无效的批量 Agent JSON：agents 必须是非空列表")\n        elif data.get("format") == "akita-agent" or "profile" in data:\n            if not isinstance(data.get("profile"), dict) or not data.get("profile"):\n                raise HTTPException(400, "无效的 Agent JSON：缺少有效的 profile")\n            raw_agents = [data]\n        else:\n            raise HTTPException(400, "无法识别的 JSON 格式，缺少 profile 或 agents 字段")\n''',
        "reject malformed JSON package structure",
    )
    replace_exact(
        path,
        '''            _invalidate_imported_profile_runtime(request, profile.id)\n            imported.append(profile.to_dict())\n\n        _reload_skills(request)\n''',
        '''            _invalidate_imported_profile_runtime(request, profile.id)\n            imported.append(profile.to_dict())\n\n        if not imported:\n            raise HTTPException(400, "文件中没有可导入的有效 Agent")\n\n        _reload_skills(request)\n''',
        "reject zero-import success",
    )


if __name__ == "__main__":
    main()
