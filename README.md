# Jaywire

Everyone is building agents, so I just had to do it too. I'm sorry.

This one is, in contrast to the other popular ones (looking at you, OpenClaw and Hermes Agent), very token-efficient. The default system prompt is ~100 tokens, but it can stil do advanced tasks.
For example, I got it to effortlessly figure out how the printer in my network works, print something on it and store it all in a skill file.

Tested with Deepseek V4 Flash, but should work with any capable model.

Features:

- Skills and persistent memory for self-improvement
- To-Do list and task management
- Arbitrary MCP server support via HTTP(s)
- File editing
- Restoring and resuming old sessions
- Basic isolation (the agent runs in a reasonably secured Docker container, but I won't guarantee anything - it has root in there!)
- Highly efficient prompting, which makes your agent super cheap to use
- Uses OpenAI's official Agent SDK, it's very easy to hack together your own custom features!
- Clean code, no slop

## Get started

```
cp config.example.yaml config.yaml
cp .env.example .env
```

Edit the config to your liking and set up the environment variables in .env, then run:

```
docker compose up --build -d
```

Done! You can interact with the agent in the CLI by running:

```
docker compose exec jaywire python3 ./main.py
```

## AI usage

This project has **not been vibe-coded**. AI was merely used for code completions in non-critical repetitive parts, and all code has been read, examined and edited by hand. It should be fine.
