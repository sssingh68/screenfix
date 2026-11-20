import glob
import os
import re
from typing import Any, Dict, List, Optional
import yaml

# Cache for loaded skills
_LOADED_SKILLS: List[Dict[str, Any]] = []


def parse_skill_file(file_path: str) -> Optional[Dict[str, Any]]:
    """Reads a single SKILL.md file, extracts YAML frontmatter and approved action_id."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Split on YAML frontmatter delimiters '---'
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        frontmatter_raw = parts[1]
        body = parts[2]

        metadata = yaml.safe_load(frontmatter_raw) or {}
        skill_id = metadata.get("name", os.path.basename(os.path.dirname(file_path)))
        description = metadata.get("description", "").strip()

        # Extract approved action_id from markdown body (e.g. - **action_id:** `reset_vpn_profile`)
        action_match = re.search(r"action_id[^\w]+([a-zA-Z0-9_\-]+)", body)
        action_id = action_match.group(1) if action_match else None

        return {
            "id": skill_id,
            "name": skill_id,
            "description": description,
            "action_id": action_id,
            "path": file_path,
            "content": content,
        }
    except Exception as e:
        print(f"Warning: Failed to load skill from {file_path}: {e}")
        return None


def load_skills(skills_dir: str = ".agents/skills") -> List[Dict[str, Any]]:
    """Loads all runbook skills from .agents/skills/*/SKILL.md into memory."""
    global _LOADED_SKILLS
    pattern = os.path.join(skills_dir, "*", "SKILL.md")
    skill_files = glob.glob(pattern)

    loaded = []
    for f in skill_files:
        skill = parse_skill_file(f)
        if skill:
            loaded.append(skill)

    _LOADED_SKILLS = loaded
    return _LOADED_SKILLS


def get_skills() -> List[Dict[str, Any]]:
    """Returns the currently loaded skills (loads them if not yet loaded)."""
    if not _LOADED_SKILLS:
        load_skills()
    return _LOADED_SKILLS


def get_skill(skill_id: str) -> Optional[Dict[str, Any]]:
    """Look up a loaded skill by its id / name."""
    for skill in get_skills():
        if skill["id"] == skill_id:
            return skill
    return None


def get_skills_summary() -> str:
    """Returns a short text block of all skill names and descriptions for Gemini system instructions."""
    skills = get_skills()
    if not skills:
        return "No runbook skills currently loaded."

    lines = ["Available approved runbooks:"]
    for s in skills:
        action_info = f" (Approved Action: `{s['action_id']}`)" if s.get("action_id") else ""
        lines.append(f"- ID: {s['id']}")
        lines.append(f"  Description: {s['description']}{action_info}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Testing skills loader...")
    skills = load_skills()
    print(f"Loaded {len(skills)} skill(s):")
    for s in skills:
        print(f" - [{s['id']}] -> Action: {s['action_id']}")
        print(f"   Description: {s['description']}")

    print("\nFormatted Summary for Gemini Prompt:")
    print("-" * 50)
    print(get_skills_summary())
    print("-" * 50)
