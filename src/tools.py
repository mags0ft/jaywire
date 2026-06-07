from datetime import datetime
from subprocess import Popen, PIPE
from typing import List

from agents import function_tool, Tool

from .util import squeeze
from .db import (
    delete_todos,
    new_memory,
    delete_memory,
    get_memories,
    overwrite_memory,
    new_skill,
    delete_skill,
    get_skills,
    overwrite_skill,
    new_todo,
    get_todos,
    tick_todo,
)


@function_tool(
    name_override="add_memory",
    description_override=squeeze("""Add persistent memory for next session; use
                                 for important info that might be useful later.
                                 """),
)
def add_memory_tool(content: str) -> dict[str, str]:
    if len(str(get_memories())) >= 3000:
        return {
            "error": "Memory limit reached. Please delete or compact memories "
            "before adding new ones."
        }

    if len(content) > 1000:
        return {"error": "Memory too long. Please keep under 1000 chars."}

    new_memory(content)
    return {"result": "OK"}


@function_tool(
    name_override="delete_memory",
    description_override=squeeze("""Delete memory by ID when no longer
                                 relevant; only use after getting all memories
                                 by their IDs with get_memories tool."""),
)
def delete_memory_tool(memory_id: int) -> dict[str, str]:
    delete_memory(memory_id)
    return {"result": "OK"}


@function_tool(
    name_override="get_memories",
    description_override=squeeze("""Get all persistent memories; use to recall
                                 important info from previous sessions; returns
                                 list of dicts with id, mem, time."""),
)
def get_memories_tool() -> list[dict[str, str | int]]:
    return get_memories()


@function_tool(
    name_override="overwrite_memory",
    description_override=squeeze("""Fully overwrite memory by ID when info is
                                 outdated; need to get ID first."""),
)
def overwrite_memory_tool(memory_id: int, new_content: str) -> dict[str, str]:
    if len(new_content) > 1000:
        return {"error": "Memory too long. Please keep under 1000 chars."}

    overwrite_memory(memory_id, new_content)
    return {"result": "OK"}


@function_tool(
    name_override="add_skill",
    description_override=squeeze("""Add skill that can be used as reference
                                 handbook in future sessions; needs short
                                 descriptive name and explanatory content."""),
)
def add_skill_tool(name: str, content: str) -> dict[str, str]:
    new_skill(name, content)
    return {"result": "OK"}


@function_tool(
    name_override="delete_skill",
    description_override=squeeze("""Delete skill by ID when no longer
                                 relevant; only use after getting all skills
                                 by their IDs with get_skills tool."""),
)
def delete_skill_tool(skill_id: int) -> dict[str, str]:
    delete_skill(skill_id)
    return {"result": "OK"}


@function_tool(
    name_override="get_skills",
    description_override=squeeze("""Get all skills; use to recall important
                                 info from previous sessions; returns list of
                                 dicts with id, name, content, time."""),
)
def get_skills_tool() -> list[dict[str, str | int]]:
    return get_skills()


@function_tool(
    name_override="overwrite_skill",
    description_override=squeeze("""Fully overwrite skill by ID when info is
                                 outdated; need to get ID first."""),
)
def overwrite_skill_tool(
    skill_id: int, new_name: str, new_content: str
) -> dict[str, str]:
    overwrite_skill(skill_id, new_name, new_content)
    return {"result": "OK"}


@function_tool(
    name_override="add_todo",
    description_override=squeeze("""Add to-do task for long-horizon task
                                 planning; can be ticked off later to keep
                                 track of progress."""),
)
def add_todo_tool(task: str) -> dict[str, str]:
    new_todo(task)
    return {"result": "OK"}


@function_tool(
    name_override="delete_finished_todos",
    description_override=squeeze("""Delete all ticked-off to-dos; use after
                                 ticking off."""),
)
def delete_todos_tool() -> dict[str, str]:
    delete_todos()
    return {"result": "OK"}


@function_tool(
    name_override="get_todos",
    description_override=squeeze("""Get all to-dos; use to recall pending
                                 tasks; returns list of dicts with id, content,
                                 done."""),
)
def get_todos_tool() -> list[dict[str, str | bool]]:
    return get_todos()


@function_tool(
    name_override="tick_todo",
    description_override=squeeze("""Add or remove tick for to-do by ID."""),
)
def tick_todo_tool(todo_id: int, done: bool) -> dict[str, str]:
    tick_todo(todo_id, done)
    return {"result": "OK"}


@function_tool(
    name_override="get_datetime",
    description_override=squeeze("""Retrieves current time and date."""),
)
def get_datetime_tool() -> dict[str, str]:
    now = datetime.now()
    return {"datetime": now.strftime("%Y-%m-%d %H:%M:%S")}


def _get_command_output(command: str, timeout: int = 30) -> dict[str, str]:
    process = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate(timeout=timeout)

    if process.returncode != 0:
        return {"error": f"{stderr.decode()}"}

    return {"output": stdout.decode().strip()}


@function_tool(
    name_override="env_overview",
    description_override=squeeze("""Returns general environment status overview
                                 (OS, hardware, etc.)"""),
)
def env_overview_tool() -> dict[str, str]:
    uname = _get_command_output("uname -a")
    lscpu = _get_command_output("lscpu")
    free = _get_command_output("free -h")
    df = _get_command_output("df -h")

    return {"info": squeeze(f"""
                   uname: {uname}; lscpu: {lscpu}; free: {free}; df: {df}""")}


@function_tool(
    name_override="terminal_blocking",
    description_override=squeeze("""Run blocking terminal command, will wait
                                 and return output; use for short-running
                                 commands."""),
)
def terminal_blocking_tool(command: str, timeout: int = 30) -> dict[str, str]:
    return _get_command_output(command, timeout=timeout)


@function_tool(
    name_override="terminal_non_blocking",
    description_override=squeeze("""Run non-blocking terminal command, will
                                 immediately return and run in background;
                                 use for long-running commands. No return."""),
)
def terminal_non_blocking_tool(command: str) -> dict[str, str]:
    Popen(command, shell=True)
    return {"result": "OK"}


@function_tool(
    name_override="read_file",
    description_override=squeeze("""Read file content; provide path and get
                                 content back."""),
)
def read_file_tool(path: str) -> dict[str, str]:
    try:
        with open(path, "r") as f:
            return {"content": f.read()}
    except Exception as e:
        return {"error": str(e)}


@function_tool(
    name_override="write_file",
    description_override=squeeze("""Write content to file; provide path and
                                 content; careful, will overwrite existing
                                 content."""),
)
def write_file_tool(path: str, content: str) -> dict[str, str]:
    try:
        with open(path, "w") as f:
            f.write(content)
        return {"result": "OK"}
    except Exception as e:
        return {"error": str(e)}


tools_list: List[Tool] = [
    # memory:
    add_memory_tool,
    delete_memory_tool,
    get_memories_tool,
    overwrite_memory_tool,
    # skills:
    add_skill_tool,
    delete_skill_tool,
    get_skills_tool,
    overwrite_skill_tool,
    # to-dos:
    add_todo_tool,
    delete_todos_tool,
    get_todos_tool,
    tick_todo_tool,
    # terminal:
    env_overview_tool,
    terminal_blocking_tool,
    terminal_non_blocking_tool,
    # file system:
    read_file_tool,
    write_file_tool,
]
