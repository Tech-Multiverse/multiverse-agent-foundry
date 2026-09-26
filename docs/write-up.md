# Multiverse Foundry: Serialized on 8GB, Engineered for a Swarm

## Why this project exists

Multi-agent demos often assume abundant cloud inference capacity. Multiverse Foundry starts from a less glamorous constraint: one remote Ollama host with an 8GB GPU. Rather than disguising that constraint, the architecture makes it visible and useful.

A task configuration enters the system. A builder model designs a small crew, validates every agent specification, and hands that crew to a runner. The runner already has a parallel fan-out topology, but a semaphore limits active model calls to one by default. More capable hardware changes the concurrency setting, not the graph.

The project is both a working local-first agent factory and a teaching artifact for LangGraph, MCP, A2A, durable interrupts, structured validation, and operational tracing.

## System map

```text
Task YAML/JSON
      |
      v
Builder A2A service :8001
  - validates TaskConfig
  - asks Ollama for AgentSpec[]
  - retries invalid structured output
      |
      | A2A JSON-RPC
      v
Runner A2A service :8002
  - LangGraph Send fan-out
  - MAX_CONCURRENCY semaphore
  - SQLite checkpoints + interrupts
      |
      +---- agent branch ---- MCP web search
      +---- agent branch ---- MCP calculator
      +---- agent branch ---- MCP file write
      |
      v
Ordered structured results
```

Both services publish A2A 1.0 agent cards. Tools are separate stdio MCP servers. Ollama remains outside the Compose network and is addressed only through the gitignored `.env` file.

## Phase-by-phase design story

### Phase 0: make configuration boring

The initial milestone deliberately did not call a model. It established a strict Pydantic task contract and a reproducible Conda/Docker skeleton. The task carries schema-agnostic `task_input` and an optional caller-supplied JSON response schema, so adding a task type does not require adding application-specific response classes.

### Phase 1: prove the model boundary

A one-node graph (`START → call_model → END`) proved that a container could reach remote Ollama through `OLLAMA_HOST`. No private address is present in tracked files. This isolated networking and model-tag problems before agent logic complicated diagnosis.

### Phase 2: treat model output as untrusted input

The builder receives the task plus an `AgentCrew` JSON Schema. Its output is parsed and validated rather than trusted. Validation covers:

- crew size and task limits;
- unique roles;
- non-empty system prompts;
- tool allowlists;
- required-tool assignment;
- consecutive handoff order;
- rejection of unknown fields.

Invalid output is fed back to the model for a bounded retry. A model response becomes application state only after it satisfies the contract.

### Phase 3: parallel-shaped, intentionally serialized

LangGraph's `Send` API creates one branch per agent. A reducer gathers branch results and a final node restores deterministic handoff order.

```text
                  +--> Agent A --+
START --> gate -->+--> Agent B --+--> finalize --> END
                  +--> Agent C --+
```

A shared semaphore wraps model execution:

```dotenv
MAX_CONCURRENCY=1
```

At `1`, branches exist concurrently in the graph but only one can use Ollama at a time. At `2`, two branches may overlap. Deterministic tests observe peak active model calls of exactly one and two respectively. Those are topology tests, not claims about GPU throughput; real timing depends on model size, context, quantization, and the Ollama host.

The honest scaling story is:

| Hardware situation | Dial | Graph rewrite |
|---|---:|---|
| Current 8GB GPU | `MAX_CONCURRENCY=1` | None |
| Larger single GPU | `MAX_CONCURRENCY=2+` after measurement | None |
| Multiple inference hosts | route branches across endpoints | Topology remains fan-out/fan-in |

### Phase 4: tools are protocol boundaries

Calculator, Wikipedia search, and sandboxed file writing run as separate MCP servers. Agents receive only tools on their validated allowlist. The calculator evaluates a restricted arithmetic AST rather than executing code, and file writes are confined to approved extensions under the bind-mounted `data/` directory.

When a required tool has no MCP server, the graph emits a structured `ResourceRequest` with LangGraph `interrupt()`. SQLite stores the thread under `data/checkpoints.sqlite`. A later process resumes that exact thread with `Command(resume=...)`.

Available decisions are `retry`, `continue_without_tool`, and `cancel`. The committed `resource-request.yaml` task demonstrates the pause/resume flow without pretending that a missing capability exists.

### Phase 5: agents become network peers

The builder and runner are separate A2A services. The builder discovers the runner from its agent card and submits the validated task and crew over A2A JSON-RPC. There is no direct builder-to-runner function call in this path.

