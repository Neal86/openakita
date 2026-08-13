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
        '_SEMVER_PATTERN = re.compile(r"^\\d+\\.\\d+\\.\\d+")\n',
        '_SEMVER_PATTERN = re.compile(r"^\\d+\\.\\d+\\.\\d+(?:-[0-9A-Za-z.-]+)?(?:\\+[0-9A-Za-z.-]+)?$")\n',
        "strict semver",
    )
    replace_exact(
        manifest,
        '''def validate_file_safety(filepath: str) -> list[str]:\n    """校验文件路径安全性"""\n    errors = []\n    normalized = filepath.replace("\\\\", "/")\n\n    if ".." in normalized.split("/"):\n        errors.append(f"Path traversal detected: {filepath}")\n\n    if normalized.startswith("/"):\n        errors.append(f"Absolute path not allowed: {filepath}")\n\n    ext = "." + normalized.rsplit(".", 1)[-1].lower() if "." in normalized else ""\n    if ext in FORBIDDEN_EXTENSIONS:\n        errors.append(f"Forbidden file type: {filepath}")\n\n    return errors\n''',
        '''def validate_file_safety(filepath: str) -> list[str]:\n    """Validate archive member names using cross-platform filesystem rules."""\n    errors: list[str] = []\n    if not isinstance(filepath, str) or not filepath:\n        return [f"Invalid empty file path: {filepath!r}"]\n    if "\\x00" in filepath:\n        errors.append(f"NUL byte not allowed in path: {filepath!r}")\n\n    normalized = filepath.replace("\\\\", "/")\n    parts = normalized.split("/")\n    meaningful_parts = parts[:-1] if parts and parts[-1] == "" else parts\n\n    if normalized.startswith("/") or normalized.startswith("//"):\n        errors.append(f"Absolute path not allowed: {filepath}")\n    if re.match(r"^[A-Za-z]:", normalized):\n        errors.append(f"Windows drive path not allowed: {filepath}")\n\n    windows_reserved = {\n        "CON", "PRN", "AUX", "NUL",\n        *(f"COM{i}" for i in range(1, 10)),\n        *(f"LPT{i}" for i in range(1, 10)),\n    }\n    for part in meaningful_parts:\n        if part in {"", ".", ".."}:\n            errors.append(f"Unsafe path segment {part!r}: {filepath}")\n            continue\n        if ":" in part:\n            errors.append(f"Colon/ADS path segment not allowed: {filepath}")\n        if part.endswith((" ", ".")):\n            errors.append(f"Windows-normalized path segment not allowed: {filepath}")\n        stem = part.split(".", 1)[0].rstrip(" .").upper()\n        if stem in windows_reserved:\n            errors.append(f"Windows reserved filename not allowed: {filepath}")\n\n    ext = "." + normalized.rsplit(".", 1)[-1].lower() if "." in normalized else ""\n    if ext in FORBIDDEN_EXTENSIONS:\n        errors.append(f"Forbidden file type: {filepath}")\n\n    return errors\n''',
        "cross-platform archive path validation",
    )

    packager = Path("src/openakita/agents/packager.py")
    replace_exact(
        packager,
        '''            normalized_name = info.filename.replace("\\\\", "/")\n            if normalized_name in seen_names:\n                raise PackageError(f"Duplicate ZIP member not allowed: {info.filename}")\n            seen_names.add(normalized_name)\n''',
        '''            normalized_name = info.filename.replace("\\\\", "/")\n            collision_key = "/".join(\n                part.rstrip(" .").casefold() for part in normalized_name.split("/")\n            )\n            if collision_key in seen_names:\n                raise PackageError(f"Duplicate ZIP member not allowed: {info.filename}")\n            seen_names.add(collision_key)\n''',
        "cross-platform duplicate member detection",
    )


if __name__ == "__main__":
    main()
