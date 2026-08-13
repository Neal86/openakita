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


if __name__ == "__main__":
    main()
