# caching-service

FastAPI service that builds a payload from two equal-length string lists: each string is uppercased by a
"transformer" (a stand-in for a paid external service), and the results are interleaved. Every transformer
result is cached in Postgres, so each distinct string is transformed once; repeated input returns the
same payload id.

Design: `docs/01-RFC.md` · Spec: `docs/02-spec.yaml` · Tests: `docs/03-test-checklist.md`

## Requirements

- Docker with Compose, to run the stack and the integration tests (testcontainers).
- [uv](https://docs.astral.sh/uv/) for local development; it installs Python 3.12 from `.python-version`.
- Optional: [lets](https://lets-cli.org/) task runner. Every task in `lets.yaml` wraps a plain `uv` or
  `docker compose` command shown below, so lets is a shortcut, not a requirement.

## Run

```bash
lets run                         # or: docker compose up --build
                                 # postgres → migrations → service on :8000
curl localhost:8000/health
lets stop                        # or: docker compose down (keeps the database volume)
```

## Configuration

The service reads `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (required), `POSTGRES_HOST`
(default `localhost`), `POSTGRES_PORT` (default `5432`) and `LOG_LEVEL` (default `INFO`) from environment
variables.

Docker Compose can take them from an optional `.env` file next to `docker-compose.yml` (git-ignored);
without it, it falls back to `caching`/`caching`/`caching`, `INFO`, and the bundled `postgres:5432`.
Example `.env`:

```dotenv
POSTGRES_USER=caching
POSTGRES_PASSWORD=caching
POSTGRES_DB=caching
LOG_LEVEL=INFO
```

To use a different file: `lets run --env FILE` (runs `docker compose --env-file FILE up --build`).

## API

| Method | Path | Result |
|---|---|---|
| `POST` | `/payload` `{"list_1": [...], "list_2": [...]}` | `201 {"id", "message": "Payload created"}`, or `200 {"id", "message": "Payload already exists"}` |
| `GET` | `/payload/{id}` | `200 {"output": "..."}`, `404`, `422` |
| `GET` | `/health` | `200 {"status": "ok"}` |

## CLI

```bash
uv run cache-cli [-h|--host URL] [-r|--repeat N] [-i|--input FILE|-] [-j|--json JSON] [-o|--output FILE|-] [--help]

uv run cache-cli -j '{"list_1":["first string"],"list_2":["other string"]}' -r 3
echo '{"list_1":["a"],"list_2":["b"]}' | uv run cache-cli -i - -o results.jsonl
```

`-h` is `--host`, as in the brief's usage line. Help is `--help` only. Each iteration POSTs then GETs and
writes one JSON line. Exit codes: `0` ok, `1` HTTP/connection failure, `2` invalid arguments or input.
The CLI ignores environment variables.

## Develop

```bash
uv sync                          # create .venv with dev dependencies
lets test                        # unit + integration (integration needs Docker)
lets lint                        # mypy + ruff + black
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

Git hooks (`.pre-commit-config.yaml`): `lets lint` runs on every commit; `lets test` and `lets audit` also run
before every push.

| lets | Plain command |
|---|---|
| `lets activate-venv` | `source .venv/bin/activate`; every `uv run` task below depends on it |
| `lets test [-p PATH]` | `uv run pytest -vv PATH` (default `tests/`) |
| `lets lint` | runs `lets mypy`, `lets ruff`, `lets black` |
| `lets mypy` | `uv run mypy caching_service cache_cli migrations/env.py` |
| `lets ruff` | `uv run ruff check .` |
| `lets black` | `uv run black --check .` |
| `lets audit` | `uv run pip-audit --skip-editable` (known vulnerabilities in dependencies) |
| `lets run [--env FILE]` | `docker compose [--env-file FILE] up --build` |
| `lets stop` | `docker compose down` |
| `lets alembic-upgrade` | `uv run alembic upgrade head` (DB from `POSTGRES_*` env vars) |
| `lets alembic-revision -m "..."` | `uv run alembic revision --autogenerate -m "..."` |

## Shortcuts and assumptions

- The transformer is `str.upper()` with no latency, behind the `TransformerClient` protocol.
- Postgres is the only cache tier: no Redis, no in-process LRU, no expiry (uppercase is deterministic).
- Two concurrent requests that first see the same string at the same moment may each call the
  transformer once. `ON CONFLICT DO NOTHING` keeps one row. No cross-request locking.
- Empty lists, non-string items, NUL characters and broken Unicode characters are rejected with `422`.
- Limits: 1–1000 items per list, ≤ 10 000 characters per item.
- The brief's sample JSON uses typographic quotes (`“ ”`), which is not valid JSON. It is read as plain
  `"` quotes; the brief's sample output is reproduced exactly.
- Payload identity is order-sensitive. The input lists are not stored, only the output.
