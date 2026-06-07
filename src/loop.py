"""
The main loop that keeps the agent running.
"""

import asyncio
import warnings
from os import getenv

from openai import AsyncOpenAI
from openai.types import Reasoning
from openai.types.responses import ResponseTextDeltaEvent
from agents import (
    Agent,
    ModelSettings,
    OpenAIChatCompletionsModel,
    set_default_openai_client,
    set_tracing_disabled
)
from agents.mcp import MCPServerStreamableHttp
from agents.extensions.memory import AdvancedSQLiteSession
from agents.run import get_default_agent_runner
from dotenv import load_dotenv

from .config import configuration
from .prompts import build_system_prompt
from .tools import tools_list
from .db import get_memories, get_skills


load_dotenv()


def get_client():
    providers = configuration.get("providers", {})
    main_model = configuration.get("main_model", {})
    provider_name = main_model.get("provider")
    important_provider = providers.get(provider_name, {})

    if not provider_name or not important_provider:
        raise ValueError(f"Unknown provider '{provider_name}'. Check config.yaml.")

    base_url = important_provider.get("base_url")
    if not base_url:
        raise ValueError(f"Missing base_url for provider '{provider_name}'.")

    api_key_env = important_provider.get("api_key_env", "OPENAI_API_KEY")
    api_key = getenv(api_key_env)
    if not api_key:
        raise ValueError(f"Missing API key in env var '{api_key_env}'.")

    print(f"using provider {provider_name} with model {main_model.get('slug')}")

    client = AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers={
            "X-OpenRouter-Title": "Jaywire",
            "X-OpenRouter-Categories": "personal-agent",
            "HTTP-Referer": "https://github.com/mags0ft/jaywire"
        }
    )

    return client


def _get_default_loop():
    policy = asyncio.get_event_loop_policy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = policy.get_event_loop()
        except RuntimeError:
            loop = policy.new_event_loop()
            policy.set_event_loop(loop)

    return loop


async def _run_task_async(agent: Agent, task: str, session: AdvancedSQLiteSession):
    if agent.mcp_servers:
        for server in agent.mcp_servers:
            if getattr(server, "session", None) is None:
                await server.connect()

    try:
        runner = get_default_agent_runner()
        stream = runner.run_streamed(
            agent,
            task,
            max_turns=configuration.get("max_turns", 50),
            session=session,
        )
        async for event in stream.stream_events():
            if event.type == "raw_response_event" and isinstance(
                event.data, ResponseTextDeltaEvent):
                print(event.data.delta, end="", flush=True)
        
        return stream

    finally:
        for server in agent.mcp_servers:
            if getattr(server, "session", None) is not None:
                await server.cleanup()


def init_mcp_servers():
    mcp_servers = []

    for name, server_config in configuration.get("mcp", {}).items():
        server = MCPServerStreamableHttp(
            name=name,
            params = {
                "url": server_config["url"],
                "headers": server_config.get("headers", {}),
                "timeout": server_config.get("timeout", 10),
            },
            cache_tools_list=True,
            max_retry_attempts=server_config.get("max_retries", 3),
        )
        mcp_servers.append(server)

    return mcp_servers


client = get_client()


def create_main_agent():
    memories = [mem["mem"] for mem in get_memories()]
    skills = [str(skill["name"]) for skill in get_skills()]

    model = OpenAIChatCompletionsModel(
        model=configuration.get("main_model", {})["slug"],
        openai_client=client
    )

    agent = Agent(
        name="jaywire",
        instructions=build_system_prompt(memories, skills),
        mcp_config={
            "convert_schemas_to_strict": True,
            "include_server_in_tool_names": False,
        },
        tools=tools_list,
        mcp_servers=init_mcp_servers(),
        model=model,
        model_settings=ModelSettings(
            max_tokens=configuration.get("main_model", {}).get("max_tokens", 8192),
            reasoning=Reasoning(effort=configuration.get("reasoning", "high"))
        )
    )

    return agent


def create_session(session_id: str = ""):
    databases = configuration.get("databases", {})

    session = AdvancedSQLiteSession(
        session_id=session_id,
        db_path=databases.get("sessions", "./data/sessions.db"),
        create_tables=True
    )

    return session


def run_task(agent: Agent, task: str, session: AdvancedSQLiteSession):
    loop = _get_default_loop()
    result = loop.run_until_complete(_run_task_async(agent, task, session))

    print()


def mainloop(session_id: str = ""):
    print("initializing agent...")
    agent = create_main_agent()
    print("starting session...")
    session = create_session(session_id=session_id)
    print("ready.")

    while True:
        task = input(" >> ").strip()

        if task.lower() == "exit":
            break

        run_task(agent, task, session=session)


set_tracing_disabled(True)
set_default_openai_client(client, use_for_tracing=False)
