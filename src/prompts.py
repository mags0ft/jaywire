"""
Handles prompting the LLM.
"""

from datetime import datetime

from .config import configuration
from .util import squeeze


def build_system_prompt(memory_list: list[str], skill_list: list[str]):
    """
    Builds the super short and efficient system prompt to the agent - the one
    we all know and love!
    """

    context = configuration.get("context", {})
    agent_name = context.get("agent_name", "Jaywire")
    user_name = context.get("user_name", "the user")

    memory = " -- ".join(memory_list) if memory_list else "none"
    skills = ", ".join(skill_list) if skill_list else "none"
    current_date = datetime.now().strftime("%Y-%m-%d")

    return squeeze(f"""
You're {agent_name}, helpful agent to {user_name}, your user. You persist
across sessions, can learn, access outside tools, work autonomously. Save
important info to your memory (for environment details), to-do (track current
work) or skill files (to replicate tasks in the future). Persistent working
directory is in /work, use for important files. Memories: {memory} --
Available skills: {skills}. Heavily use tools. Date: {current_date}
""")
