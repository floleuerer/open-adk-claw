import json
import re
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Sandbox Code Executor")

FILES_DIR = "/data/files"
SKILLS_DIR = "/data/skills"


class ExecuteRequest(BaseModel):
    code: str
    language: str = "python"
    timeout: int = 10


class ExecuteResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int


class ExecuteSkillRequest(BaseModel):
    skill_name: str
    arguments: dict = {}
    timeout: int = 10


@app.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest) -> ExecuteResponse:
    if req.language != "python":
        return ExecuteResponse(
            stdout="",
            stderr=f"Unsupported language: {req.language}",
            exit_code=1,
        )

    timeout = min(req.timeout, 30)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir="/tmp", delete=False
    ) as f:
        f.write(req.code)
        script_path = f.name

    try:
        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=FILES_DIR,
        )
        return ExecuteResponse(
            stdout=result.stdout[:10000],
            stderr=result.stderr[:10000],
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return ExecuteResponse(
            stdout="",
            stderr=f"Execution timed out after {timeout}s",
            exit_code=124,
        )
    finally:
        Path(script_path).unlink(missing_ok=True)


@app.post("/execute_skill", response_model=ExecuteResponse)
async def execute_skill(req: ExecuteSkillRequest) -> ExecuteResponse:
    # Validate skill name: alphanumeric + underscores only
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", req.skill_name):
        return ExecuteResponse(
            stdout="",
            stderr=f"Invalid skill name: {req.skill_name}",
            exit_code=1,
        )

    skill_path = Path(SKILLS_DIR) / f"{req.skill_name}.py"
    if not skill_path.is_file():
        return ExecuteResponse(
            stdout="",
            stderr=f"Skill not found: {req.skill_name}",
            exit_code=1,
        )

    timeout = min(req.timeout, 30)

    # Generate wrapper code that imports and calls the skill
    wrapper = (
        f"import sys, json\n"
        f"sys.path.insert(0, {SKILLS_DIR!r})\n"
        f"import {req.skill_name} as _skill\n"
        f"_args = json.loads({json.dumps(json.dumps(req.arguments))})\n"
        f"_result = _skill.run(**_args)\n"
        f"print(_result)\n"
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir="/tmp", delete=False
    ) as f:
        f.write(wrapper)
        script_path = f.name

    try:
        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=FILES_DIR,
        )
        return ExecuteResponse(
            stdout=result.stdout[:10000],
            stderr=result.stderr[:10000],
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return ExecuteResponse(
            stdout="",
            stderr=f"Skill execution timed out after {timeout}s",
            exit_code=124,
        )
    finally:
        Path(script_path).unlink(missing_ok=True)


class ShellRequest(BaseModel):
    command: str
    timeout: int = 10
    working_dir: str = ""


@app.post("/execute_shell", response_model=ExecuteResponse)
async def execute_shell(req: ShellRequest) -> ExecuteResponse:
    timeout = min(req.timeout, 30)
    cwd = req.working_dir or FILES_DIR

    try:
        result = subprocess.run(
            req.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return ExecuteResponse(
            stdout=result.stdout[:10000],
            stderr=result.stderr[:10000],
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return ExecuteResponse(
            stdout="",
            stderr=f"Shell command timed out after {timeout}s",
            exit_code=124,
        )


@app.get("/health")
async def health():
    return {"status": "ok"}
