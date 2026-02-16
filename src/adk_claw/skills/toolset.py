from __future__ import annotations

import ast
import inspect
import logging
from pathlib import Path
from typing import Any

import httpx
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

logger = logging.getLogger(__name__)


def _parse_skill(source: str) -> dict | None:
    """Parse a skill file's AST to extract the run() function signature and docstring."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    # Extract module docstring
    module_doc = ast.get_docstring(tree) or ""

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            func_doc = ast.get_docstring(node) or module_doc

            params = []
            defaults_offset = len(node.args.args) - len(node.args.defaults)
            for i, arg in enumerate(node.args.args):
                param: dict[str, Any] = {"name": arg.arg}

                # Type annotation
                if arg.annotation and isinstance(arg.annotation, ast.Name):
                    param["type"] = arg.annotation.id
                elif arg.annotation and isinstance(arg.annotation, ast.Constant):
                    param["type"] = str(arg.annotation.value)
                else:
                    param["type"] = "str"

                # Default value
                default_idx = i - defaults_offset
                if default_idx >= 0:
                    default_node = node.args.defaults[default_idx]
                    if isinstance(default_node, ast.Constant):
                        param["default"] = default_node.value

                params.append(param)

            # Return type annotation
            return_type = "str"
            if node.returns and isinstance(node.returns, ast.Name):
                return_type = node.returns.id

            return {
                "doc": func_doc,
                "params": params,
                "return_type": return_type,
            }

    return None


def _make_skill_caller(skill_name: str, sandbox_url: str, skill_info: dict) -> callable:
    """Build a function that calls the sandbox /execute_skill endpoint."""
    params = skill_info["params"]

    # Build parameter string for the function signature
    param_parts = []
    for p in params:
        type_name = p.get("type", "str")
        if "default" in p:
            param_parts.append(f"{p['name']}: {type_name} = {p['default']!r}")
        else:
            param_parts.append(f"{p['name']}: {type_name}")

    param_str = ", ".join(param_parts)
    param_names = [p["name"] for p in params]

    # Create the function dynamically so ADK introspects real parameters
    func_body = f"""
def {skill_name}({param_str}) -> dict:
    \"\"\"{skill_info['doc']}\"\"\"
    _args = {{{', '.join(f'{repr(n)}: {n}' for n in param_names)}}}
    try:
        resp = _httpx.post(
            f"{{_url}}/execute_skill",
            json={{"skill_name": {skill_name!r}, "arguments": _args, "timeout": 30}},
            timeout=35.0,
        )
        resp.raise_for_status()
        return resp.json()
    except _httpx.HTTPError as e:
        return {{"error": f"Skill execution failed: {{e}}"}}
"""
    ns: dict[str, Any] = {"_httpx": httpx, "_url": sandbox_url}
    exec(func_body, ns)
    return ns[skill_name]


class SkillToolset(BaseToolset):
    """Dynamic toolset that exposes workspace skills as ADK tools."""

    def __init__(self, skills_dir: Path, sandbox_url: str) -> None:
        super().__init__()
        self._skills_dir = skills_dir
        self._sandbox_url = sandbox_url

    async def get_tools(self, readonly_context=None) -> list[FunctionTool]:
        """Scan skills directory and return FunctionTools for each valid skill."""
        if not self._skills_dir.is_dir():
            return []

        tools = []
        for py_file in sorted(self._skills_dir.glob("*.py")):
            skill_name = py_file.stem
            try:
                source = py_file.read_text(encoding="utf-8")
                skill_info = _parse_skill(source)
                if skill_info is None:
                    logger.warning("Skipping invalid skill: %s", skill_name)
                    continue

                caller = _make_skill_caller(skill_name, self._sandbox_url, skill_info)
                tools.append(FunctionTool(caller))
            except Exception:
                logger.exception("Error loading skill: %s", skill_name)

        return tools