This is more ceremony than an in-process call, but it creates a real deployment boundary. The runner can move to another container or machine as long as its agent card advertises a reachable interface.

### Phase 6: useful observability without sending prompts elsewhere

The primary observability backend is local JSONL at `data/traces.jsonl`. Events cover:

- host-to-builder and builder-to-runner A2A requests;
- builder generation duration;
- runner graph duration;
- individual agent duration and handoff position;
- active branch count versus configured concurrency;
- MCP tool name and duration;
- failures by exception type.

Prompts, model responses, private endpoints, and credentials are intentionally excluded. Metadata fields containing key, token, password, or secret are redacted. The JSONL boundary can later feed a dashboard, OpenTelemetry collector, LangSmith, or Langfuse without changing orchestration logic.

Inspect recent events with:

```bash
python -c 'import json; from pathlib import Path; [print(json.dumps(json.loads(x), indent=2)) for x in Path("data/traces.jsonl").read_text().splitlines()[-10:]]'
```

### Phase 7: turn observability into an Agent Zoo

The browser dashboard at `http://localhost:8080` turns the protocol graph into a visual workspace. Users submit a topic, agent limit, and tool selection; the dashboard sends the task to the builder over A2A and receives live status through Server-Sent Events. No Node toolchain or frontend build is required.

The zoo adds a durable collaboration and event ledger in `data/zoo.sqlite`. Agents post a public plan before work, publish an observation afterward, critique one peer, and appoint the final agent as spokesperson for a team decision. These are explicit communication artifacts, not hidden chain-of-thought. Message content is capped at 2,000 characters and rounds are schema-bounded to prevent loops.

Every meaningful transition is written as a sequenced event: task queueing, builder validation, Ollama crew design, agent creation, A2A dispatch, runner receipt, inference-slot waiting, agent work, MCP calls, board posts, critiques, decisions, and completion. Cursor-based SSE delivers events individually, making long serialized waits understandable rather than visually silent.

The UI presents an animated architecture path, live activity timeline, clickable agent cards, tool allowlists, current status, a chat-style message board, resource controls, and final structured output. An agent detail drawer shows its mission prompt, activity history, and sent or received messages. The dashboard remains a view over the existing architecture rather than a shortcut around it: task submission still enters through builder A2A, execution remains in the runner, and tools remain MCP-only.

## Running the demonstration

```bash
cp .env.example .env
# Set the private Ollama URL in .env.
docker compose up --build
```

Open `http://localhost:8080` for the visual Agent Zoo. For protocol-level verification, use another terminal:

```bash
curl http://localhost:8001/.well-known/agent-card.json
curl http://localhost:8002/.well-known/agent-card.json
conda run -n multiverse-foundry python -m src.a2a \
  --config configs/example-tasks/research.yaml
```

The expected path is host client → builder A2A → runner A2A → LangGraph branches → MCP/Ollama → ordered response.

## Security and trust boundaries

- `.env` and `data/` are ignored by Git and excluded from the Docker build context.
- Model output is Pydantic-validated before it controls graph construction.
- Tool visibility is deny-by-default through each agent's allowlist.
- File writes cannot escape the configured data directory.
- The calculator does not evaluate Python code.
- Web search targets a fixed provider rather than accepting an arbitrary fetch URL.
- Checkpoint deserialization explicitly allows only known application models.
- Local telemetry redacts sensitive-looking metadata and omits prompt/response bodies.

This remains an educational system, not a hardened multi-tenant platform. The A2A ports have no authentication, Wikipedia search is limited, and model-generated claims must be checked against actual tool results.

## Suggested article and video outline

1. Start with the 8GB constraint and explain why pretending it does not exist produces misleading demos.
2. Show the task config and validated builder output.
3. Draw the `Send` fan-out graph and change `MAX_CONCURRENCY` in a mocked test.
4. Follow one MCP tool call across the process boundary.
5. Trigger `resource-request.yaml`, stop the container, and resume the SQLite thread.
6. `curl` both A2A cards and submit a task through the builder.
7. Tail `data/traces.jsonl` while a run executes.
8. Close with what changes—and what does not—when more GPU capacity arrives.

## Next experiments

- Optional Postgres checkpoints when several A2A runner replicas need shared state.
- A richer graph visualization and playback timeline in the Agent Zoo.
- Multiple Ollama endpoints for a genuine distributed concurrency demonstration.
- Stronger citation verification and result synthesis after branch fan-in.
- Authentication and authorization on A2A and MCP transports.
- Applying the runner boundary to the crAPI LLM Security Lab agents.
