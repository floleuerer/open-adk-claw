from __future__ import annotations

import re

from adk_claw.context import get_context


def create_skill(name: str, description: str, code: str) -> dict:
    """Create a new skill that can be invoked as a tool.

    The code must define a `run()` function. The skill will be available
    as a tool on the next agent invocation.

    Args:
        name: Skill name (lowercase, underscores allowed, e.g. "fetch_weather").
        description: One-line description of what the skill does.
        code: Python source code with a `run()` function.
    """
    ctx = get_context()
    if ctx.skills_dir is None:
        return {"error": "Skills directory not configured"}

    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        return {"error": "Invalid skill name: use lowercase letters, digits, and underscores"}

    if "def run(" not in code:
        return {"error": "Skill code must define a `run()` function"}

    # Prepend docstring as module docstring
    module_code = f'"""{description}"""\n\n{code}'

    skill_path = ctx.skills_dir / f"{name}.py"
    skill_path.write_text(module_code, encoding="utf-8")
    return {"status": "created", "name": name, "path": str(skill_path)}


def list_skills() -> dict:
    """List all available skills and their descriptions."""
    ctx = get_context()
    if ctx.skills_dir is None:
        return {"error": "Skills directory not configured"}

    if not ctx.skills_dir.is_dir():
        return {"skills": []}

    skills = []
    for py_file in sorted(ctx.skills_dir.glob("*.py")):
        name = py_file.stem
        # Extract module docstring
        content = py_file.read_text(encoding="utf-8")
        description = ""
        if content.startswith('"""'):
            end = content.find('"""', 3)
            if end != -1:
                description = content[3:end].strip()
        skills.append({"name": name, "description": description})

    return {"skills": skills, "count": len(skills)}
