# Remote Ollama

The application reads the Ollama endpoint from `OLLAMA_HOST`; private network addresses are never embedded in tracked application code or documentation. Copy `.env.example` to the gitignored `.env` file and replace the placeholder whenever the model host changes networks.

Check connectivity and inspect exact model tags with:

```bash
docker compose run --rm foundry -m src.graph --check
```

Phase 1 uses `langchain-ollama` to send requests through a single-node LangGraph workflow. Do not expose an unauthenticated Ollama endpoint to an untrusted network.
