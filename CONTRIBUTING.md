# Contributing to Segnog

Thanks for your interest in contributing. This guide covers setup, conventions, and the PR process.

## Development Setup

### Prerequisites

- Python 3.11+
- Docker (for DragonflyDB and FalkorDB)
- An OpenRouter API key (or any OpenAI-compatible endpoint)

### Getting started

```bash
# Clone the repo
git clone https://github.com/rafiksalama/Segnog.git
cd Segnog

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Start storage backends
docker-compose up -d dragonfly falkordb

# Configure API keys
cp .secrets.toml.example .secrets.toml
# Edit .secrets.toml with your keys

# Or use environment variables
export MEMORY_SERVICE_EMBEDDINGS__API_KEY=sk-or-...
export MEMORY_SERVICE_LLM__API_KEY=sk-or-...

# Run the service
python -m memory_service.main
```

### Running tests

Tests require the service and backends to be running:

```bash
# Start everything
./service.sh start

# Run the test suite
pytest tests/ -v -s
```

## Making Changes

### Branch naming

- `feat/description` — new features
- `fix/description` — bug fixes
- `refactor/description` — code restructuring
- `docs/description` — documentation only

### Code style

- We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting
- Line length: 100 characters
- Target: Python 3.11
- Run `ruff check .` and `ruff format .` before committing

### Commit messages

Write clear, concise commit messages. Use imperative mood:

- "Fix concurrency bug in group_id scoping" (good)
- "Fixed the bug" (bad)

### What to work on

Check the [issues](https://github.com/rafiksalama/Segnog/issues) for open tasks. Issues labeled `good first issue` are a great starting point.

If you want to work on something not listed, open an issue first to discuss the approach.

## Pull Request Process

1. Fork the repo and create your branch from `main`
2. Make your changes with tests where applicable
3. Run `ruff check .` and `pytest tests/ -v -s`
4. Open a PR against `main` with a clear description of what and why
5. Link any related issues

PRs need at least one review before merging. Keep PRs focused — one concern per PR.

## Project Structure

The codebase is organised in strict dependency layers — each layer may only import from layers below it:

```
transport/ → services/ → storage/, intelligence/, ontology/
messaging/, workers/ → services/, storage/
ontology/ — foundation layer (no internal imports)
```

Key packages:

- `src/memory_service/ontology/` — Schema.org vocabulary + entity name normalization (foundation)
- `src/memory_service/storage/` — persistence backends, split into `short_term/`, `long_term/`, `retrieval/`
- `src/memory_service/intelligence/` — LLM operations, split into `extract/`, `synthesis/`, `evaluation/`, `graph/`
- `src/memory_service/services/` — core business logic (`MemoryService`, `observe_core`)
- `src/memory_service/messaging/` — NATS event bus client and publisher
- `src/memory_service/workers/` — background consolidation workers (REM, curation)
- `src/memory_service/transport/` — REST (`transport/rest/`) and gRPC (`transport/grpc/`) adapters
- `client/memory_client/` — Python client library
- `tests/` — unit, integration, and smoke test suites

## Reporting Bugs

Use the [bug report template](https://github.com/rafiksalama/Segnog/issues/new?template=bug_report.md). Include:

- What you expected vs what happened
- Steps to reproduce
- Environment details (OS, Python version, Docker versions)

## Suggesting Features

Use the [feature request template](https://github.com/rafiksalama/Segnog/issues/new?template=feature_request.md). Describe the problem you're solving, not just the solution you want.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
