# Multiverse Foundry

**Serialized on 8GB, engineered for a swarm.**

Multiverse Foundry is a configurable agent factory and visual Agent Zoo. A validated task passes through an A2A builder service, which designs a task-specific crew for a parallel-shaped LangGraph runner. Agents use allowlisted MCP tools, exchange bounded public messages, persist checkpoints and activity locally, and stream live status to the browser while remote Ollama inference remains serialized by default for an 8GB GPU.

## Implemented phases

Phase 0 provides the repository skeleton, strict Pydantic task validation, schema-agnostic response definitions, Docker and Conda workflows, and persistent local storage.

Phase 1 adds:

- environment-backed Ollama host and model settings;
- a remote Ollama client using `langchain-ollama`;
- a minimal `START → call_model → END` LangGraph workflow;
- CLI health checks and model invocation;
- mocked graph tests plus a verified live round trip through Docker Compose.

Phase 2 adds:

- a Pydantic-validated `AgentSpec` schema for role, system prompt, tool allowlist, and handoff order;
- a builder LangGraph node that converts a task config into a crew;
- JSON Schema-constrained Ollama output with explicit parsing and validation;
- retries that return validation feedback to the model;
- cross-field safeguards for unique roles, consecutive handoffs, agent limits, and tool allowlists.

Phase 3 adds:

- a `Send`-based fan-out graph that maps each generated specification to an agent branch;
- reducer-backed fan-in and deterministic result ordering;
- a `MAX_CONCURRENCY` semaphore that defaults to serialized model calls;
- schema-agnostic `task_input` data so task configs carry an actual subject and context;
- an end-to-end entry point that builds the crew, executes every branch, and prints both specifications and results.

Phase 4 adds:

- separate stdio MCP servers for Wikipedia search, sandboxed file writes, and arithmetic;
- per-agent tool binding restricted by each generated allowlist;
- a bounded tool-call loop that returns MCP results to Ollama;
- structured `ResourceRequest` interrupts for missing tools;
- `Command(resume=...)` support using durable LangGraph thread IDs;
- SQLite checkpoints under `/app/data/checkpoints.sqlite` in the shared Docker volume, preserved independently of containers and images.

Phase 5 adds:

- separate long-running builder and runner A2A services;
- A2A 1.0 JSON-RPC agent cards and task messaging;
- builder-to-runner discovery and dispatch over the Compose network;
- host ports `8001` and `8002` for card inspection and integration;
- an A2A client CLI for submitting task configs.

Phase 6 adds:

- privacy-preserving JSONL telemetry under `/app/data/traces.jsonl` in Docker;
- timing across builder, runner, agent, MCP, and A2A boundaries;
- active-branch measurements that make the concurrency dial observable;
- automatic redaction of sensitive-looking metadata;
- a community-facing architecture narrative and demo outline.

Phase 7 — Agent Zoo adds:

- a FastAPI browser dashboard at `http://localhost:8080`;
- task submission through the builder's A2A interface;
- live SSE updates without a frontend build pipeline;
- persistent agent cards, run status, results, and a shared message board;
- bounded public planning, observation, peer-critique, and team-decision rounds;
- a sequenced live activity feed, active architecture path, and clickable agent detail drawer;
- explicit public rationale rather than hidden chain-of-thought.

## Quick start with Docker Compose

Docker Compose is the recommended way to build and run Multiverse Foundry. It keeps the runtime isolated and closely matches how the project will be deployed. Conda is not required for this workflow.

```bash
cp .env.example .env
```

Set `OLLAMA_HOST` in `.env` to your private Ollama URL. Do not put a private network address in tracked files. Then build and start the builder and runner A2A services:

```bash
docker compose up --build
```

The services remain running. Open the Agent Zoo dashboard:

```text
http://localhost:8080
```

The dashboard submits tasks over A2A and updates live through SSE. You can also inspect the builder card or submit from the CLI:

```bash
curl http://localhost:8001/.well-known/agent-card.json
conda run -n multiverse-foundry python -m src.a2a \
  --config configs/example-tasks/research.yaml
```

For subsequent starts, when neither dependencies nor the Dockerfile have changed, use `docker compose up`. The builder designs the crew and dispatches it to the runner over A2A; the runner executes independent branches and exposes only each branch's allowlisted MCP tools. Search currently uses Wikipedia's OpenSearch API, so claims not supported by returned MCP results must still be treated as unverified.

