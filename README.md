# caching-service

FastAPI service that builds a payload from two equal-length string lists: each string is uppercased by a
"transformer" (a stand-in for a paid external service), and the results are interleaved. Every transformer
result is cached in Postgres, so each distinct string is transformed once; repeated input returns the
same payload id.

Design: `docs/01-RFC.md` · Spec: `docs/02-spec.yaml` · Tests: `docs/03-test-checklist.md`

## Run

```bash
docker compose up --build        # postgres → migrations → service on :8000
curl localhost:8000/health
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

### External database

Add `POSTGRES_HOST` and `POSTGRES_PORT` (plus that database's credentials) to `.env`, then start only the
migrations and the service, without the bundled postgres:

```bash
lets run-external            # docker compose up --build --no-deps migrations caching-service
```

Use a hostname the containers can reach, **never `localhost`** (inside a container that is the container
itself). For a database running directly on your machine use `host.docker.internal`.

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
uv sync
uv run pytest                                            # unit + integration (integration needs Docker)
uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli migrations/env.py
```

The same commands via [lets](https://lets-cli.org/):

| Command | Does |
|---|---|
| `lets test [-p PATH]` | pytest (default `tests/`) |
| `lets lint` | `mypy` + `ruff` + `black` (each also runnable alone) |
| `lets run [--env FILE]` / `lets stop` | `docker compose [--env-file FILE] up --build` / `docker compose down` |
| `lets run-external [--env FILE]` | migrations + service only, against an external database |
| `lets alembic-upgrade` | apply migrations to the DB set by `POSTGRES_*` |
| `lets alembic-revision -m "..."` | autogenerate a migration |

## Shortcuts and assumptions

- The transformer is `str.upper()` with no latency, behind the `TransformerClient` protocol.
- Postgres is the only cache tier: no Redis, no in-process LRU, no expiry (uppercase is deterministic).
- Two concurrent requests that first see the same string at the same moment may each call the
  transformer once. `ON CONFLICT DO NOTHING` keeps one row. No cross-request locking.
- Empty lists, non-string items, NUL characters and broken Unicode characters are rejected with `422`.
- Limits: 1–1000 items per list, ≤ 10 000 characters per item.
- Payload identity is order-sensitive. The input lists are not stored, only the output.
