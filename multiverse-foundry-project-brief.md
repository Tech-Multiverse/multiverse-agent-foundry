# Multiverse Foundry — Project Brief

**Tagline:** Serialized on 8GB, engineered for a swarm.

## Pitch

A configurable agent factory: a task config goes in, a "builder" LLM designs a
crew of task-specific sub-agents to handle it, and a runner executes them.
Runs today as a serialized pipeline against a single remote Ollama model on
an 8GB-VRAM GPU box — but the graph topology, message protocol, and tool
interfaces are all written so that swapping in more GPU capacity turns the
same code into a genuinely parallel multi-agent system. No rewrite required,
just a concurrency dial.

Audience: Tech-Multiverse community members who want to learn multi-agent
orchestration without needing a cloud GPU budget, plus a portfolio piece that
demonstrates real familiarity with the current enterprise agent stack
(LangGraph, MCP, A2A).

## Goals

1. **Teaching artifact** — every design decision should be legible: comments
   and a companion write-up explain *why* it's serialized here and *what
   changes* to make it parallel.
2. **Resume artifact** — use tools a hiring manager will recognize: LangGraph,
   Model Context Protocol (MCP) for tool access, the A2A protocol for
   inter-agent messaging, Docker, structured tracing.
3. **Actually useful** — should run against a real remote Ollama endpoint and
   complete real tasks (research, content draft, plan), not just print mock
   output.

## Architecture at a glance

- **Task config** (YAML/JSON, Pydantic-validated) — declares the task type,
  which tools are allowed, and resource limits.
- **Builder agent** — a LangGraph node that reads the config and emits a list
  of sub-agent specs (role, system prompt, tool allowlist, handoff order).
- **Task agent runner** — a LangGraph graph built with fan-out edges
  (`Send` API) so the *topology* is parallel-shaped. A `MAX_CONCURRENCY` env
  var controls how many branches actually execute at once — set to 1 today,
  turned up on bigger hardware later.
- **Tool layer** — every tool is exposed as an MCP server (even trivial ones),
  so task agents talk to tools over the same protocol enterprise tooling
  uses. This is also where your resource-request mechanism lives: a tool call
  that fails or is missing raises a structured `ResourceRequest`.