## Optional local development with Conda

Use Conda only when you want to run tests, debug Python directly, or use host-based IDE tooling without rebuilding an image. These commands are an alternative development workflow, not prerequisites for Docker Compose.

```bash
conda env create -f environment.yml
conda activate multiverse-foundry
python -m src.graph --check
python -m src.builder --config configs/example-tasks/research.yaml
python -m src.builder --config configs/example-tasks/research.yaml --validate-only
python -m pytest
```

After changing Python dependencies, update the existing environment with:

```bash
conda env update -f environment.yml --prune
```

## Configuration

Copy `.env.example` to `.env`. The defaults are:

| Variable | Purpose | Default |
|---|---|---|
| `OLLAMA_HOST` | Remote Ollama API base URL; must be set in `.env` | No usable default |
| `OLLAMA_MODEL` | Generation model | `qwen3:8b` |
| `OLLAMA_EMBED_MODEL` | Embedding model | `nomic-embed-text:latest` |
| `MAX_CONCURRENCY` | Maximum simultaneous agent branches | `1` |
| `FOUNDRY_DATA_DIR` | Persistent runtime database/telemetry location | `data` locally; Compose overrides to `/app/data` |
| `FOUNDRY_ARTIFACT_DIR` | Agent-generated file location | `artifacts` locally; Compose overrides to `/app/artifacts` |

The runtime consumes `OLLAMA_HOST`, `OLLAMA_MODEL`, `MAX_CONCURRENCY`, `FOUNDRY_DATA_DIR`, and `FOUNDRY_ARTIFACT_DIR`. The embedding model setting is reserved for a later phase.

Task files accept `task_type`, schema-agnostic `task_input`, `allowed_tools`, `required_tools`, `max_agents`, and an optional `response_schema`. Required tools must also be allowed and must be assigned to at least one generated agent. The input mapping carries the subject and context without hardcoding fields for each task type. The response definition is a JSON Schema supplied with each request, allowing later agents to produce task-specific structures without hardcoding one application schema.

## Concurrency dial

The graph always has parallel-shaped `Send` branches, but `MAX_CONCURRENCY=1` allows only one model request at a time. This is the recommended setting for the current 8GB GPU host. On hardware that can safely serve simultaneous requests, test the same graph with:

```bash
MAX_CONCURRENCY=2 docker compose up
```

Only the semaphore limit changes; the graph topology does not. Unit tests verify both a peak concurrency of one and a peak concurrency of two. Higher concurrency against a single memory-constrained Ollama host may reduce performance or exhaust GPU memory.

## Agent Zoo collaboration

The zoo does not expose hidden model reasoning. Agents publish bounded, explicit messages intended for other agents and human viewers. They first post public work plans, then observations, one peer critique each, and one final team decision. Message length and round count are schema-bounded to prevent uncontrolled conversation loops.

A durable sequenced event ledger streams each real action to the browser: builder validation, Ollama crew design, agent creation, A2A dispatch, queue state, agent starts, MCP calls, observations, critiques, decisions, and completion. SSE sends new rows by cursor rather than repeatedly sending full snapshots.

Agent Zoo state is persisted at `/app/data/zoo.sqlite` in the shared named volume, separately from LangGraph checkpoints. Agent cards are clickable and open a detail drawer containing the role's mission prompt, tools, current status, event history, and sent/received messages. The browser also displays the active architecture boundary, live activity timeline, shared message board, resource controls, and final results while preserving the A2A and MCP service boundaries. The **Clear expedition history** button removes Zoo runs, cards, messages, and activity events after confirmation; it does not delete LangGraph checkpoints, generated artifacts, or `traces.jsonl`, and it refuses to run while an expedition is queued or running.

## Generated artifacts

The `file_write` MCP server writes `.md`, `.txt`, and `.json` files to `/app/artifacts`, which Compose bind-mounts to the repository's gitignored `artifacts/` directory. Files are immediately visible in Finder, editors, and the Zoo's **Artifacts** panel. The panel shows filename, size, creating agent when attribution is available, text preview, and a download action. Path traversal and unsupported extensions are rejected.

Artifact files are intentionally separate from the `foundry-data` runtime volume. Clearing Zoo history or deleting the Docker volume does not delete exported artifacts; remove files from the local `artifacts/` directory only when you intentionally want to discard them.

## Local observability

