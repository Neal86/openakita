from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    path = Path("src/openakita/agents/profile.py")

    replace_exact(
        path,
        '''    def _load_categories(self) -> None:\n        if not self._categories_file.exists():\n            return\n        try:\n            data = json.loads(self._categories_file.read_text(encoding="utf-8"))\n            if isinstance(data, list):\n                self._custom_categories = data\n                logger.info(f"Loaded {len(data)} custom category(ies)")\n        except Exception as e:\n            logger.warning(f"Failed to load categories: {e}")\n\n    def _persist_categories(self) -> None:\n        atomic_json_write(self._categories_file, self._custom_categories)\n''',
        '''    def _load_categories(self) -> None:\n        data = read_json_safe(self._categories_file)\n        if data is None:\n            return\n        if not isinstance(data, list):\n            logger.warning("Failed to load categories: root must be a list")\n            return\n\n        loaded: list[dict[str, Any]] = []\n        seen = set(_BUILTIN_IDS)\n        for row in data:\n            if not isinstance(row, dict):\n                logger.warning("Skipping malformed category row: %r", row)\n                continue\n            cat_id = row.get("id")\n            label = row.get("label")\n            color = row.get("color")\n            if (\n                not isinstance(cat_id, str)\n                or not cat_id.strip()\n                or cat_id != cat_id.strip()\n                or cat_id in seen\n                or not isinstance(label, str)\n                or not label.strip()\n                or not isinstance(color, str)\n                or not color.strip()\n            ):\n                logger.warning("Skipping invalid category row: %r", row)\n                continue\n            loaded.append({"id": cat_id, "label": label, "color": color})\n            seen.add(cat_id)\n\n        self._custom_categories = loaded\n        if loaded:\n            logger.info("Loaded %d custom category(ies)", len(loaded))\n\n    def _persist_categories(self, categories: list[dict[str, Any]]) -> None:\n        atomic_json_write(\n            self._categories_file,\n            categories,\n            backup=True,\n            fsync=True,\n            allow_fallback=False,\n        )\n''',
        "durable category load/persist",
    )

    replace_exact(
        path,
        '''    def add_category(self, cat_id: str, label: str, color: str) -> dict[str, Any]:\n        """新增自定义分类。id 不能与已有分类重复。"""\n        with self._lock:\n            existing_ids = _BUILTIN_IDS | {c["id"] for c in self._custom_categories}\n            if cat_id in existing_ids:\n                raise ValueError(f"分类 ID 已存在: {cat_id}")\n            entry: dict[str, Any] = {"id": cat_id, "label": label, "color": color}\n            self._custom_categories.append(entry)\n            self._persist_categories()\n        logger.info(f"Added custom category: {cat_id} ({label})")\n        return {**entry, "builtin": False, "agent_count": 0}\n''',
        '''    def add_category(self, cat_id: str, label: str, color: str) -> dict[str, Any]:\n        """新增自定义分类。id 不能与已有分类重复。"""\n        if (\n            not isinstance(cat_id, str)\n            or not cat_id.strip()\n            or cat_id != cat_id.strip()\n            or not isinstance(label, str)\n            or not label.strip()\n            or not isinstance(color, str)\n            or not color.strip()\n        ):\n            raise ValueError("分类 ID、名称和颜色不能为空，ID 不能包含首尾空白")\n        with self._lock:\n            existing_ids = _BUILTIN_IDS | {c["id"] for c in self._custom_categories}\n            if cat_id in existing_ids:\n                raise ValueError(f"分类 ID 已存在: {cat_id}")\n            entry: dict[str, Any] = {"id": cat_id, "label": label, "color": color}\n            updated = [*self._custom_categories, entry]\n            self._persist_categories(updated)\n            self._custom_categories = updated\n        logger.info(f"Added custom category: {cat_id} ({label})")\n        return {**entry, "builtin": False, "agent_count": 0}\n''',
        "category add fail closed",
    )

    replace_exact(
        path,
        '''            before = len(self._custom_categories)\n            self._custom_categories = [c for c in self._custom_categories if c["id"] != cat_id]\n            if len(self._custom_categories) == before:\n                return False\n            self._persist_categories()\n''',
        '''            before = len(self._custom_categories)\n            updated = [c for c in self._custom_categories if c["id"] != cat_id]\n            if len(updated) == before:\n                return False\n            self._persist_categories(updated)\n            self._custom_categories = updated\n''',
        "category remove fail closed",
    )


if __name__ == "__main__":
    main()
