"""
Agent 包 manifest.json 数据模型与校验逻辑

遵循 Open Agent Sharing Specification v1.0
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

from openakita.memory.types import normalize_tags

SPEC_VERSION = "1.1"
SUPPORTED_SPEC_VERSIONS = {"1.0", "1.1"}

_ID_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{1,62}[a-z0-9])?$")
_NO_DOUBLE_HYPHEN = re.compile(r"--")
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+")
_SKILL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPO_PART_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")

MAX_PACKAGE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_SINGLE_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_ICON_SIZE = 256 * 1024  # 256KB

FORBIDDEN_EXTENSIONS = frozenset(
    {
        ".exe",
        ".bat",
        ".cmd",
        ".sh",
        ".bash",
        ".ps1",
        ".py",
        ".rb",
        ".pl",
        ".php",
        ".jar",
        ".class",
        ".dll",
        ".so",
        ".dylib",
        ".msi",
        ".deb",
        ".rpm",
    }
)


def validate_external_skill_source(source: str) -> bool:
    """Return whether an external skill source is a safe GitHub repository reference.

    Accepted forms are ``owner/repo``, ``owner/repo@skill-id`` and the HTTPS
    equivalents under ``github.com``. Arbitrary hosts, non-HTTPS URLs, ports,
    credentials, query strings, fragments and path traversal are rejected so
    installing an untrusted Agent package cannot turn ``git clone`` into an
    SSRF/arbitrary-network primitive.
    """
    if not isinstance(source, str) or not source or source != source.strip():
        return False

    repo_part = source
    skill_part = ""
    if "@" in source:
        repo_part, skill_part = source.rsplit("@", 1)
        if not _SKILL_ID_PATTERN.fullmatch(skill_part):
            return False

    if repo_part.startswith("https://"):
        parsed = urlsplit(repo_part)
        try:
            port = parsed.port
        except ValueError:
            return False
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").lower() != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
        ):
            return False
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2:
            return False
        owner, repo = parts
    else:
        if "://" in repo_part or "\\" in repo_part:
            return False
        parts = repo_part.split("/")
        if len(parts) != 2:
            return False
        owner, repo = parts

    if repo.endswith(".git"):
        repo = repo[:-4]
    if owner in {".", ".."} or repo in {"", ".", ".."}:
        return False
    return bool(_REPO_PART_PATTERN.fullmatch(owner) and _REPO_PART_PATTERN.fullmatch(repo))


@dataclass
class ManifestAuthor:
    name: str
    url: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.name or not self.name.strip():
            errors.append("author.name is required")
        return errors


@dataclass
class ExternalSkillRef:
    """Reference to a third-party skill fetched from its original source at install time."""

    id: str
    source: str  # e.g. "owner/repo@skill-name"
    version: str = ""
    license: str = "unknown"
    url: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExternalSkillRef:
        return cls(
            id=data.get("id", ""),
            source=data.get("source", ""),
            version=data.get("version", ""),
            license=data.get("license", "unknown"),
            url=data.get("url", ""),
            required=data.get("required", True),
        )


@dataclass
class AgentManifest:
    spec_version: str = SPEC_VERSION
    id: str = ""
    name: str = ""
    name_i18n: dict[str, str] = field(default_factory=dict)
    description: str = ""
    description_i18n: dict[str, str] = field(default_factory=dict)
    version: str = "1.0.0"
    author: ManifestAuthor = field(default_factory=lambda: ManifestAuthor(name=""))
    category: str = ""
    tags: list[str] = field(default_factory=list)
    license: str = "MIT"
    min_platform_version: str = ""
    bundled_skills: list[str] = field(default_factory=list)
    required_builtin_skills: list[str] = field(default_factory=list)
    required_external_skills: list[ExternalSkillRef] = field(default_factory=list)
    created_at: str = ""
    checksum: str = ""

    def __post_init__(self):
        self.tags = normalize_tags(self.tags)

    def validate(self) -> list[str]:
        """返回所有校验错误。空列表表示有效。"""
        errors: list[str] = []

        if self.spec_version not in SUPPORTED_SPEC_VERSIONS:
            errors.append(
                f"Unsupported spec_version: {self.spec_version!r} "
                f"(supported: {SUPPORTED_SPEC_VERSIONS})"
            )

        if not self.id:
            errors.append("id is required")
        elif not _ID_PATTERN.match(self.id):
            errors.append(
                f"Invalid id format: {self.id!r} "
                "(must be 3-64 chars, lowercase alphanumeric + hyphens)"
            )
        elif _NO_DOUBLE_HYPHEN.search(self.id):
            errors.append(f"id must not contain consecutive hyphens: {self.id!r}")

        if not self.name:
            errors.append("name is required")

        if not self.description:
            errors.append("description is required")

        if not _SEMVER_PATTERN.match(self.version):
            errors.append(f"Invalid version format: {self.version!r} (expected SemVer)")

        errors.extend(self.author.validate())

        if self.min_platform_version and not _SEMVER_PATTERN.match(self.min_platform_version):
            errors.append(f"Invalid min_platform_version: {self.min_platform_version!r}")

        for field_name, skill_ids in (
            ("bundled_skills", self.bundled_skills),
            ("required_builtin_skills", self.required_builtin_skills),
        ):
            if not isinstance(skill_ids, list):
                errors.append(f"{field_name} must be a list")
                continue
            for skill_id in skill_ids:
                if not isinstance(skill_id, str) or not _SKILL_ID_PATTERN.fullmatch(skill_id):
                    errors.append(f"Invalid {field_name} id: {skill_id!r}")

        if not isinstance(self.required_external_skills, list):
            errors.append("required_external_skills must be a list")
        else:
            for ref in self.required_external_skills:
                if not isinstance(ref, ExternalSkillRef):
                    errors.append(f"Invalid external skill reference: {ref!r}")
                    continue
                if not _SKILL_ID_PATTERN.fullmatch(ref.id or ""):
                    errors.append(f"Invalid required_external_skills id: {ref.id!r}")
                if not validate_external_skill_source(ref.source):
                    errors.append(f"Invalid external skill source for {ref.id!r}: {ref.source!r}")

        return errors

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for key in [
            "name_i18n",
            "description_i18n",
            "tags",
            "bundled_skills",
            "required_builtin_skills",
            "required_external_skills",
        ]:
            if not d.get(key):
                d.pop(key, None)
        for key in ["category", "license", "min_platform_version", "checksum"]:
            if not d.get(key):
                d.pop(key, None)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentManifest:
        author_data = data.get("author", {})
        if isinstance(author_data, dict):
            author = ManifestAuthor(
                name=author_data.get("name", ""),
                url=author_data.get("url", ""),
            )
        else:
            author = ManifestAuthor(name=str(author_data))

        ext_skills_raw = data.get("required_external_skills", [])
        ext_skills = [
            ExternalSkillRef.from_dict(s) if isinstance(s, dict) else s for s in ext_skills_raw
        ]

        return cls(
            spec_version=data.get("spec_version", SPEC_VERSION),
            id=data.get("id", ""),
            name=data.get("name", ""),
            name_i18n=data.get("name_i18n", {}),
            description=data.get("description", ""),
            description_i18n=data.get("description_i18n", {}),
            version=data.get("version", "1.0.0"),
            author=author,
            category=data.get("category", ""),
            tags=data.get("tags", []),
            license=data.get("license", "MIT"),
            min_platform_version=data.get("min_platform_version", ""),
            bundled_skills=data.get("bundled_skills", []),
            required_builtin_skills=data.get("required_builtin_skills", []),
            required_external_skills=ext_skills,
            created_at=data.get("created_at", ""),
            checksum=data.get("checksum", ""),
        )


def validate_file_safety(filepath: str) -> list[str]:
    """校验文件路径安全性"""
    errors = []
    normalized = filepath.replace("\\", "/")

    if ".." in normalized.split("/"):
        errors.append(f"Path traversal detected: {filepath}")

    if normalized.startswith("/"):
        errors.append(f"Absolute path not allowed: {filepath}")

    ext = "." + normalized.rsplit(".", 1)[-1].lower() if "." in normalized else ""
    if ext in FORBIDDEN_EXTENSIONS:
        errors.append(f"Forbidden file type: {filepath}")

    return errors
