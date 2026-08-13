from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    for raw in (
        "src/openakita/hub/skill_store_client.py",
        "src/openakita/agents/packager.py",
    ):
        path = Path(raw)
        replace_exact(
            path,
            '''        else:\n            if backup_dir.exists():\n                shutil.rmtree(backup_dir)\n''',
            '''        else:\n            if backup_dir.exists():\n                try:\n                    shutil.rmtree(backup_dir)\n                except OSError as exc:\n                    logger.warning(\n                        "Skill replacement succeeded but backup cleanup failed (%s): %s",\n                        backup_dir,\n                        exc,\n                    )\n''',
            f"best-effort backup cleanup in {raw}",
        )


if __name__ == "__main__":
    main()
