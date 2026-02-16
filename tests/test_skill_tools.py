import tempfile
from pathlib import Path

from adk_claw.actions.skill_tools import create_skill, list_skills
from adk_claw.context import AppContext, set_context
from adk_claw.skills.toolset import _parse_skill


class TestCreateSkill:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        set_context(AppContext(skills_dir=self._dir))

    def teardown_method(self):
        self._tmp.cleanup()

    def test_create_valid_skill(self):
        code = 'def run(query: str) -> str:\n    return f"result: {query}"'
        result = create_skill("my_skill", "A test skill", code)
        assert result["status"] == "created"
        assert result["name"] == "my_skill"

        # File should exist with module docstring
        content = (self._dir / "my_skill.py").read_text()
        assert '"""A test skill"""' in content
        assert "def run(" in content

    def test_invalid_name_rejected(self):
        result = create_skill("../evil", "bad", "def run(): pass")
        assert "error" in result

    def test_uppercase_name_rejected(self):
        result = create_skill("MySkill", "bad", "def run(): pass")
        assert "error" in result

    def test_missing_run_rejected(self):
        result = create_skill("ok_name", "desc", "def other(): pass")
        assert "error" in result

    def test_name_with_digits(self):
        result = create_skill("skill2", "desc", "def run(): pass")
        assert result["status"] == "created"


class TestListSkills:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        set_context(AppContext(skills_dir=self._dir))

    def teardown_method(self):
        self._tmp.cleanup()

    def test_empty_dir(self):
        result = list_skills()
        assert result["count"] == 0

    def test_lists_skills_with_docstrings(self):
        (self._dir / "fetch.py").write_text('"""Fetch data from API."""\ndef run(): pass\n')
        (self._dir / "calc.py").write_text('"""Calculate things."""\ndef run(): pass\n')

        result = list_skills()
        assert result["count"] == 2
        names = {s["name"] for s in result["skills"]}
        assert names == {"fetch", "calc"}

        fetch = next(s for s in result["skills"] if s["name"] == "fetch")
        assert fetch["description"] == "Fetch data from API."


class TestParseSkill:
    def test_simple_function(self):
        source = '''"""My skill."""

def run(query: str) -> str:
    """Search for something.

    Args:
        query: The search query.
    """
    return query
'''
        info = _parse_skill(source)
        assert info is not None
        assert "Search for something" in info["doc"]
        assert len(info["params"]) == 1
        assert info["params"][0]["name"] == "query"
        assert info["params"][0]["type"] == "str"
        assert info["return_type"] == "str"

    def test_function_with_defaults(self):
        source = '''def run(name: str, count: int = 5) -> str:
    """Do something."""
    pass
'''
        info = _parse_skill(source)
        assert info is not None
        assert len(info["params"]) == 2
        assert info["params"][1]["default"] == 5

    def test_no_run_function(self):
        source = "def other(): pass"
        info = _parse_skill(source)
        assert info is None

    def test_invalid_syntax(self):
        source = "def run(: invalid"
        info = _parse_skill(source)
        assert info is None

    def test_module_docstring_fallback(self):
        source = '''"""Module level doc."""

def run(x: str) -> str:
    pass
'''
        info = _parse_skill(source)
        assert info is not None
        assert info["doc"] == "Module level doc."