Structured telemetry is appended to `/app/data/traces.jsonl` in the `foundry-data` named volume, which survives container and image replacement. Events contain trace IDs, operation names, durations, statuses, tool names, roles, and concurrency counts. Prompt bodies, model responses, Ollama addresses, and credentials are not recorded.

```bash
make traces
```

The local JSONL sink avoids requiring a cloud account or adding the database-heavy self-hosted Langfuse stack. It is intentionally isolated behind `src/telemetry.py` so a future backend can consume the same event boundary.

## Checkpoints and resource requests

Each run receives a LangGraph thread ID and stores checkpoints in `/app/data/checkpoints.sqlite` inside the shared `foundry-data` volume. If an agent requests a tool without a configured MCP server, the run prints a structured request and pauses. A committed demonstration config intentionally requests a missing `academic_search` server:

```bash
docker compose run --rm foundry -m src \
  --config configs/example-tasks/resource-request.yaml \
  --thread-id resource-demo
```

Keep the reported thread ID, add the server if appropriate, rebuild the image, and resume with:

```bash
docker compose run --rm foundry -m src \
  --config configs/example-tasks/resource-request.yaml \
  --thread-id THREAD_ID \
  --resume retry
```

To deliberately proceed without the missing tool, use `--resume continue_without_tool`; use `--resume cancel` to stop the run. Runner checkpoints remain single-writer SQLite. The low-volume Zoo event ledger is shared by the local services using rollback-journal mode and bounded lock waits. Postgres remains the appropriate upgrade for multiple runner replicas or heavier concurrent writes.

## Docker volume lifecycle

Compose mounts one named volume, `foundry-data`, at `/app/data` in the builder, runner, Zoo, and CLI services. It contains checkpoint state, Zoo history, and traces without writing runtime history into the repository. A separate `./artifacts:/app/artifacts` bind mount exposes only intentionally generated files on the host.

```bash
docker compose down              # stop containers; preserve Foundry state
docker compose down -v           # destructive: delete the volume and all Foundry state
docker compose up --build        # creates an empty volume when none exists
```

Use `docker compose down -v` only when you intentionally want a clean runtime database, checkpoint, and telemetry state. Host-visible files in the gitignored `artifacts/` directory survive volume deletion by design. The repository's ignored `data/` directory is used only by optional host-based Python runs and is not mounted by Compose. To back up internal runtime state before resetting, run `docker compose cp zoo:/app/data ./foundry-data-backup`.

## Docker operations

`docker compose up` is the normal project entry point. You do not also need to activate Conda, invoke the Python module, or use `docker compose run`.

Use one-off containers for diagnostics, config-only validation, or a different task file:

```bash
docker compose run --rm foundry -m src.graph --check
docker compose run --rm foundry -m src.builder --config configs/example-tasks/research.yaml --validate-only
docker compose run --rm foundry -m src.builder --config configs/example-tasks/research.yaml
```

The Docker entrypoint is `python`, so everything after the service name is a Python argument. These commands create a temporary container instead of starting the normal Compose application, making them useful for scripts and CI.

To remove only this project's Compose containers and locally built image, then force a clean image rebuild:

```bash
make docker-reset
docker compose up
```

`docker-reset` deliberately preserves the `foundry-data` volume and never removes the local `artifacts/` directory, so state and exported files survive an image rebuild. It also does not delete unrelated Docker images. Move selected artifacts into a tracked examples directory only when you intentionally want to commit them.

## Project layout

```text
configs/example-tasks/  Versioned task examples
artifacts/              Gitignored host-visible agent outputs
src/builder/            Builder graph, schemas, validation, and CLI
src/graph/              LangGraph orchestration
src/tools/              MCP tool servers
src/a2a/                A2A adapters and servers
src/resource_requests/  Human-in-the-loop resource requests
src/zoo/                Dashboard, event ledger, SSE, and collaboration storage
infra/remote-ollama/    Remote model-host guidance
docs/                   Community-facing write-up
data/                   Optional host-run state only (gitignored; not mounted by Compose)
```

## Models

The available models are enough to continue. `qwen3:8b` is the initial general-purpose default and has produced valid Phase 2 crews using JSON Schema-constrained output. `llama3-groq-tool-use:8b` remains a useful tool-calling comparison, `llama3.1:8b` provides a baseline, and `nomic-embed-text:latest` covers embeddings. No additional model is currently required.

## Roadmap

See [the project brief](multiverse-foundry-project-brief.md) for the phased implementation plan.
