# PRD Delta: Caching Service

**Slug:** caching-service
**Date:** 2026-10-01
**Author:** @odubrovyk
**Phase:** PRD
**Status:** Draft — pending review
**Source brief:** [Python Backend: Caching Service](https://dune-dinner-167.notion.site/Python-Backend-Caching-Service-1832fabcbb3f808f8627c77eb978bae4)

---

## 1. Problem Statement

We need a small service that builds a text payload from two lists of strings. Each string must first go
through a **transformer function**, which stands in for a call to an external service. Calls to external
services cost money and time, so the service must call the transformer **as few times as possible**: once
a string has been transformed, its result is stored and reused for every later request that contains it.

Clients create a payload and get back an **identifier**. They read the payload later by that
identifier. If a client sends the same input twice, they get the **same identifier** back. The service
does not build a second copy.

There is no such service today. This is a new, standalone deployable with no upstream or downstream
dependencies.

## 2. Goal

A Dockerized FastAPI microservice, `caching-service`, with:

- `POST /payload`: takes `list_1` and `list_2` (same length) and returns the payload identifier.
- `GET /payload/{id}`: returns `{"output": "<interleaved transformed strings>"}`.
- Transformer outcomes cached in **PostgreSQL**, so a string already transformed by an earlier request
  is never sent to the transformer again.
- A CLI tool, `cache-cli`, that drives the service from scripts and tests. Its arguments are parsed and
  validated with Pydantic Settings.

## 3. User Stories

- **US-1.** As an API client, I send two equal-length lists of strings and receive an identifier for the
  generated payload.
- **US-2.** As an API client, I fetch a payload by its identifier and receive the generated output.
- **US-3.** As an API client sending an input I sent before, I receive the original identifier. No new
  payload is created and the transformer is not called.
- **US-4.** As the operator paying for the external transformer, each distinct string is transformed at
  most once, across requests and within one request.
- **US-5.** As a developer or QA engineer, I run `cache-cli` against a running service with input from a
  file, stdin or an inline JSON argument, repeat it N times, and write results to a file or stdout.
- **US-6.** As an operator, I start the whole stack (service + Postgres) with one `docker compose up`.

## 4. In Scope

- FastAPI service with the two endpoints above, plus `GET /health` for container health checks.
- Transformer function: **plain `str.upper()`, no simulated latency** (decision 2026-10-01). It sits
  behind a client interface, so a real external call can replace it without touching callers.
- Postgres persistence through async SQLAlchemy 2.0 declarative models, with Alembic migrations.
- Two caches in Postgres:
  - **Transformation cache**: one row per distinct input string → transformed output.
  - **Payload registry**: one row per distinct `(list_1, list_2)` input → identifier + output.
- In-request de-duplication of strings before calling the transformer.
- `cache-cli` with the exact flags from the brief.
- Dockerfile + docker-compose (service, Postgres, one-shot migration container).
- Unit tests and integration tests (testcontainers Postgres).

## 5. Out of Scope

- Any cache tier besides Postgres. No Redis, no in-process LRU (decision 2026-10-01: the brief requires
  DB storage, and a per-replica in-memory tier does not reduce transformer calls across replicas).
- Cache expiry or invalidation. Uppercase is deterministic, so a cached result never goes stale.
- Cross-request locking or single-flight on cache misses. Two concurrent requests that both miss on the
  same string may each call the transformer once. This is accepted (see RFC, Risks).
- Authentication, authorization, rate limiting.
- Payload deletion or update endpoints.
- Kubernetes or other orchestration manifests. Docker + compose only for this phase.

## 6. Affected Services

| Service | Change |
|---|---|
| `caching-service` | **New** repo and deployable (FastAPI app + `cache-cli` entry point). |
| Postgres | **New** database `caching` with tables `transformation` and `payload`. |

## 7. Relationship to Existing Product

Standalone. It uses only public packages from PyPI and stdlib `logging`. Code conventions: layered
(routes → use cases → services → repositories), fully typed, `uv`, 120-char lines, SQLAlchemy 2.0
declarative models.

## 8. Draft Acceptance Criteria

### Payload creation
- Valid `list_1`/`list_2` of equal length (1..1000 items, each string ≤ 10 000 chars) → `201 Created`
  with `{"id": "<uuid>", "message": "Payload created"}`.
- Lists of different length → `422`. Nothing is written and the transformer is not called.
- Empty lists, non-string items, missing keys, lists over the limits → `422`.

### Payload reuse
- Re-sending an input previously sent → `200 OK` with the **same** `id` and
  `"message": "Payload already exists"`. Zero transformer calls.
- The order of items and lists matters: swapping `list_1` and `list_2`, or reordering items, is a
  different payload.

### Transformer caching
- A string already in the transformation cache is never sent to the transformer again.
- A string that appears several times in one request is sent to the transformer at most once.
- Across N requests, the transformer call count equals the number of distinct strings seen.

### Payload read
- `GET /payload/{id}` for an existing id → `200` with `{"output": "..."}`. Output = transformed strings
  interleaved `l1[0], l2[0], l1[1], l2[1], …`, joined by `", "`.
- Unknown id → `404`. Malformed id (not a UUID) → `422`.
- The brief's sample input produces exactly
  `"FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"`.

### CLI
- `cache-cli [-h|--host URL] [-r|--repeat N] [-i|--input FILE|-] [-j|--json JSON] [-o|--output FILE|-]
  [--help]`.
- Exactly one of `--input` / `--json` is required. `-` means stdin for `--input` and stdout for
  `--output`.
- `--repeat` must be ≥ 1. `--host` must be an http(s) URL. Invalid arguments → exit code 2 with a
  message on stderr.
- Each iteration does POST then GET and writes one JSON line to the output.
- Service unreachable or non-2xx response → exit code 1 with a message on stderr.

### Deployment
- `docker compose up` brings up Postgres, runs migrations, then starts the service. `GET /health` → 200.

## 9. Dependencies

- PostgreSQL 16 (compose image `postgres:16-alpine`).
- Public PyPI only. No private index and no build credentials: anyone can `uv sync` and `docker compose up`.

## 10. Risks

- **`-h` collision in the brief.** The brief lists `-h` for both `--host` and `--help`. Both cannot
  hold. **Decision:** `-h` = `--host`, help is `--help` only. This is called out in the CLI's own help text.
- **Concurrent misses** can cost one extra transformer call per racing string. Accepted. It is rare and
  bounded, and locking would cost more.
