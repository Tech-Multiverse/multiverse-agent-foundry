# Project Agent Notes

- Use the `multiverse-foundry` Conda environment (Python 3.12).
- Create the environment from conda-forge only; local Conda defaults require separate Terms acceptance. If `conda env create -f environment.yml` still injects defaults, use `conda create -n multiverse-foundry --override-channels -c conda-forge python=3.12 pip`, then install with `conda run -n multiverse-foundry python -m pip install -e '.[dev]'`.
- Validate task configuration without a model call using `python -m src.builder --config configs/example-tasks/research.yaml --validate-only`; run tests with `python -m pytest`.
- Validate Ollama connectivity with `python -m src.graph --check`, Phase 2 crew generation with `python -m src.builder --config configs/example-tasks/research.yaml`, and the Phase 3 end-to-end workflow with `python -m src --config configs/example-tasks/research.yaml`.
- Use `docker compose up --build` as the canonical runtime workflow. Keep `MAX_CONCURRENCY=1` for the 8GB GPU unless intentionally testing parallel requests.
- Compose stores checkpoints, Zoo state, and traces in the shared `foundry-data` named volume at `/app/data`; generated files go to `/app/artifacts`, bind-mounted to the gitignored host `artifacts/` directory. Optional host runs use ignored `data/` and `artifacts/`. Resume interrupted runs with the same thread ID and `--resume retry|continue_without_tool|cancel`.
- Phase 5 runs builder and runner as A2A services on ports 8001 and 8002. Submit tasks with `python -m src.a2a --config configs/example-tasks/research.yaml`; builder-to-runner calls must remain over A2A rather than direct invocation.
- Phase 7 serves the Agent Zoo on port 8080. Collaboration messages are explicit public artifacts, never hidden chain-of-thought; keep rounds and message lengths bounded.
- Zoo activity is a sequenced event ledger at `/app/data/zoo.sqlite` in Compose, streamed through cursor-based SSE. Preserve live builder, A2A, runner, agent, MCP, planning, critique, and decision events when extending workflows.
- Do not create Git commits; the repository owner manages commits and remotes.