- **Human-in-the-loop gate** — implemented with LangGraph's `interrupt`/
  `Command(resume=...)`, not a custom polling loop. When a task agent hits a
  missing resource, the graph pauses, surfaces the request (CLI prompt or
  simple web UI), and resumes once you (with Devin's help) add the tool.
- **Inter-agent messaging** — expose the builder agent and task agents as
  A2A-compliant servers (agent card + task endpoint) so agents can discover
  and call each other over the wire, not just via in-process function calls.
  This is what makes "scale to true parallelism" literal: A2A doesn't care if
  the other agent is a local coroutine or a server across the room.
- **Model host** — remote GPU box running Ollama, same pattern as your crAPI
  lab: Ollama bound behind an authenticated endpoint, app machine points at
  `OLLAMA_HOST` over the network rather than localhost.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangGraph | Native support for fan-out/fan-in, checkpointing, interrupts |
| Model serving | Ollama (remote GPU) | Matches your existing setup, easy to swap models |
| Tool protocol | MCP (Model Context Protocol) | Industry-standard tool exposure, resume-relevant |
| Agent messaging | A2A protocol | Open, cloud-vendor-backed agent interop standard |
| Config validation | Pydantic | Enterprise-standard schema validation |
| State persistence | LangGraph checkpointer (SQLite to start, Postgres optional) | Lets you pause/resume across the human-in-the-loop gate |
| Tracing/observability | LangSmith or self-hosted Langfuse | Visualize the graph execution, useful for the write-up's screenshots |
| Packaging | Docker Compose | One command to stand up the app side; GPU box stays separate |

## Repo structure

```
multiverse-foundry/
├── README.md
├── docker-compose.yml
├── configs/
│   └── example-tasks/           # sample task configs (research, content, plan)
├── src/
│   ├── builder/                 # builder agent: reads config, emits agent specs
│   ├── graph/                   # LangGraph graph definition, Send-based fan-out
│   ├── tools/                   # one MCP server per tool
│   ├── a2a/                     # agent card + task server for each exposed agent
│   ├── resource_requests/       # interrupt handling + simple approval UI
│   └── config_schema.py         # Pydantic models
├── infra/
│   └── remote-ollama/           # notes/scripts for the GPU box setup
└── docs/
    └── write-up.md              # the community-facing narrative piece
```

## Build phases (hand these to Devin one at a time)

**Phase 0 — Skeleton**
- Scaffold the repo structure above.
- Pydantic config schema for a task (`task_type`, `allowed_tools`, `max_agents`).
- One example task config committed.
- Done when: `python -m src.builder --config configs/example-tasks/research.yaml`
  prints a validated config object.

**Phase 1 — Model connection**
- Point at remote Ollama endpoint via env var, not hardcoded.
- Minimal LangGraph graph: one node that calls the model and returns a
  response.
- Done when: a single round-trip to the remote GPU box works end to end.

**Phase 2 — Builder agent**
- Builder node: takes the task config, prompts the model to emit a JSON list
  of sub-agent specs (validated against a Pydantic schema, retry on invalid
  output).
- Done when: given the research task config, it emits a plausible 2-4 agent
  spec list.

**Phase 3 — Task agent runner with parallel-shaped topology**
- Build the fan-out graph using LangGraph's `Send` API so each sub-agent spec
  becomes a branch.
- Add `MAX_CONCURRENCY` (default 1) that gates how many branches run at once
  via a semaphore, regardless of how many branches exist.
- Done when: a 3-agent spec runs sequentially at concurrency 1, and toggling
  the env var to 2+ actually runs branches concurrently (testable even on one
  GPU by pointing at a second, smaller model, or by mocking).

**Phase 4 — Tools as MCP servers + resource requests**
- Wrap 2-3 real tools (web search, file write, a calculator or scraper) as
  MCP servers.
- Task agents call tools only through MCP.
- On a missing/failed tool call, raise a `ResourceRequest`, trigger a LangGraph
  `interrupt`, and surface it (simplest: print to CLI with instructions;
  stretch: small FastAPI + HTML approval page).
- Done when: you can watch a run pause, approve a fake "add this tool"
  request, and see it resume.

**Phase 5 — A2A exposure**
- Wrap the builder agent and the task-agent runner as separate A2A servers
  with agent cards.
- Have the builder call the task-agent runner over A2A instead of a direct
  function call.
- Done when: `curl` against the builder's agent card returns valid A2A
  metadata, and a task submitted via the A2A task endpoint completes.

**Phase 6 — Observability + polish**
- Wire in LangSmith/Langfuse tracing.
- Write `docs/write-up.md`: the community-facing explanation, including a
  "here's the dial that turns this into a real swarm" section with before/after
  concurrency numbers.
- Record a short screen capture of a run for the community post.

## The parallelism story (the part worth writing about)

The single most resume- and community-relevant thing about this project is
that it's honest about the resource constraint instead of hiding it. The
write-up should explicitly show:
- The `Send`-based fan-out code, annotated to show it's already
  parallel-shaped.
- The `MAX_CONCURRENCY` semaphore as the one line that currently limits it.
- What changes on real hardware: more GPU memory → higher concurrency →
  same code, more simultaneous branches. Optionally, a second cheap GPU box
  running a second Ollama instance to demonstrate actual concurrent
  execution across two model endpoints, so the "true parallelism" claim has
  a real (even if small-scale) proof rather than just a config flag.

## Stretch goals

- Add a second remote Ollama endpoint to genuinely demonstrate 2-way
  parallel execution for the write-up's "proof" section.
- Small web dashboard (could be a simple FastAPI + HTMX page) showing live
  graph state instead of CLI output — good for a demo video.
- A guardrails/validation layer on tool inputs, drawing on your LLM security
  lab background — ties this project back to your existing community work.
