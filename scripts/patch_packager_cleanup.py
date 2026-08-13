from pathlib import Path

path = Path("src/openakita/agents/packager.py")
text = path.read_text("utf-8")
text = text.replace(
    "    validate_external_skill_source,\n    validate_external_skill_source,\n    validate_external_skill_source,\n    validate_external_skill_source,\n",
    "    validate_external_skill_source,\n",
)
text = text.replace(
    "from openakita.utils.atomic_io import atomic_json_write, safe_write, safe_write_bytes\n"
    "from openakita.utils.atomic_io import atomic_json_write, safe_write, safe_write_bytes\n"
    "from openakita.utils.atomic_io import atomic_json_write, safe_write, safe_write_bytes\n"
    "from openakita.utils.atomic_io import atomic_json_write, safe_write, safe_write_bytes\n",
    "from openakita.utils.atomic_io import atomic_json_write, safe_write, safe_write_bytes\n",
)
path.write_text(text, "utf-8")
