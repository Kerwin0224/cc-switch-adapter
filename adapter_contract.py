from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

APP_DIRS_REL: dict[str, tuple[str, ...]] = {
    "claude": (".claude", "skills"),
    "codex": (".codex", "skills"),
    "gemini": (".gemini", "skills"),
    "grokbuild": (".grok", "skills"),
    "opencode": (".config", "opencode", "skills"),
    "hermes": (".hermes", "skills"),
}

APP_OVERRIDE_KEYS: dict[str, str] = {
    "claude": "claudeConfigDir",
    "codex": "codexConfigDir",
    "gemini": "geminiConfigDir",
    "grokbuild": "grokConfigDir",
    "opencode": "opencodeConfigDir",
    "hermes": "hermesConfigDir",
}

PROFILE_SKILL_APPS: tuple[str, ...] = ("claude", "codex")


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class MigrationRequest:
    source_id: str
    target_id: str
    directory: str
    name: str | None
    apply: bool


def is_safe_directory(value: str) -> bool:
    return (
        bool(value)
        and value == value.strip()
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
        and value not in {".", ".."}
        and not value.startswith(".")
    )


def is_safe_skill_path(
    value: str, *, allow_nested: bool, allow_hidden: bool = False
) -> bool:
    if not value or value != value.strip() or "\\" in value or "\x00" in value:
        return False
    if value.startswith("/") or value.startswith("~"):
        return False
    parts = value.split("/")
    if not allow_nested and len(parts) != 1:
        return False
    return all(
        part
        and part not in {".", ".."}
        and (allow_hidden or not part.startswith("."))
        for part in parts
    )


def is_canonical_id(value: str) -> bool:
    if value.startswith("local:"):
        return is_safe_skill_path(value[6:], allow_nested=False)
    if ":" not in value:
        return False
    repo, skill_path = value.split(":", 1)
    owner_repo = repo.split("/")
    if len(owner_repo) != 2 or not is_github_owner(owner_repo[0]) or not is_github_repo(owner_repo[1]):
        return False
    return is_safe_skill_path(skill_path, allow_nested=True, allow_hidden=True)


def is_github_owner(value: str) -> bool:
    return bool(value) and len(value) <= 39 and all(
        char.isascii() and (char.isalnum() or char == "-") for char in value
    )


def is_github_repo(value: str) -> bool:
    return bool(value) and len(value) <= 100 and value not in {".", ".."} and all(
        char.isascii() and (char.isalnum() or char in ".-_") for char in value
    )


def resolve_override_path(home: Path, raw: str) -> Path:
    if raw == "~":
        return home
    if raw.startswith("~/") or raw.startswith("~\\"):
        return home / raw[2:]
    return Path(raw)


def app_skills_dir(
    home: Path, settings: Mapping[str, str | bool | None], app: str
) -> Path:
    try:
        default_parts = APP_DIRS_REL[app]
        override_key = APP_OVERRIDE_KEYS[app]
    except KeyError as exc:
        raise KeyError(f"unknown app: {app}") from exc
    raw_override = settings.get(override_key)
    if isinstance(raw_override, str) and raw_override:
        return resolve_override_path(home, raw_override) / "skills"
    return home.joinpath(*default_parts)


def app_skill_dirs(
    home: Path, settings: Mapping[str, str | bool | None]
) -> dict[str, Path]:
    return {app: app_skills_dir(home, settings, app) for app in APP_DIRS_REL}


def parse_skill_metadata(path: Path, fallback_name: str) -> SkillMetadata:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return SkillMetadata(name=fallback_name, description="")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return SkillMetadata(name=fallback_name, description="")

    name = fallback_name
    description = ""
    index = 1
    while index < end:
        line = lines[index]
        if line.startswith("name:"):
            name = _scalar(line.partition(":")[2]) or fallback_name
        elif line.startswith("description:"):
            raw = line.partition(":")[2].strip()
            if raw in {">", ">-", ">+", "|", "|-", "|+"}:
                block: list[str] = []
                index += 1
                while index < end and (not lines[index] or lines[index][0].isspace()):
                    block.append(lines[index].strip())
                    index += 1
                description = (
                    " ".join(part for part in block if part)
                    if raw.startswith(">")
                    else "\n".join(block).strip()
                )
                continue
            description = _scalar(raw)
        index += 1
    return SkillMetadata(name=name, description=description)


def _scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
