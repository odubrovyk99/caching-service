# Caching Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `caching-service`, a Dockerized FastAPI microservice that turns two equal-length string lists into an interleaved, uppercased payload, caches every transformer result in Postgres so each distinct string is transformed once, reuses payload ids for repeated input, and ships a Pydantic-Settings CLI (`cache-cli`) to drive it.

**Architecture:** Layered: `api/routes` → `use_cases` → `services` → `db/repositories` → SQLAlchemy models, with the transformer behind a `clients/` protocol. Postgres is the only cache. Transformations are keyed by sha256 of the string; payloads by sha256 of canonical JSON of both lists. Every write uses `INSERT … ON CONFLICT DO NOTHING`, so concurrent requests converge without locks. The CLI is a second package in the same distribution and reuses the server's request schema for client-side validation.

**Tech Stack:** Python 3.12, uv, FastAPI ≥ 0.121, SQLAlchemy 2.0 async + asyncpg, Alembic, Pydantic v2 + pydantic-settings, httpx, stdlib logging, pytest + pytest-asyncio + testcontainers[postgres], ruff, black, mypy, Docker + compose.

**Spec:** `docs/02-spec.yaml` (acceptance criteria AC-1..AC-39). Design rationale is in `docs/01-RFC.md`, test IDs in `docs/03-test-checklist.md`. Read the spec's ACs alongside each task. Test names below cite the AC or checklist ID they pin.

## Global Constraints

- Repo root: `caching-service/` (the parent of this `docs/` folder). All paths below are relative to it.
- Python `>=3.12`. Use `uv` for everything, never `pip`. If the shell says `uv: command not found`, prefix commands with `PATH="$HOME/.pyenv/versions/3.12.12/bin:$PATH"`.
- Every dependency comes from public PyPI. No credentials anywhere (code, Dockerfile, compose). Logging is stdlib `logging`. Never read, create or edit any `.env*` file.
- Line length 120. `ruff check .`, `black --check .` and `mypy caching_service cache_cli migrations/env.py` must be clean at the end of every task. Code blocks in this plan are not guaranteed black-formatted, so run `uv run black . && uv run ruff check --fix .` before each lint check. mypy covers `migrations/env.py` only, because a revision file named `0001_….py` is not a valid module name for mypy.
- f-strings only, except logging calls, which pass lazy `%s` arguments (`logger.info("… %s", value)`). Imports ordered stdlib → third-party → local. Module constants directly after imports.
- **Docstrings:** full Google style on every production class, function and method: summary, blank line, `Args:` listing every parameter, `Returns:`/`Yields:` for non-`None` returns, `Raises:` where relevant. Never trim to a one-liner. Test functions carry no docstrings; their names say what they pin.
- **Pydantic vs dataclass:** Pydantic only where validation or the HTTP/CLI boundary needs it (request/response models, settings). Internal values built by our own code are `@dataclass(frozen=True, slots=True)`.
- SQLAlchemy: `DeclarativeBase` + `Mapped[...]` + `mapped_column()` only. Table names singular lowercase. Index names `idx_{table}__{field}`.
- Exact strings from the spec: `"Payload created"`, `"Payload already exists"`, `"Payload not found"`, separator `", "`, `{"status": "ok"}`.
- Limits: `MAX_LIST_LENGTH = 1000`, `MAX_STRING_LENGTH = 10_000`. These cap the batched transformation insert at 2 000 × 3 = 6 000 query arguments, far under asyncpg's 32 767.
- The session dependency is declared `Depends(get_session, scope="function")`, so the commit happens before the response is sent.
- **Commits:** at each "Commit" step, print the `git` commands and stop for the user to run them. Do not run `git init`, `git add` or `git commit` yourself (user preference). Lint and test commands are fine to run.
- Integration tests need a running Docker daemon (testcontainers).

## Review Focus

The spec says nothing about these inputs, but each one turns into a 500 or wrong behaviour if mishandled. Most likely to bite first:

1. **A lone surrogate (`"\ud800"`) or NUL (`"\u0000"`) inside a list item.** Expected: `422`. Two separate failures produce a `500` instead: Postgres rejects NUL / UTF-8 encoding rejects surrogates at insert, **and** FastAPI's default 422 handler echoes the input back and crashes UTF-8-encoding it. Pinned by Task 3 `test_rejects_strings_postgres_cannot_store` and Task 8 `test_invalid_bodies_are_rejected_without_side_effects[lone_surrogate|nul_character]`.
2. **A cached transformer output that is the empty string.** Expected: a cache hit. `if not output:` silently re-calls the transformer. Pinned by Task 6 `test_cached_empty_string_counts_as_a_hit` and Task 8 `test_cached_empty_string_is_not_transformed_again`.
3. **Two concurrent requests sharing strings in opposite order.** Expected: both `201`. Unsorted multi-row `ON CONFLICT` inserts take row locks in different orders and can deadlock. Pinned by Task 8 `test_overlapping_requests_in_opposite_order_do_not_deadlock`.
4. **A `HOST`/`REPEAT`/`OUTPUT` variable already exported in the user's shell.** Expected: the CLI ignores it. `env_prefix` does not apply to aliased fields. Pinned by Task 9 `test_environment_variables_are_ignored`.
5. **A failing commit.** Expected: the client sees `500`, not `201`. FastAPI's default yield-dependency scope commits after the response is sent. Pinned by Task 8 `test_commit_failure_reaches_the_client`.

---

## File Structure

```
caching-service/
├── pyproject.toml            # deps, console script, pytest/black config
├── uv.lock
├── .gitignore / .dockerignore    # ruff, mypy, black and pytest config live in pyproject.toml
├── alembic.ini
├── Dockerfile / docker-compose.yml / README.md
├── migrations/
│   ├── env.py                # async Alembic env; URL from ini or POSTGRES_* settings
│   ├── script.py.mako        # generated by `alembic init`
│   └── versions/0001_create_transformation_and_payload.py
├── caching_service/
│   ├── constants.py          # limits, messages, separator
│   ├── core/config.py        # Settings (POSTGRES_* parts, LOG_LEVEL)
│   ├── core/db.py            # engine + sessionmaker factories
│   ├── core/logging.py       # stdlib logging, configured once in lifespan
│   ├── db/models/{base,transformation,payload}.py
│   ├── db/repositories/{transformation,payload}_repository.py
│   ├── clients/transformer_client.py   # TransformerClient protocol + UppercaseTransformerClient
│   ├── services/{transformation,payload}_service.py
│   ├── use_cases/{create_payload,get_payload}.py
│   ├── schemas/{payload,transformation,health}.py
│   ├── utils/{hashing,interleave}.py
│   └── api/{app,lifespan,dependencies,errors,responses}.py, api/routes/{payload,health}.py
├── cache_cli/
│   ├── constants.py / settings.py / io.py / runner.py / main.py
└── tests/
    ├── fakes.py / samples.py
    ├── units/{utils/, schemas/, clients/, services/, use_cases/, cli/}
    └── integration/{conftest.py, database.py, db/, api/, cli/}
```

---

### Task 1: Repository scaffold and shared constants

**Files:**
- Create: `pyproject.toml` (also holds ruff, mypy, black and pytest config), `.python-version` (`3.12`), `.gitignore`, `.dockerignore`
- Create: `caching_service/__init__.py`, `caching_service/constants.py`, `cache_cli/__init__.py`
- Test: none. Pure scaffolding and constants; the first tests arrive in Task 2.

**Interfaces:**
- Consumes: nothing.
- Produces: `caching_service.constants`: `OUTPUT_SEPARATOR: str`, `MAX_LIST_LENGTH: int`, `MAX_STRING_LENGTH: int`, `PAYLOAD_CREATED_MESSAGE: str`, `PAYLOAD_EXISTS_MESSAGE: str`, `PAYLOAD_NOT_FOUND_DETAIL: str`. Console script name `cache-cli` → `cache_cli.main:entrypoint` (implemented in Task 10).

- [ ] **Step 1: Create the project files**

`pyproject.toml`:

```toml
[project]
name = "caching-service"
version = "0.1.0"
description = "Payload generation service with a Postgres-backed transformer cache"
requires-python = ">=3.12"
dependencies = [
    "fastapi[standard]>=0.121.0",
    "pydantic>=2.10",
    "pydantic-settings>=2.14",
    "sqlalchemy[asyncio]>=2.0.38",
    "asyncpg>=0.30.0",
    "alembic>=1.14",
    "httpx>=0.28.1",
]

[project.scripts]
cache-cli = "cache_cli.main:entrypoint"

[dependency-groups]
dev = [
    "pytest>=8.3.5",
    "pytest-asyncio>=0.26.0",
    "pytest-cov>=6.0.0",
    "testcontainers[postgres]>=4.10.0",
    "mypy>=1.15",
    "ruff>=0.9",
    "black>=25.1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["caching_service", "cache_cli"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["."]
addopts = "--import-mode=importlib"

[tool.black]
line-length = 120
target-version = ["py312"]

[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = ["A", "E", "F", "UP", "B", "SIM", "PIE", "TID", "C4", "EXE", "N", "W", "I", "Q"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
explicit_package_bases = true
plugins = ["pydantic.mypy"]
```

`.gitignore`:

```
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
```

`.dockerignore`:

```
.venv
.git
.pytest_cache
.mypy_cache
.ruff_cache
htmlcov
tests
docs
```

`caching_service/__init__.py` and `cache_cli/__init__.py`: empty files.

- [ ] **Step 2: Pin Python and install dependencies**

Run: `uv python pin 3.12 && uv sync && uv run python --version`
Expected: writes `.python-version`, creates `.venv` and `uv.lock` from public PyPI (no credentials), prints `Python 3.12.x`. Without the pin, uv picks the newest local interpreter (e.g. 3.14) while Docker runs 3.12.

- [ ] **Step 3: Write the constants**

`caching_service/constants.py`:

```python
OUTPUT_SEPARATOR = ", "

MAX_LIST_LENGTH = 1000
MAX_STRING_LENGTH = 10_000

PAYLOAD_CREATED_MESSAGE = "Payload created"
PAYLOAD_EXISTS_MESSAGE = "Payload already exists"
PAYLOAD_NOT_FOUND_DETAIL = "Payload not found"
```

- [ ] **Step 4: Lint**

Run: `uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli`
Expected: no errors.

- [ ] **Step 5: Commit (print for the user, do not run)**

```bash
git init
git add pyproject.toml uv.lock .python-version .gitignore .dockerignore caching_service cache_cli docs
git commit -m "chore: scaffold caching-service with shared constants"
```

---

### Task 2: Hashing and interleaving helpers

**Files:**
- Create: `caching_service/utils/__init__.py` (empty), `caching_service/utils/hashing.py`, `caching_service/utils/interleave.py`
- Test: `tests/units/utils/test_hashing.py`, `tests/units/utils/test_interleave.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `sha256_hex(value: str) -> str` (64 lowercase hex chars); `payload_input_hash(list_1: Sequence[str], list_2: Sequence[str]) -> str`; `interleave(first: Sequence[str], second: Sequence[str]) -> list[str]` (raises `ValueError` on unequal lengths).

- [ ] **Step 1: Write the failing tests**

`tests/units/utils/test_hashing.py`:

```python
from caching_service.utils.hashing import payload_input_hash, sha256_hex


def test_sha256_hex_matches_known_vector() -> None:
    assert sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_hex_returns_64_lowercase_hex_chars_for_unicode() -> None:
    digest = sha256_hex("Straße 👋")

    assert len(digest) == 64
    assert digest == digest.lower()
    int(digest, 16)


def test_payload_input_hash_is_deterministic() -> None:
    assert payload_input_hash(["a", "b"], ["c", "d"]) == payload_input_hash(["a", "b"], ["c", "d"])


def test_payload_input_hash_changes_when_lists_are_swapped() -> None:
    assert payload_input_hash(["a"], ["b"]) != payload_input_hash(["b"], ["a"])


def test_payload_input_hash_changes_when_items_are_reordered() -> None:
    assert payload_input_hash(["a", "b"], ["c", "d"]) != payload_input_hash(["b", "a"], ["c", "d"])


def test_payload_input_hash_does_not_collide_on_separator_characters() -> None:
    assert payload_input_hash(["a,b"], ["c"]) != payload_input_hash(["a"], ["b,c"])
```

`tests/units/utils/test_interleave.py`:

```python
import pytest

from caching_service.utils.interleave import interleave


def test_interleave_alternates_items() -> None:
    assert interleave(["a", "b"], ["c", "d"]) == ["a", "c", "b", "d"]


def test_interleave_rejects_unequal_lengths() -> None:
    with pytest.raises(ValueError):
        interleave(["a", "b"], ["c"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/units/utils -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'caching_service.utils'`

- [ ] **Step 3: Implement**

`caching_service/utils/hashing.py`:

```python
import hashlib
import json
from collections.abc import Sequence


def sha256_hex(value: str) -> str:
    """Hash a string into the fixed-width key used by the cache tables.

    A fixed-width key is used instead of the raw text because a Postgres btree index entry is capped at
    about 2.7 KB, so a unique index on raw text would reject long inputs.

    Args:
        value: Text to hash. Must be encodable as UTF-8.

    Returns:
        The SHA-256 digest as 64 lowercase hex characters.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def payload_input_hash(list_1: Sequence[str], list_2: Sequence[str]) -> str:
    """Compute the identity of a payload request.

    The lists are encoded as a JSON array rather than joined with a separator, so items that contain the
    separator cannot make two different inputs collide. Order matters: reordering changes the output, so
    it must change the identity.

    Args:
        list_1: First input list, in request order.
        list_2: Second input list, in request order.

    Returns:
        The SHA-256 hex digest of the canonical JSON encoding of both lists.
    """
    canonical = json.dumps([list(list_1), list(list_2)], ensure_ascii=False, separators=(",", ":"))
    return sha256_hex(canonical)
```

`caching_service/utils/interleave.py`:

```python
from collections.abc import Sequence


def interleave(first: Sequence[str], second: Sequence[str]) -> list[str]:
    """Alternate the items of two equal-length sequences.

    Args:
        first: Items placed at even positions.
        second: Items placed at odd positions.

    Returns:
        ``[first[0], second[0], first[1], second[1], ...]``.

    Raises:
        ValueError: If the sequences differ in length.
    """
    return [item for pair in zip(first, second, strict=True) for item in pair]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/units/utils -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Lint and commit (print for the user)**

Run: `uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli`

```bash
git add caching_service/utils tests/units/utils
git commit -m "feat: add payload hashing and interleave helpers"
```

---

### Task 3: Request, response and record schemas

**Files:**
- Create: `caching_service/schemas/__init__.py` (empty), `caching_service/schemas/payload.py`, `caching_service/schemas/transformation.py`, `caching_service/schemas/health.py`
- Test: `tests/units/schemas/test_payload_schema.py`

**Interfaces:**
- Consumes: `MAX_LIST_LENGTH`, `MAX_STRING_LENGTH` from Task 1.
- Produces:
  - `PayloadCreateRequest(list_1: list[str], list_2: list[str])`: `extra="forbid"`, strict strings, 1..1000 items, ≤10 000 chars per item, no NUL / lone surrogates, equal lengths (error text contains `"same length"`).
  - `PayloadCreateResponse(id: UUID, message: str)`, `PayloadReadResponse(output: str)`.
  - `PayloadCreationResult(payload_id: UUID, created: bool)`: frozen dataclass.
  - `TransformationRecord(input_hash: str, input_value: str, output_value: str)`: frozen dataclass.
  - `HealthResponse(status: str)`.

- [ ] **Step 1: Write the failing tests**

`tests/units/schemas/test_payload_schema.py`:

```python
import pytest
from pydantic import ValidationError

from caching_service.constants import MAX_LIST_LENGTH, MAX_STRING_LENGTH
from caching_service.schemas.payload import PayloadCreateRequest


def test_accepts_equal_length_lists() -> None:
    request = PayloadCreateRequest.model_validate({"list_1": ["a", "b"], "list_2": ["c", "d"]})

    assert request.list_1 == ["a", "b"]
    assert request.list_2 == ["c", "d"]


def test_rejects_lists_of_different_length() -> None:
    with pytest.raises(ValidationError, match="same length"):
        PayloadCreateRequest.model_validate({"list_1": ["a", "b"], "list_2": ["c"]})


def test_rejects_empty_lists() -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": [], "list_2": []})


@pytest.mark.parametrize("bad_item", [123, None, True, {"x": 1}])
def test_rejects_non_string_items_without_coercion(bad_item: object) -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": [bad_item], "list_2": ["a"]})


def test_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": ["a"], "list_2": ["b"], "list_3": ["c"]})


def test_rejects_missing_keys() -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": ["a"]})


def test_accepts_lists_at_the_length_limit() -> None:
    items = ["x"] * MAX_LIST_LENGTH

    PayloadCreateRequest.model_validate({"list_1": items, "list_2": items})


def test_rejects_lists_over_the_length_limit() -> None:
    items = ["x"] * (MAX_LIST_LENGTH + 1)

    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": items, "list_2": items})


def test_accepts_items_at_the_string_limit() -> None:
    PayloadCreateRequest.model_validate({"list_1": ["x" * MAX_STRING_LENGTH], "list_2": ["y"]})


def test_rejects_items_over_the_string_limit() -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": ["x" * (MAX_STRING_LENGTH + 1)], "list_2": ["y"]})


@pytest.mark.parametrize("unstorable", ["a\x00b", "\ud800"], ids=["nul_character", "lone_surrogate"])
def test_rejects_strings_postgres_cannot_store(unstorable: str) -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": [unstorable], "list_2": ["a"]})


def test_accepts_empty_string_items() -> None:
    request = PayloadCreateRequest.model_validate({"list_1": [""], "list_2": ["a"]})

    assert request.list_1 == [""]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/units/schemas -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'caching_service.schemas'`

- [ ] **Step 3: Implement**

`caching_service/schemas/payload.py`:

```python
from dataclasses import dataclass
from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr, model_validator

from caching_service.constants import MAX_LIST_LENGTH, MAX_STRING_LENGTH


def _reject_nul(value: str) -> str:
    """Reject strings containing NUL, which Postgres TEXT cannot store.

    Without this a NUL would pass validation and surface as a 500 at insert time. Lone surrogates need no
    check here: pydantic's ``str`` validation already rejects them (``string_unicode``).

    Args:
        value: A single list item.

    Returns:
        The unchanged value.

    Raises:
        ValueError: If the value contains a NUL character.
    """
    if "\x00" in value:
        raise ValueError("strings must not contain NUL characters")
    return value


PayloadItem = Annotated[StrictStr, Field(max_length=MAX_STRING_LENGTH), AfterValidator(_reject_nul)]
PayloadItems = Annotated[list[PayloadItem], Field(min_length=1, max_length=MAX_LIST_LENGTH)]


class PayloadCreateRequest(BaseModel):
    """Body of ``POST /payload``.

    Attributes:
        list_1: Strings placed at even positions of the output.
        list_2: Strings placed at odd positions of the output; same length as ``list_1``.
    """

    model_config = ConfigDict(extra="forbid")

    list_1: PayloadItems
    list_2: PayloadItems

    @model_validator(mode="after")
    def _lists_have_equal_length(self) -> Self:
        """Enforce the equal-length rule that interleaving depends on.

        Returns:
            The validated model.

        Raises:
            ValueError: If the lists differ in length.
        """
        if len(self.list_1) != len(self.list_2):
            raise ValueError("list_1 and list_2 must have the same length")
        return self


class PayloadCreateResponse(BaseModel):
    """Body returned by ``POST /payload``.

    Attributes:
        id: Identifier of the created or reused payload.
        message: Whether the payload was created or already existed.
    """

    id: UUID
    message: str


class PayloadReadResponse(BaseModel):
    """Body returned by ``GET /payload/{id}``.

    Attributes:
        output: Interleaved transformed strings joined by ``", "``.
    """

    output: str


@dataclass(frozen=True, slots=True)
class PayloadCreationResult:
    """Outcome of storing a payload, before it is mapped to HTTP.

    A dataclass, not a pydantic model: it is built only from values our own code produced, so there is
    nothing to validate.

    Attributes:
        payload_id: Identifier of the created or reused payload.
        created: ``True`` if this call created the payload, ``False`` if it already existed.
    """

    payload_id: UUID
    created: bool
```

`caching_service/schemas/transformation.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TransformationRecord:
    """A transformer result ready to be cached.

    A dataclass, not a pydantic model: the hash is ours and the output comes from our own transformer, so
    there is nothing to validate, and it is built once per new string on the request path.

    Attributes:
        input_hash: ``sha256_hex(input_value)``.
        input_value: The original string.
        output_value: The transformer's result for ``input_value``.
    """

    input_hash: str
    input_value: str
    output_value: str
```

`caching_service/schemas/health.py`:

```python
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Body returned by ``GET /health``.

    Attributes:
        status: Always ``"ok"`` while the process serves requests.
    """

    status: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/units/schemas -v`
Expected: PASS (16 tests incl. parametrized)

- [ ] **Step 5: Lint and commit (print for the user)**

Run: `uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli`

```bash
git add caching_service/schemas tests/units/schemas
git commit -m "feat: add payload request/response schemas with storage-safe validation"
```

---

### Task 4: Settings, ORM models and the Alembic migration

**Files:**
- Create: `caching_service/core/__init__.py` (empty), `caching_service/core/config.py`
- Create: `caching_service/db/__init__.py` (empty), `caching_service/db/models/__init__.py`, `caching_service/db/models/base.py`, `caching_service/db/models/transformation.py`, `caching_service/db/models/payload.py`
- Create (via `alembic init`, then overwrite): `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`
- Create: `migrations/versions/0001_create_transformation_and_payload.py`
- Test: `tests/integration/database.py`, `tests/integration/conftest.py`, `tests/integration/db/test_migrations.py`, `tests/units/core/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Settings` (no env prefix): `postgres_host` (default `localhost`), `postgres_port` (default `5432`), required `postgres_user`, `postgres_password: SecretStr`, `postgres_db`; `log_level` (`LOG_LEVEL`, default `INFO`); property `database_url -> sqlalchemy.URL` (asyncpg, parts escaped). `get_settings() -> Settings` is `lru_cache`d and has `.cache_clear()`.
  - `Base`, `TransformationModel` (table `transformation`: `id`, `input_hash`, `input_value`, `output_value`, `created_at`), `PayloadModel` (table `payload`: `id: UUID`, `input_hash`, `output`, `created_at`), all exported from `caching_service.db.models`.
  - Test helpers in `tests/integration/database.py`: `upgrade_to_head(url)`, `downgrade_to_base(url)`, `fetch_table_names(url) -> set[str]`, `fetch_unique_index_names(url) -> set[str]`, `truncate_tables(url)`, `async count_rows(engine, model) -> int`, `set_postgres_env(monkeypatch, url)` (splits a container URL into `POSTGRES_*` env vars).
  - Fixtures in `tests/integration/conftest.py`: `postgres_url` (session, migrated), `engine` (per test, NullPool, tables truncated), `session_factory`, `session`.

- [ ] **Step 1: Generate the Alembic skeleton**

Run: `uv run alembic init -t async migrations`
Expected: creates `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/README`, `migrations/versions/`. Delete `migrations/README`.

- [ ] **Step 2: Write the integration test helpers and the failing migration test**

`tests/integration/database.py`:

```python
import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, make_url, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from caching_service.db.models import Base

PROJECT_ROOT = Path(__file__).resolve().parents[2]

type AlembicCommand = Callable[[Config, str], None]


def _in_worker_thread[T](function: Callable[[], T]) -> T:
    # Alembic's async env.py and these helpers call asyncio.run, which replaces and then clears the
    # calling thread's event loop. A worker thread keeps that away from pytest-asyncio's loop.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(function).result()


def _migrate_on_connection(connection: Connection, alembic_command: AlembicCommand, revision: str) -> None:
    # env.py migrates on a connection passed in config.attributes instead of building its own engine.
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    alembic_command(config, revision)


def _run_alembic(database_url: str, alembic_command: AlembicCommand, revision: str) -> None:
    async def _run() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        async with engine.begin() as connection:
            await connection.run_sync(_migrate_on_connection, alembic_command, revision)
        await engine.dispose()

    _in_worker_thread(lambda: asyncio.run(_run()))


def upgrade_to_head(database_url: str) -> None:
    _run_alembic(database_url, command.upgrade, "head")


def downgrade_to_base(database_url: str) -> None:
    _run_alembic(database_url, command.downgrade, "base")


def _fetch_names(database_url: str, query: str) -> set[str]:
    async def _fetch() -> set[str]:
        engine = create_async_engine(database_url, poolclass=NullPool)
        async with engine.connect() as connection:
            names = set((await connection.execute(text(query))).scalars())
        await engine.dispose()
        return names

    return _in_worker_thread(lambda: asyncio.run(_fetch()))


def fetch_table_names(database_url: str) -> set[str]:
    return _fetch_names(database_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")


def fetch_unique_index_names(database_url: str) -> set[str]:
    return _fetch_names(
        database_url,
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexdef LIKE 'CREATE UNIQUE INDEX%'",
    )


def truncate_tables(database_url: str) -> None:
    async def _truncate() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE transformation, payload"))
        await engine.dispose()

    _in_worker_thread(lambda: asyncio.run(_truncate()))


async def count_rows(engine: AsyncEngine, model: type[Base]) -> int:
    async with engine.connect() as connection:
        return int(await connection.scalar(select(func.count()).select_from(model)) or 0)


def set_postgres_env(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    # Points Settings (POSTGRES_* variables) at the test container, for tests that run the real lifespan.
    url = make_url(database_url)
    monkeypatch.setenv("POSTGRES_HOST", str(url.host))
    monkeypatch.setenv("POSTGRES_PORT", str(url.port))
    monkeypatch.setenv("POSTGRES_USER", str(url.username))
    monkeypatch.setenv("POSTGRES_PASSWORD", str(url.password))
    monkeypatch.setenv("POSTGRES_DB", str(url.database))
```

`tests/integration/conftest.py`:

```python
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from tests.integration.database import upgrade_to_head

POSTGRES_IMAGE = "postgres:16-alpine"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as container:
        url = container.get_connection_url()
        upgrade_to_head(url)
        yield url


@pytest.fixture
async def engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    # NullPool: every session opens its own connection on the current event loop, which keeps the
    # engine usable from TestClient's separate loop and lets concurrency tests get real parallel sessions.
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE transformation, payload"))
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
```

`tests/integration/db/test_migrations.py` (synchronous on purpose: Alembic's async `env.py` calls `asyncio.run`, which cannot run inside a running loop):

```python
from tests.integration.database import (
    downgrade_to_base,
    fetch_table_names,
    fetch_unique_index_names,
    upgrade_to_head,
)

EXPECTED_TABLES = {"transformation", "payload"}
EXPECTED_UNIQUE_INDEXES = {"idx_transformation__input_hash", "idx_payload__input_hash"}


def test_upgrade_creates_tables_and_unique_indexes(postgres_url: str) -> None:
    assert EXPECTED_TABLES <= fetch_table_names(postgres_url)
    assert EXPECTED_UNIQUE_INDEXES <= fetch_unique_index_names(postgres_url)


def test_downgrade_drops_tables_and_upgrade_restores_them(postgres_url: str) -> None:
    downgrade_to_base(postgres_url)
    try:
        assert not EXPECTED_TABLES & fetch_table_names(postgres_url)
    finally:
        upgrade_to_head(postgres_url)

    assert EXPECTED_UNIQUE_INDEXES <= fetch_unique_index_names(postgres_url)
```

`tests/units/core/test_config.py`:

```python
import pytest

from caching_service.core.config import Settings

POSTGRES_ENV = {
    "POSTGRES_HOST": "db.internal",
    "POSTGRES_PORT": "6543",
    "POSTGRES_USER": "cache",
    "POSTGRES_PASSWORD": "secret",
    "POSTGRES_DB": "caching",
}


@pytest.fixture
def postgres_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in POSTGRES_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.mark.usefixtures("postgres_env")
def test_reads_unprefixed_postgres_variables() -> None:
    settings = Settings()

    assert settings.postgres_host == "db.internal"
    assert settings.postgres_port == 6543
    assert settings.postgres_user == "cache"
    assert settings.postgres_password.get_secret_value() == "secret"
    assert settings.postgres_db == "caching"


@pytest.mark.usefixtures("postgres_env")
def test_builds_an_asyncpg_url_from_the_parts() -> None:
    url = Settings().database_url

    assert url.render_as_string(hide_password=False) == "postgresql+asyncpg://cache:secret@db.internal:6543/caching"


@pytest.mark.usefixtures("postgres_env")
def test_password_with_url_special_characters_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w/rd?#")

    assert Settings().database_url.password == "p@ss:w/rd?#"


@pytest.mark.usefixtures("postgres_env")
def test_password_is_hidden_in_repr() -> None:
    assert "secret" not in repr(Settings())


def test_host_and_port_have_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.setenv(name, POSTGRES_ENV[name])
    for name in ("POSTGRES_HOST", "POSTGRES_PORT"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432


@pytest.mark.usefixtures("postgres_env")
def test_log_level_reads_unprefixed_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    assert Settings().log_level == "DEBUG"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/db/test_migrations.py tests/units/core -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'caching_service.db'` (and `caching_service.core`)

- [ ] **Step 4: Implement settings and models**

`caching_service/core/config.py`:

```python
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy import URL

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Service configuration, read from environment variables.

    The ``POSTGRES_*`` names match the official postgres image's own variables, so one env block can
    configure both the database container and this service.

    Attributes:
        postgres_host: Database host.
        postgres_port: Database port.
        postgres_user: Database user.
        postgres_password: Database password; hidden in ``repr`` and logs.
        postgres_db: Database name.
        log_level: Level for the service's stdlib logging. Validated, so a typo fails at startup.
    """

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    log_level: LogLevel = "INFO"

    @property
    def database_url(self) -> URL:
        """Build the asyncpg connection URL from the separate parts.

        ``URL.create`` escapes each part, so a password containing ``@``, ``:`` or ``/`` stays intact.

        Returns:
            A ``postgresql+asyncpg`` SQLAlchemy URL.
        """
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process.

    Returns:
        The cached ``Settings`` instance.
    """
    return Settings()
```

`caching_service/db/models/base.py`:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models and by Alembic's ``target_metadata``."""
```

`caching_service/db/models/transformation.py`:

```python
from datetime import datetime

from sqlalchemy import CHAR, BigInteger, DateTime, Identity, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from caching_service.db.models.base import Base


class TransformationModel(Base):
    """One cached transformer result per distinct input string.

    Attributes:
        id: Auto-incrementing row number.
        input_hash: ``sha256_hex(input_value)``; unique, used for lookups and ``ON CONFLICT``.
        input_value: The original string, kept for debugging.
        output_value: The transformer's result.
        created_at: Insert time.
    """

    __tablename__ = "transformation"
    __table_args__ = (Index("idx_transformation__input_hash", "input_hash", unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    input_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    input_value: Mapped[str] = mapped_column(Text, nullable=False)
    output_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

`caching_service/db/models/payload.py`:

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import CHAR, DateTime, Index, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from caching_service.db.models.base import Base


class PayloadModel(Base):
    """One generated payload per distinct ``(list_1, list_2)`` input.

    Attributes:
        id: Public identifier returned to clients (uuid4, generated in the app).
        input_hash: ``payload_input_hash(list_1, list_2)``; unique, used for id reuse.
        output: Final interleaved string.
        created_at: Insert time.
    """

    __tablename__ = "payload"
    __table_args__ = (Index("idx_payload__input_hash", "input_hash", unique=True),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    input_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

`caching_service/db/models/__init__.py`:

```python
from caching_service.db.models.base import Base
from caching_service.db.models.payload import PayloadModel
from caching_service.db.models.transformation import TransformationModel

__all__ = ["Base", "PayloadModel", "TransformationModel"]
```

- [ ] **Step 5: Overwrite the Alembic config and env, add the migration**

`alembic.ini` (replace the generated file entirely):

```ini
[alembic]
script_location = %(here)s/migrations
prepend_sys_path = .
path_separator = os
```

`migrations/env.py` (replace the generated file entirely):

```python
import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from caching_service.core.config import get_settings
from caching_service.db.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit migration SQL without connecting to a database."""
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations_on_connection(connection: Connection) -> None:
    """Run migrations on a synchronous connection.

    Args:
        connection: Connection handed in by a caller, or the sync view of our own async connection.
    """
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_with_new_engine() -> None:
    """Run migrations on a fresh engine built from the ``POSTGRES_*`` settings."""
    engine = create_async_engine(get_settings().database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations_on_connection)
    await engine.dispose()


def run_migrations_online() -> None:
    """Migrate on the connection a caller passed in ``config.attributes`` (tests), else on a new engine."""
    connection: Connection | None = config.attributes.get("connection")
    if connection is None:
        asyncio.run(_run_migrations_with_new_engine())
    else:
        _run_migrations_on_connection(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`migrations/versions/0001_create_transformation_and_payload.py`:

```python
"""Create transformation and payload tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create both cache tables and their unique hash indexes."""
    op.create_table(
        "transformation",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("input_hash", sa.CHAR(64), nullable=False),
        sa.Column("input_value", sa.Text(), nullable=False),
        sa.Column("output_value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_transformation__input_hash", "transformation", ["input_hash"], unique=True)

    op.create_table(
        "payload",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("input_hash", sa.CHAR(64), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_payload__input_hash", "payload", ["input_hash"], unique=True)


def downgrade() -> None:
    """Drop both cache tables."""
    op.drop_index("idx_payload__input_hash", table_name="payload")
    op.drop_table("payload")
    op.drop_index("idx_transformation__input_hash", table_name="transformation")
    op.drop_table("transformation")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/integration/db/test_migrations.py tests/units/core -v`
Expected: PASS (2 + 6 tests). The first run pulls `postgres:16-alpine`.

- [ ] **Step 7: Lint and commit (print for the user)**

Run: `uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli migrations/env.py`

```bash
git add alembic.ini migrations caching_service/core caching_service/db tests/integration tests/units/core
git commit -m "feat: add cache tables, ORM models and initial migration"
```

---

### Task 5: Repositories

**Files:**
- Create: `caching_service/db/repositories/__init__.py` (empty), `caching_service/db/repositories/transformation_repository.py`, `caching_service/db/repositories/payload_repository.py`
- Test: `tests/integration/db/test_transformation_repository.py`, `tests/integration/db/test_payload_repository.py`

**Interfaces:**
- Consumes: `TransformationModel`, `PayloadModel` (Task 4); `TransformationRecord` (Task 3); `sha256_hex` (Task 2); fixtures `session`, `session_factory`, `engine`, helper `count_rows` (Task 4).
- Produces:
  - `TransformationRepository(session: AsyncSession)`
    - `async get_outputs_by_hashes(input_hashes: Collection[str]) -> dict[str, str]`
    - `async save_many(records: Sequence[TransformationRecord]) -> None`: one statement, sorted by hash, `ON CONFLICT DO NOTHING`.
  - `PayloadRepository(session: AsyncSession)`
    - `async get_id_by_input_hash(input_hash: str) -> UUID | None`
    - `async get_output_by_id(payload_id: UUID) -> str | None`
    - `async insert_if_absent(payload_id: UUID, input_hash: str, output: str) -> bool` (`True` if inserted)
  - Repositories never commit. The caller owns the transaction.

- [ ] **Step 1: Write the failing tests**

`tests/integration/db/test_transformation_repository.py`:

```python
import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from caching_service.constants import MAX_STRING_LENGTH
from caching_service.db.models import TransformationModel
from caching_service.db.repositories.transformation_repository import TransformationRepository
from caching_service.schemas.transformation import TransformationRecord
from caching_service.utils.hashing import sha256_hex
from tests.integration.database import count_rows


def _record(value: str, output: str | None = None) -> TransformationRecord:
    return TransformationRecord(
        input_hash=sha256_hex(value),
        input_value=value,
        output_value=value.upper() if output is None else output,
    )


async def _save_and_commit(session: AsyncSession, records: list[TransformationRecord]) -> None:
    await TransformationRepository(session).save_many(records)
    await session.commit()


async def test_saved_records_are_returned_by_hash(session: AsyncSession) -> None:
    repository = TransformationRepository(session)
    await repository.save_many([_record("a"), _record("b")])
    await session.commit()

    outputs = await repository.get_outputs_by_hashes([sha256_hex("a"), sha256_hex("b"), sha256_hex("missing")])

    assert outputs == {sha256_hex("a"): "A", sha256_hex("b"): "B"}


async def test_lookup_without_hashes_returns_an_empty_mapping(session: AsyncSession) -> None:
    assert await TransformationRepository(session).get_outputs_by_hashes([]) == {}


async def test_saving_an_existing_hash_keeps_the_original_row(session: AsyncSession) -> None:
    repository = TransformationRepository(session)
    await repository.save_many([_record("a", "first")])
    await session.commit()

    await repository.save_many([_record("a", "second")])
    await session.commit()

    assert await repository.get_outputs_by_hashes([sha256_hex("a")]) == {sha256_hex("a"): "first"}


async def test_values_longer_than_a_btree_entry_round_trip(session: AsyncSession) -> None:
    value = "x" * MAX_STRING_LENGTH
    repository = TransformationRepository(session)
    await repository.save_many([_record(value)])
    await session.commit()

    assert await repository.get_outputs_by_hashes([sha256_hex(value)]) == {sha256_hex(value): value.upper()}


async def test_concurrent_sessions_inserting_the_same_hash_keep_one_row(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as first, session_factory() as second:
        await TransformationRepository(first).save_many([_record("a")])
        second_insert = asyncio.create_task(_save_and_commit(second, [_record("a")]))
        await asyncio.sleep(0.2)  # lets the second insert block on the first session's uncommitted row
        await first.commit()
        await second_insert

    assert await count_rows(engine, TransformationModel) == 1
```

`tests/integration/db/test_payload_repository.py`:

```python
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from caching_service.db.repositories.payload_repository import PayloadRepository

INPUT_HASH = "a" * 64
OTHER_HASH = "b" * 64


async def test_insert_if_absent_inserts_only_the_first_time(session: AsyncSession) -> None:
    repository = PayloadRepository(session)

    first = await repository.insert_if_absent(uuid4(), INPUT_HASH, "OUT")
    second = await repository.insert_if_absent(uuid4(), INPUT_HASH, "OTHER")

    assert first is True
    assert second is False


async def test_lookups_return_stored_values_or_none(session: AsyncSession) -> None:
    repository = PayloadRepository(session)
    payload_id = uuid4()
    await repository.insert_if_absent(payload_id, INPUT_HASH, "OUT")
    await session.commit()

    assert await repository.get_id_by_input_hash(INPUT_HASH) == payload_id
    assert await repository.get_output_by_id(payload_id) == "OUT"
    assert await repository.get_id_by_input_hash(OTHER_HASH) is None
    assert await repository.get_output_by_id(uuid4()) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/db -v`
Expected: the two new files FAIL with `ModuleNotFoundError: No module named 'caching_service.db.repositories'`. The migration tests still PASS.

- [ ] **Step 3: Implement**

`caching_service/db/repositories/transformation_repository.py`:

```python
from collections.abc import Collection, Sequence
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from caching_service.db.models import TransformationModel
from caching_service.schemas.transformation import TransformationRecord


class TransformationRepository:
    """Read and write cached transformer results.

    Args:
        session: Request-scoped session. The caller owns commit and rollback.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_outputs_by_hashes(self, input_hashes: Collection[str]) -> dict[str, str]:
        """Fetch cached outputs for many inputs in one query.

        Args:
            input_hashes: ``sha256_hex`` keys to look up.

        Returns:
            Mapping of input hash to cached output. Hashes with no cached row are absent.
        """
        if not input_hashes:
            return {}
        statement = select(TransformationModel.input_hash, TransformationModel.output_value).where(
            TransformationModel.input_hash.in_(list(input_hashes))
        )
        result = await self._session.execute(statement)
        return {row.input_hash: row.output_value for row in result}

    async def save_many(self, records: Sequence[TransformationRecord]) -> None:
        """Insert transformer results in one statement, skipping inputs that are already cached.

        Rows are inserted in ``input_hash`` order so that concurrent transactions with overlapping inputs
        take row locks in the same order and cannot deadlock each other.

        Args:
            records: Results to cache. Must not contain duplicate hashes.
        """
        if not records:
            return
        rows = [asdict(record) for record in sorted(records, key=lambda record: record.input_hash)]
        statement = (
            insert(TransformationModel)
            .values(rows)
            .on_conflict_do_nothing(index_elements=[TransformationModel.input_hash])
        )
        await self._session.execute(statement)
```

`caching_service/db/repositories/payload_repository.py`:

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from caching_service.db.models import PayloadModel


class PayloadRepository:
    """Read and write generated payloads.

    Args:
        session: Request-scoped session. The caller owns commit and rollback.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_id_by_input_hash(self, input_hash: str) -> UUID | None:
        """Find the payload generated for an input.

        Args:
            input_hash: ``payload_input_hash`` of the request lists.

        Returns:
            The payload id, or ``None`` if this input was never stored.
        """
        result = await self._session.execute(select(PayloadModel.id).where(PayloadModel.input_hash == input_hash))
        return result.scalar_one_or_none()

    async def get_output_by_id(self, payload_id: UUID) -> str | None:
        """Read a payload's output.

        Args:
            payload_id: Public payload identifier.

        Returns:
            The stored output, or ``None`` if no payload has this id.
        """
        result = await self._session.execute(select(PayloadModel.output).where(PayloadModel.id == payload_id))
        return result.scalar_one_or_none()

    async def insert_if_absent(self, payload_id: UUID, input_hash: str, output: str) -> bool:
        """Insert a payload unless one with the same input already exists.

        Args:
            payload_id: Identifier to use if the row is inserted.
            input_hash: ``payload_input_hash`` of the request lists.
            output: Final interleaved string.

        Returns:
            ``True`` if this call inserted the row, ``False`` if a row with ``input_hash`` already existed.
        """
        statement = (
            insert(PayloadModel)
            .values(id=payload_id, input_hash=input_hash, output=output)
            .on_conflict_do_nothing(index_elements=[PayloadModel.input_hash])
            .returning(PayloadModel.id)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none() is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/db -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Lint and commit (print for the user)**

Run: `uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli migrations/env.py`

```bash
git add caching_service/db/repositories tests/integration/db
git commit -m "feat: add transformation and payload repositories with conflict-safe inserts"
```

---

### Task 6: Transformer client and TransformationService

**Files:**
- Create: `caching_service/clients/__init__.py` (empty), `caching_service/clients/transformer_client.py`
- Create: `caching_service/services/__init__.py` (empty), `caching_service/services/transformation_service.py`
- Create: `tests/fakes.py`
- Test: `tests/units/clients/test_transformer_client.py`, `tests/units/services/test_transformation_service.py`

**Interfaces:**
- Consumes: `TransformationRepository` (Task 5), `TransformationRecord` (Task 3), `sha256_hex` (Task 2).
- Produces:
  - `TransformerClient` protocol with `async transform(value: str) -> str`, and `UppercaseTransformerClient`.
  - `TransformationService(repository: TransformationRepository, transformer: TransformerClient)` with `async transform_all(values: Iterable[str]) -> dict[str, str]` (distinct input → output).
  - `tests/fakes.py`: `CountingTransformerClient` (`.calls: list[str]`) and `InMemoryTransformationRepository(outputs_by_hash: dict[str, str] | None = None)` (`.saved: list[TransformationRecord]`).

- [ ] **Step 1: Write the fakes and the failing tests**

`tests/fakes.py`:

```python
from collections.abc import Collection, Sequence

from caching_service.schemas.transformation import TransformationRecord


class CountingTransformerClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def transform(self, value: str) -> str:
        self.calls.append(value)
        return value.upper()


class InMemoryTransformationRepository:
    def __init__(self, outputs_by_hash: dict[str, str] | None = None) -> None:
        self.outputs_by_hash = dict(outputs_by_hash or {})
        self.saved: list[TransformationRecord] = []

    async def get_outputs_by_hashes(self, input_hashes: Collection[str]) -> dict[str, str]:
        return {key: self.outputs_by_hash[key] for key in input_hashes if key in self.outputs_by_hash}

    async def save_many(self, records: Sequence[TransformationRecord]) -> None:
        self.saved.extend(records)
        for record in records:
            self.outputs_by_hash.setdefault(record.input_hash, record.output_value)
```

`tests/units/clients/test_transformer_client.py`:

```python
import pytest

from caching_service.clients.transformer_client import UppercaseTransformerClient


@pytest.mark.parametrize(
    ("value", "expected"),
    [("first string", "FIRST STRING"), ("straße", "STRASSE"), ("héllo 👋", "HÉLLO 👋"), ("", "")],
)
async def test_uppercase_transformer(value: str, expected: str) -> None:
    assert await UppercaseTransformerClient().transform(value) == expected
```

`tests/units/services/test_transformation_service.py`:

```python
from caching_service.schemas.transformation import TransformationRecord
from caching_service.services.transformation_service import TransformationService
from caching_service.utils.hashing import sha256_hex
from tests.fakes import CountingTransformerClient, InMemoryTransformationRepository


async def test_cold_cache_calls_the_transformer_once_per_value() -> None:
    transformer = CountingTransformerClient()
    service = TransformationService(InMemoryTransformationRepository(), transformer)

    outputs = await service.transform_all(["a", "b"])

    assert outputs == {"a": "A", "b": "B"}
    assert transformer.calls == ["a", "b"]


async def test_duplicates_within_one_call_are_transformed_once() -> None:
    transformer = CountingTransformerClient()
    service = TransformationService(InMemoryTransformationRepository(), transformer)

    outputs = await service.transform_all(["a", "a", "a", "b"])

    assert outputs == {"a": "A", "b": "B"}
    assert transformer.calls == ["a", "b"]


async def test_cached_values_are_not_sent_to_the_transformer() -> None:
    transformer = CountingTransformerClient()
    repository = InMemoryTransformationRepository({sha256_hex("a"): "A"})
    service = TransformationService(repository, transformer)

    outputs = await service.transform_all(["a", "x"])

    assert outputs == {"a": "A", "x": "X"}
    assert transformer.calls == ["x"]


async def test_cached_empty_string_counts_as_a_hit() -> None:
    transformer = CountingTransformerClient()
    repository = InMemoryTransformationRepository({sha256_hex(""): ""})
    service = TransformationService(repository, transformer)

    outputs = await service.transform_all([""])

    assert outputs == {"": ""}
    assert transformer.calls == []


async def test_only_misses_are_saved_with_their_hashes() -> None:
    repository = InMemoryTransformationRepository({sha256_hex("a"): "A"})
    service = TransformationService(repository, CountingTransformerClient())

    await service.transform_all(["a", "x"])

    assert repository.saved == [TransformationRecord(input_hash=sha256_hex("x"), input_value="x", output_value="X")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/units/clients tests/units/services -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'caching_service.clients'`

- [ ] **Step 3: Implement**

`caching_service/clients/transformer_client.py`:

```python
from typing import Protocol


class TransformerClient(Protocol):
    """Transforms one string. Stands in for a paid external service, so callers minimise calls."""

    async def transform(self, value: str) -> str:
        """Transform a single string.

        Args:
            value: Input string.

        Returns:
            The transformed string.
        """
        ...


class UppercaseTransformerClient:
    """The service's transformer: Unicode-aware ``str.upper``.

    It is async so that a real HTTP-backed client can replace it without touching any caller.
    """

    async def transform(self, value: str) -> str:
        """Uppercase a single string.

        Args:
            value: Input string.

        Returns:
            ``value.upper()``.
        """
        return value.upper()
```

`caching_service/services/transformation_service.py`:

```python
from collections.abc import Iterable

from caching_service.clients.transformer_client import TransformerClient
from caching_service.db.repositories.transformation_repository import TransformationRepository
from caching_service.schemas.transformation import TransformationRecord
from caching_service.utils.hashing import sha256_hex


class TransformationService:
    """Transform strings through the Postgres cache, calling the transformer only on misses.

    Args:
        repository: Cache storage.
        transformer: The (expensive) transformer.
    """

    def __init__(self, repository: TransformationRepository, transformer: TransformerClient) -> None:
        self._repository = repository
        self._transformer = transformer

    async def transform_all(self, values: Iterable[str]) -> dict[str, str]:
        """Transform strings, calling the transformer only for strings never seen before.

        Duplicates are collapsed before the cache lookup. The lookup happens once per request, so without
        this a string repeated in one cold request would be sent to the transformer once per occurrence.

        Args:
            values: Strings to transform, in any order, duplicates allowed.

        Returns:
            Mapping from each distinct input string to its transformed output.
        """
        unique_values = list(dict.fromkeys(values))
        hash_by_value = {value: sha256_hex(value) for value in unique_values}
        cached_outputs = await self._repository.get_outputs_by_hashes(list(hash_by_value.values()))

        outputs: dict[str, str] = {}
        new_records: list[TransformationRecord] = []
        for value in unique_values:
            input_hash = hash_by_value[value]
            # `is None`, not falsiness: a cached empty string is a hit.
            output = cached_outputs.get(input_hash)
            if output is None:
                output = await self._transformer.transform(value)
                new_records.append(
                    TransformationRecord(input_hash=input_hash, input_value=value, output_value=output)
                )
            outputs[value] = output

        await self._repository.save_many(new_records)
        return outputs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/units/clients tests/units/services -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Lint and commit (print for the user)**

Run: `uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli migrations/env.py`

```bash
git add caching_service/clients caching_service/services tests/fakes.py tests/units/clients tests/units/services
git commit -m "feat: add uppercase transformer client and cache-first transformation service"
```

---

### Task 7: PayloadService, use cases and logging

**Files:**
- Create: `caching_service/core/logging.py`, `caching_service/services/payload_service.py`
- Create: `caching_service/use_cases/__init__.py` (empty), `caching_service/use_cases/create_payload.py`, `caching_service/use_cases/get_payload.py`
- Create: `tests/samples.py`
- Modify: `tests/fakes.py` (append `InMemoryPayloadRepository`)
- Test: `tests/units/services/test_payload_service.py`, `tests/units/use_cases/test_create_payload.py`

**Interfaces:**
- Consumes: `PayloadRepository` (Task 5), `TransformationService` (Task 6), `PayloadCreationResult` (Task 3), `payload_input_hash`, `interleave` (Task 2), `OUTPUT_SEPARATOR` (Task 1).
- Produces:
  - `caching_service.core.logging`: `logger: logging.Logger` (name `caching_service`) and `configure_logging(level: str) -> None` (called by `lifespan` in Task 8).
  - `PayloadService(repository: PayloadRepository)`: `async find_id(input_hash: str) -> UUID | None`, `async get_output(payload_id: UUID) -> str | None`, `async create(input_hash: str, output: str) -> PayloadCreationResult` (raises `RuntimeError` if the insert conflicted but no row is visible).
  - `CreatePayloadUseCase(payload_service: PayloadService, transformation_service: TransformationService)`: `async execute(list_1: Sequence[str], list_2: Sequence[str]) -> PayloadCreationResult`.
  - `GetPayloadUseCase(payload_service: PayloadService)`: `async execute(payload_id: UUID) -> str | None`.
  - `tests/samples.py`: `SAMPLE_REQUEST: dict[str, list[str]]`, `SAMPLE_OUTPUT: str`.
  - `tests/fakes.py`: `InMemoryPayloadRepository` (`.ids_by_hash`, `.outputs_by_id`).

- [ ] **Step 1: Add the sample, the fake, and the failing tests**

`tests/samples.py`:

```python
SAMPLE_REQUEST = {
    "list_1": ["first string", "second string", "third string"],
    "list_2": ["other string", "another string", "last string"],
}
SAMPLE_OUTPUT = "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"
```

Append to `tests/fakes.py`, and add `from uuid import UUID` to its imports:

```python
class InMemoryPayloadRepository:
    def __init__(self) -> None:
        self.ids_by_hash: dict[str, UUID] = {}
        self.outputs_by_id: dict[UUID, str] = {}

    async def get_id_by_input_hash(self, input_hash: str) -> UUID | None:
        return self.ids_by_hash.get(input_hash)

    async def get_output_by_id(self, payload_id: UUID) -> str | None:
        return self.outputs_by_id.get(payload_id)

    async def insert_if_absent(self, payload_id: UUID, input_hash: str, output: str) -> bool:
        if input_hash in self.ids_by_hash:
            return False
        self.ids_by_hash[input_hash] = payload_id
        self.outputs_by_id[payload_id] = output
        return True
```

`tests/units/services/test_payload_service.py`:

```python
from uuid import UUID, uuid4

import pytest

from caching_service.services.payload_service import PayloadService
from tests.fakes import InMemoryPayloadRepository

INPUT_HASH = "a" * 64


class _ConflictWithoutVisibleRow(InMemoryPayloadRepository):
    async def insert_if_absent(self, payload_id: UUID, input_hash: str, output: str) -> bool:
        return False


async def test_create_returns_a_new_id_when_the_insert_wins() -> None:
    repository = InMemoryPayloadRepository()

    result = await PayloadService(repository).create(INPUT_HASH, "OUT")

    assert result.created is True
    assert repository.ids_by_hash[INPUT_HASH] == result.payload_id


async def test_create_returns_the_existing_id_when_the_insert_loses() -> None:
    repository = InMemoryPayloadRepository()
    existing_id = uuid4()
    repository.ids_by_hash[INPUT_HASH] = existing_id

    result = await PayloadService(repository).create(INPUT_HASH, "OUT")

    assert result.created is False
    assert result.payload_id == existing_id


async def test_create_raises_when_the_conflicting_row_is_not_visible() -> None:
    service = PayloadService(_ConflictWithoutVisibleRow())

    with pytest.raises(RuntimeError):
        await service.create(INPUT_HASH, "OUT")
```

`tests/units/use_cases/test_create_payload.py`:

```python
import logging

import pytest

from caching_service.services.payload_service import PayloadService
from caching_service.services.transformation_service import TransformationService
from caching_service.use_cases.create_payload import CreatePayloadUseCase
from caching_service.utils.hashing import payload_input_hash
from tests.fakes import CountingTransformerClient, InMemoryPayloadRepository, InMemoryTransformationRepository
from tests.samples import SAMPLE_OUTPUT, SAMPLE_REQUEST


def _use_case(
    payload_repository: InMemoryPayloadRepository, transformer: CountingTransformerClient
) -> CreatePayloadUseCase:
    return CreatePayloadUseCase(
        payload_service=PayloadService(payload_repository),
        transformation_service=TransformationService(InMemoryTransformationRepository(), transformer),
    )


async def test_new_input_produces_the_sample_output() -> None:
    payload_repository = InMemoryPayloadRepository()
    transformer = CountingTransformerClient()

    result = await _use_case(payload_repository, transformer).execute(
        SAMPLE_REQUEST["list_1"], SAMPLE_REQUEST["list_2"]
    )

    assert result.created is True
    assert payload_repository.outputs_by_id[result.payload_id] == SAMPLE_OUTPUT
    assert len(transformer.calls) == 6


async def test_known_input_takes_the_fast_path_without_transforming() -> None:
    payload_repository = InMemoryPayloadRepository()
    first = await _use_case(payload_repository, CountingTransformerClient()).execute(
        SAMPLE_REQUEST["list_1"], SAMPLE_REQUEST["list_2"]
    )
    # Fresh transformation cache: only the payload fast path can avoid calling the transformer now.
    transformer = CountingTransformerClient()

    second = await _use_case(payload_repository, transformer).execute(
        SAMPLE_REQUEST["list_1"], SAMPLE_REQUEST["list_2"]
    )

    assert second.created is False
    assert second.payload_id == first.payload_id
    assert transformer.calls == []
    assert set(payload_repository.ids_by_hash) == {
        payload_input_hash(SAMPLE_REQUEST["list_1"], SAMPLE_REQUEST["list_2"])
    }


async def test_storing_a_payload_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="caching_service")

    result = await _use_case(InMemoryPayloadRepository(), CountingTransformerClient()).execute(["a"], ["b"])

    assert f"payload_id={result.payload_id} created=True" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/units/services/test_payload_service.py tests/units/use_cases -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'caching_service.services.payload_service'`

- [ ] **Step 3: Implement**

`caching_service/core/logging.py`:

```python
# ruff: noqa: A005
import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

logger = logging.getLogger("caching_service")


def configure_logging(level: str) -> None:
    """Send log records to stderr in one plain-text format.

    Called once from ``lifespan``, never at import time. Importing the package (tests, the CLI, Alembic)
    therefore never reconfigures the host process's logging.

    Args:
        level: Standard level name, such as ``"INFO"`` or ``"DEBUG"``.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
```

`caching_service/services/payload_service.py`:

```python
from uuid import UUID, uuid4

from caching_service.db.repositories.payload_repository import PayloadRepository
from caching_service.schemas.payload import PayloadCreationResult


class PayloadService:
    """Look up and store generated payloads.

    Args:
        repository: Payload storage.
    """

    def __init__(self, repository: PayloadRepository) -> None:
        self._repository = repository

    async def find_id(self, input_hash: str) -> UUID | None:
        """Find the payload already generated for an input.

        Args:
            input_hash: ``payload_input_hash`` of the request lists.

        Returns:
            The existing payload id, or ``None``.
        """
        return await self._repository.get_id_by_input_hash(input_hash)

    async def get_output(self, payload_id: UUID) -> str | None:
        """Read a payload's output.

        Args:
            payload_id: Public payload identifier.

        Returns:
            The output, or ``None`` if the id is unknown.
        """
        return await self._repository.get_output_by_id(payload_id)

    async def create(self, input_hash: str, output: str) -> PayloadCreationResult:
        """Store a payload, or return the one a concurrent request stored first.

        Args:
            input_hash: ``payload_input_hash`` of the request lists.
            output: Final interleaved string.

        Returns:
            The new id with ``created=True``, or the concurrent winner's id with ``created=False``.

        Raises:
            RuntimeError: If the insert conflicted but no row with that hash is visible. That would mean
                payload rows are being deleted, which this service never does.
        """
        payload_id = uuid4()
        if await self._repository.insert_if_absent(payload_id, input_hash, output):
            return PayloadCreationResult(payload_id=payload_id, created=True)

        existing_id = await self._repository.get_id_by_input_hash(input_hash)
        if existing_id is None:
            raise RuntimeError(f"Payload insert conflicted on {input_hash} but no row is visible")
        return PayloadCreationResult(payload_id=existing_id, created=False)
```

`caching_service/use_cases/create_payload.py`:

```python
from collections.abc import Sequence

from caching_service.constants import OUTPUT_SEPARATOR
from caching_service.core.logging import logger
from caching_service.schemas.payload import PayloadCreationResult
from caching_service.services.payload_service import PayloadService
from caching_service.services.transformation_service import TransformationService
from caching_service.utils.hashing import payload_input_hash
from caching_service.utils.interleave import interleave


class CreatePayloadUseCase:
    """Create a payload from two lists, or return the id of the identical payload created before.

    Args:
        payload_service: Payload lookup and storage.
        transformation_service: Cache-first transformer access.
    """

    def __init__(self, payload_service: PayloadService, transformation_service: TransformationService) -> None:
        self._payload_service = payload_service
        self._transformation_service = transformation_service

    async def execute(self, list_1: Sequence[str], list_2: Sequence[str]) -> PayloadCreationResult:
        """Create or reuse the payload for ``(list_1, list_2)``.

        A known input returns before any transformation lookup, so a repeated payload costs one query and
        zero transformer calls.

        Args:
            list_1: Strings for even output positions.
            list_2: Strings for odd output positions; same length as ``list_1``.

        Returns:
            The payload id and whether this call created it.
        """
        input_hash = payload_input_hash(list_1, list_2)
        existing_id = await self._payload_service.find_id(input_hash)
        if existing_id is not None:
            return PayloadCreationResult(payload_id=existing_id, created=False)

        outputs = await self._transformation_service.transform_all([*list_1, *list_2])
        ordered_outputs = interleave([outputs[value] for value in list_1], [outputs[value] for value in list_2])
        result = await self._payload_service.create(input_hash, OUTPUT_SEPARATOR.join(ordered_outputs))
        logger.info("Payload stored: payload_id=%s created=%s", result.payload_id, result.created)
        return result
```

`caching_service/use_cases/get_payload.py`:

```python
from uuid import UUID

from caching_service.services.payload_service import PayloadService


class GetPayloadUseCase:
    """Read a generated payload by id.

    Args:
        payload_service: Payload lookup.
    """

    def __init__(self, payload_service: PayloadService) -> None:
        self._payload_service = payload_service

    async def execute(self, payload_id: UUID) -> str | None:
        """Fetch a payload's output.

        Args:
            payload_id: Public payload identifier.

        Returns:
            The output, or ``None`` if the id is unknown.
        """
        return await self._payload_service.get_output(payload_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/units -v`
Expected: PASS (all unit tests so far)

- [ ] **Step 5: Lint and commit (print for the user)**

Run: `uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli migrations/env.py`

```bash
git add caching_service/core/logging.py caching_service/services/payload_service.py caching_service/use_cases tests/samples.py tests/fakes.py tests/units/services tests/units/use_cases
git commit -m "feat: add payload service and create/get use cases"
```

---

### Task 8: HTTP API: lifespan, dependencies, routes, validation errors

**Files:**
- Create: `caching_service/core/db.py`
- Create: `caching_service/api/__init__.py` (empty), `caching_service/api/app.py`, `caching_service/api/lifespan.py`, `caching_service/api/dependencies.py`, `caching_service/api/responses.py`, `caching_service/api/errors.py`
- Create: `caching_service/api/routes/__init__.py` (empty), `caching_service/api/routes/payload.py`, `caching_service/api/routes/health.py`
- Test: `tests/integration/api/conftest.py`, `tests/integration/api/test_create_and_read_payload.py`, `tests/integration/api/test_validation.py`, `tests/integration/api/test_statement_budget.py`, `tests/integration/api/test_concurrency.py`, `tests/integration/api/test_commit_timing.py`, `tests/integration/api/test_lifespan.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7. Fixtures `postgres_url`, `engine`, `session_factory`; helpers `count_rows`; `CountingTransformerClient`; `SAMPLE_REQUEST`/`SAMPLE_OUTPUT`.
- Produces:
  - `create_app() -> FastAPI` in `caching_service.api.app`. This is the uvicorn factory: `caching_service.api.app:create_app --factory`.
  - Dependency override points: `get_session_factory(request) -> async_sessionmaker[AsyncSession]` and `get_transformer(request) -> TransformerClient` in `caching_service.api.dependencies`.
  - Routes: `POST /payload`, `GET /payload/{payload_id}`, `GET /health`, with bodies exactly as in spec `api_contracts`.

- [ ] **Step 1: Write the API fixtures and failing tests**

`tests/integration/api/conftest.py`:

```python
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from caching_service.api.app import create_app
from caching_service.api.dependencies import get_session_factory, get_transformer
from tests.fakes import CountingTransformerClient


@pytest.fixture
def transformer() -> CountingTransformerClient:
    return CountingTransformerClient()


@pytest.fixture
def app(session_factory: async_sessionmaker[AsyncSession], transformer: CountingTransformerClient) -> FastAPI:
    # ASGITransport does not run the lifespan, so both lifespan-provided dependencies are overridden.
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_transformer] = lambda: transformer
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
```

`tests/integration/api/test_create_and_read_payload.py`:

```python
from http import HTTPStatus
from uuid import UUID, uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from caching_service.constants import MAX_STRING_LENGTH, PAYLOAD_CREATED_MESSAGE, PAYLOAD_EXISTS_MESSAGE
from caching_service.db.models import PayloadModel, TransformationModel
from tests.fakes import CountingTransformerClient
from tests.integration.database import count_rows
from tests.samples import SAMPLE_OUTPUT, SAMPLE_REQUEST


async def _create_and_read(client: httpx.AsyncClient, body: dict[str, list[str]]) -> str:
    created = await client.post("/payload", json=body)
    assert created.status_code == HTTPStatus.CREATED, created.text
    fetched = await client.get(f"/payload/{created.json()['id']}")
    assert fetched.status_code == HTTPStatus.OK
    return str(fetched.json()["output"])


async def test_sample_input_is_created_and_read_back(
    client: httpx.AsyncClient, transformer: CountingTransformerClient
) -> None:
    created = await client.post("/payload", json=SAMPLE_REQUEST)

    assert created.status_code == HTTPStatus.CREATED
    assert created.json()["message"] == PAYLOAD_CREATED_MESSAGE
    payload_id = UUID(created.json()["id"])
    fetched = await client.get(f"/payload/{payload_id}")
    assert fetched.status_code == HTTPStatus.OK
    assert fetched.json() == {"output": SAMPLE_OUTPUT}
    assert len(transformer.calls) == 6


async def test_repeated_input_returns_the_same_id_without_new_work(
    client: httpx.AsyncClient, transformer: CountingTransformerClient, engine: AsyncEngine
) -> None:
    first = await client.post("/payload", json=SAMPLE_REQUEST)
    calls_after_first = len(transformer.calls)

    second = await client.post("/payload", json=SAMPLE_REQUEST)

    assert second.status_code == HTTPStatus.OK
    assert second.json() == {"id": first.json()["id"], "message": PAYLOAD_EXISTS_MESSAGE}
    assert len(transformer.calls) == calls_after_first
    assert await count_rows(engine, PayloadModel) == 1
    assert await count_rows(engine, TransformationModel) == 6


async def test_strings_cached_by_an_earlier_request_are_not_transformed_again(
    client: httpx.AsyncClient, transformer: CountingTransformerClient
) -> None:
    await client.post("/payload", json={"list_1": ["a", "b"], "list_2": ["c", "d"]})
    transformer.calls.clear()

    output = await _create_and_read(client, {"list_1": ["a", "x"], "list_2": ["c", "y"]})

    assert sorted(transformer.calls) == ["x", "y"]
    assert output == "A, C, X, Y"


async def test_cached_empty_string_is_not_transformed_again(
    client: httpx.AsyncClient, transformer: CountingTransformerClient
) -> None:
    await client.post("/payload", json={"list_1": [""], "list_2": ["a"]})
    transformer.calls.clear()

    await client.post("/payload", json={"list_1": [""], "list_2": ["b"]})

    assert transformer.calls == ["b"]


async def test_duplicates_in_one_cold_request_are_transformed_once(
    client: httpx.AsyncClient, transformer: CountingTransformerClient
) -> None:
    output = await _create_and_read(client, {"list_1": ["a", "a"], "list_2": ["a", "b"]})

    assert transformer.calls == ["a", "b"]
    assert output == "A, A, A, B"


async def test_swapped_lists_are_a_different_payload(client: httpx.AsyncClient) -> None:
    first = await client.post("/payload", json={"list_1": ["a"], "list_2": ["b"]})
    second = await client.post("/payload", json={"list_1": ["b"], "list_2": ["a"]})

    assert second.status_code == HTTPStatus.CREATED
    assert second.json()["id"] != first.json()["id"]


async def test_empty_string_item_produces_a_leading_separator(client: httpx.AsyncClient) -> None:
    assert await _create_and_read(client, {"list_1": [""], "list_2": ["a"]}) == ", A"


async def test_unicode_long_and_separator_strings_round_trip(client: httpx.AsyncClient) -> None:
    long_value = "x" * MAX_STRING_LENGTH
    body = {"list_1": ["straße", long_value], "list_2": ["héllo 👋", "a, b"]}

    output = await _create_and_read(client, body)

    assert output == f"STRASSE, HÉLLO 👋, {long_value.upper()}, A, B"


async def test_unknown_id_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/payload/{uuid4()}")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"detail": "Payload not found"}


async def test_malformed_id_returns_422(client: httpx.AsyncClient) -> None:
    response = await client.get("/payload/not-a-uuid")

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}
```

`tests/integration/api/test_validation.py`:

```python
import json
from http import HTTPStatus

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from caching_service.constants import MAX_LIST_LENGTH
from caching_service.db.models import PayloadModel, TransformationModel
from tests.fakes import CountingTransformerClient
from tests.integration.database import count_rows

INVALID_BODIES = {
    "unequal_lengths": json.dumps({"list_1": ["a", "b"], "list_2": ["c"]}),
    "empty_lists": json.dumps({"list_1": [], "list_2": []}),
    "integer_item": json.dumps({"list_1": [123], "list_2": ["a"]}),
    "extra_key": json.dumps({"list_1": ["a"], "list_2": ["b"], "list_3": ["c"]}),
    "missing_key": json.dumps({"list_1": ["a"]}),
    "array_body": json.dumps([["a"], ["b"]]),
    "nul_character": json.dumps({"list_1": ["a\x00b"], "list_2": ["c"]}),
    "lone_surrogate": '{"list_1": ["\\ud800"], "list_2": ["c"]}',
    "too_many_items": json.dumps(
        {"list_1": ["a"] * (MAX_LIST_LENGTH + 1), "list_2": ["b"] * (MAX_LIST_LENGTH + 1)}
    ),
}


@pytest.mark.parametrize("raw_body", list(INVALID_BODIES.values()), ids=list(INVALID_BODIES))
async def test_invalid_bodies_are_rejected_without_side_effects(
    client: httpx.AsyncClient, transformer: CountingTransformerClient, engine: AsyncEngine, raw_body: str
) -> None:
    response = await client.post(
        "/payload", content=raw_body.encode("utf-8"), headers={"content-type": "application/json"}
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    assert transformer.calls == []
    assert await count_rows(engine, PayloadModel) == 0
    assert await count_rows(engine, TransformationModel) == 0


async def test_unequal_lengths_error_names_the_rule(client: httpx.AsyncClient) -> None:
    response = await client.post("/payload", json={"list_1": ["a", "b"], "list_2": ["c"]})

    assert "list_1 and list_2 must have the same length" in response.text
```

`tests/integration/api/test_statement_budget.py`:

```python
from collections.abc import Iterator
from http import HTTPStatus
from typing import Any

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from caching_service.constants import MAX_LIST_LENGTH
from tests.samples import SAMPLE_REQUEST

APPLICATION_TABLES = ("payload", "transformation")


@pytest.fixture
def executed_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(*args: Any) -> None:
        statement = args[2]
        # Counts only statements on our tables, so driver/dialect bookkeeping queries cannot skew the budget.
        if any(table in statement for table in APPLICATION_TABLES):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    yield statements
    event.remove(engine.sync_engine, "before_cursor_execute", _record)


async def test_new_payload_at_the_size_limit_uses_at_most_five_statements(
    client: httpx.AsyncClient, executed_statements: list[str]
) -> None:
    body = {
        "list_1": [f"a{index}" for index in range(MAX_LIST_LENGTH)],
        "list_2": [f"b{index}" for index in range(MAX_LIST_LENGTH)],
    }

    response = await client.post("/payload", json=body)

    assert response.status_code == HTTPStatus.CREATED
    assert len(executed_statements) <= 5, executed_statements


async def test_repeated_payload_uses_exactly_one_statement(
    client: httpx.AsyncClient, executed_statements: list[str]
) -> None:
    await client.post("/payload", json=SAMPLE_REQUEST)
    executed_statements.clear()

    response = await client.post("/payload", json=SAMPLE_REQUEST)

    assert response.status_code == HTTPStatus.OK
    assert len(executed_statements) == 1, executed_statements
```

`tests/integration/api/test_concurrency.py`:

```python
import asyncio
from http import HTTPStatus

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from caching_service.db.models import PayloadModel
from tests.integration.database import count_rows
from tests.samples import SAMPLE_REQUEST


async def test_concurrent_identical_posts_converge_on_one_payload(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    responses = await asyncio.gather(*(client.post("/payload", json=SAMPLE_REQUEST) for _ in range(5)))

    assert {response.status_code for response in responses} <= {HTTPStatus.CREATED, HTTPStatus.OK}
    assert len({response.json()["id"] for response in responses}) == 1
    assert await count_rows(engine, PayloadModel) == 1


async def test_overlapping_requests_in_opposite_order_do_not_deadlock(client: httpx.AsyncClient) -> None:
    for round_number in range(10):
        values = [f"r{round_number}-v{index}" for index in range(100)]
        reversed_values = values[::-1]
        forward = {"list_1": values[:50], "list_2": values[50:]}
        backward = {"list_1": reversed_values[:50], "list_2": reversed_values[50:]}

        responses = await asyncio.gather(
            client.post("/payload", json=forward), client.post("/payload", json=backward)
        )

        assert [response.status_code for response in responses] == [HTTPStatus.CREATED, HTTPStatus.CREATED]
```

`tests/integration/api/test_commit_timing.py`:

```python
from http import HTTPStatus

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from caching_service.api.dependencies import get_session_factory
from tests.samples import SAMPLE_REQUEST


class _FailingCommitSession(AsyncSession):
    async def commit(self) -> None:
        raise RuntimeError("simulated commit failure")


async def test_commit_failure_reaches_the_client(app: FastAPI, engine: AsyncEngine) -> None:
    failing_factory = async_sessionmaker(engine, class_=_FailingCommitSession, expire_on_commit=False)
    app.dependency_overrides[get_session_factory] = lambda: failing_factory
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/payload", json=SAMPLE_REQUEST)

    # With FastAPI's default yield-dependency scope the client would already hold a 201 here.
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
```

`tests/integration/api/test_lifespan.py` (synchronous: `TestClient` runs the app on its own loop):

```python
from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from caching_service.api.app import create_app
from caching_service.core.config import get_settings
from tests.integration.database import set_postgres_env


def test_real_lifespan_serves_health_create_and_read(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    set_postgres_env(monkeypatch, postgres_url)
    get_settings.cache_clear()
    unique_value = f"lifespan-{uuid4()}"
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health").json() == {"status": "ok"}
            created = client.post("/payload", json={"list_1": [unique_value], "list_2": ["b"]})
            assert created.status_code == HTTPStatus.CREATED
            fetched = client.get(f"/payload/{created.json()['id']}")
            assert fetched.json() == {"output": f"{unique_value.upper()}, B"}
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/api -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'caching_service.api'`

- [ ] **Step 3: Implement**

`caching_service/core/db.py`:

```python
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine(database_url: URL) -> AsyncEngine:
    """Create the application's async engine.

    Args:
        database_url: ``postgresql+asyncpg`` URL built by ``Settings.database_url``.

    Returns:
        An engine with pre-ping enabled, so connections dropped by a Postgres restart are replaced
        instead of failing a request.
    """
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the per-request session factory.

    Args:
        engine: Engine created at startup.

    Returns:
        A sessionmaker with ``expire_on_commit=False``, so loaded values stay readable after commit.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
```

`caching_service/api/lifespan.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from caching_service.clients.transformer_client import UppercaseTransformerClient
from caching_service.core.config import get_settings
from caching_service.core.db import create_engine, create_session_factory
from caching_service.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    """Configure logging, create runtime dependencies once per process, and release them on shutdown.

    Args:
        app: The application being started.

    Yields:
        Lifespan state, exposed to dependencies as ``request.state``.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    try:
        yield {"session_factory": create_session_factory(engine), "transformer": UppercaseTransformerClient()}
    finally:
        await engine.dispose()
```

`caching_service/api/dependencies.py`:

```python
from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from caching_service.clients.transformer_client import TransformerClient
from caching_service.db.repositories.payload_repository import PayloadRepository
from caching_service.db.repositories.transformation_repository import TransformationRepository
from caching_service.services.payload_service import PayloadService
from caching_service.services.transformation_service import TransformationService
from caching_service.use_cases.create_payload import CreatePayloadUseCase
from caching_service.use_cases.get_payload import GetPayloadUseCase


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """Return the session factory created in ``lifespan``.

    Args:
        request: Current request.

    Returns:
        The process-wide session factory.
    """
    return cast(async_sessionmaker[AsyncSession], request.state.session_factory)


def get_transformer(request: Request) -> TransformerClient:
    """Return the transformer created in ``lifespan``.

    Args:
        request: Current request.

    Returns:
        The process-wide transformer client.
    """
    return cast(TransformerClient, request.state.transformer)


async def get_session(
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    """Open one session per request, commit on success, roll back on any error.

    Args:
        session_factory: Factory from ``lifespan``.

    Yields:
        The request's session.
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# scope="function" runs the commit above before the response is sent. With FastAPI's default
# ("request"), the client would already hold its 201 when the commit runs: commit failures would be
# invisible, and a quick GET could miss the row it was just told exists.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
TransformerDep = Annotated[TransformerClient, Depends(get_transformer)]


def get_create_payload_use_case(session: SessionDep, transformer: TransformerDep) -> CreatePayloadUseCase:
    """Assemble the create-payload use case for one request.

    Args:
        session: The request's session.
        transformer: The process-wide transformer.

    Returns:
        A use case bound to this request's session.
    """
    return CreatePayloadUseCase(
        payload_service=PayloadService(PayloadRepository(session)),
        transformation_service=TransformationService(TransformationRepository(session), transformer),
    )


def get_get_payload_use_case(session: SessionDep) -> GetPayloadUseCase:
    """Assemble the get-payload use case for one request.

    Args:
        session: The request's session.

    Returns:
        A use case bound to this request's session.
    """
    return GetPayloadUseCase(payload_service=PayloadService(PayloadRepository(session)))
```

`caching_service/api/responses.py`:

```python
import json
from typing import Any

from fastapi.responses import JSONResponse


class AsciiJSONResponse(JSONResponse):
    """JSON response that escapes every non-ASCII character.

    Used for validation errors. FastAPI echoes the offending input back, and a lone surrogate in that
    input cannot be encoded as UTF-8, so the default renderer would turn a 422 into a 500.
    """

    def render(self, content: Any) -> bytes:
        """Serialize content as ASCII-only JSON.

        Args:
            content: JSON-compatible content.

        Returns:
            The encoded body.
        """
        return json.dumps(content, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
```

`caching_service/api/errors.py`:

```python
from http import HTTPStatus

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError

from caching_service.api.responses import AsciiJSONResponse


async def validation_error_handler(request: Request, error: RequestValidationError) -> AsciiJSONResponse:
    """Render request validation errors like FastAPI does, but safe for any input.

    Args:
        request: The rejected request.
        error: The validation error.

    Returns:
        A 422 response with FastAPI's usual ``{"detail": [...]}`` body, ASCII-escaped.
    """
    return AsciiJSONResponse(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY, content={"detail": jsonable_encoder(error.errors())}
    )
```

`caching_service/api/routes/payload.py`:

```python
from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from caching_service.api.dependencies import get_create_payload_use_case, get_get_payload_use_case
from caching_service.constants import PAYLOAD_CREATED_MESSAGE, PAYLOAD_EXISTS_MESSAGE, PAYLOAD_NOT_FOUND_DETAIL
from caching_service.schemas.payload import PayloadCreateRequest, PayloadCreateResponse, PayloadReadResponse
from caching_service.use_cases.create_payload import CreatePayloadUseCase
from caching_service.use_cases.get_payload import GetPayloadUseCase

router = APIRouter(prefix="/payload", tags=["payload"])


@router.post(
    "",
    status_code=HTTPStatus.CREATED,
    responses={HTTPStatus.OK: {"model": PayloadCreateResponse, "description": "Payload already exists"}},
)
async def create_payload(
    body: PayloadCreateRequest,
    response: Response,
    use_case: Annotated[CreatePayloadUseCase, Depends(get_create_payload_use_case)],
) -> PayloadCreateResponse:
    """Create a payload, or return the id of the identical payload created earlier.

    Args:
        body: The two input lists.
        response: Used to downgrade the status to 200 when the payload already existed.
        use_case: Create-payload use case.

    Returns:
        The payload id and a created/exists message.
    """
    result = await use_case.execute(body.list_1, body.list_2)
    if not result.created:
        response.status_code = HTTPStatus.OK
        return PayloadCreateResponse(id=result.payload_id, message=PAYLOAD_EXISTS_MESSAGE)
    return PayloadCreateResponse(id=result.payload_id, message=PAYLOAD_CREATED_MESSAGE)


@router.get("/{payload_id}", responses={HTTPStatus.NOT_FOUND: {"description": PAYLOAD_NOT_FOUND_DETAIL}})
async def get_payload(
    payload_id: UUID, use_case: Annotated[GetPayloadUseCase, Depends(get_get_payload_use_case)]
) -> PayloadReadResponse:
    """Return a generated payload.

    Args:
        payload_id: Identifier returned by ``POST /payload``.
        use_case: Get-payload use case.

    Returns:
        The payload output.

    Raises:
        HTTPException: 404 if no payload has this id.
    """
    output = await use_case.execute(payload_id)
    if output is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=PAYLOAD_NOT_FOUND_DETAIL)
    return PayloadReadResponse(output=output)
```

`caching_service/api/routes/health.py`:

```python
from fastapi import APIRouter

from caching_service.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> HealthResponse:
    """Report that the process is serving requests.

    Returns:
        ``{"status": "ok"}``.
    """
    return HealthResponse(status="ok")
```

`caching_service/api/app.py`:

```python
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from caching_service.api.errors import validation_error_handler
from caching_service.api.lifespan import lifespan
from caching_service.api.routes.health import router as health_router
from caching_service.api.routes.payload import router as payload_router


def create_app() -> FastAPI:
    """Build the FastAPI application (uvicorn factory).

    Returns:
        The configured application.
    """
    app = FastAPI(title="caching-service", lifespan=lifespan)
    app.exception_handler(RequestValidationError)(validation_error_handler)
    app.include_router(health_router)
    app.include_router(payload_router)
    return app
```

If importing `dependencies.py` raises `TypeError: Depends() got an unexpected keyword argument 'scope'`, the resolved FastAPI is too old. Run `uv lock --upgrade-package fastapi` and confirm `uv run python -c "import fastapi; print(fastapi.__version__)"` prints ≥ 0.121. Do **not** drop `scope="function"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/api -v`
Expected: PASS. In particular `test_invalid_bodies_are_rejected_without_side_effects[lone_surrogate]`, `test_commit_failure_reaches_the_client`, `test_overlapping_requests_in_opposite_order_do_not_deadlock` and `test_cached_empty_string_is_not_transformed_again` are green.

- [ ] **Step 5: Prove the two guards are load-bearing (then revert)**

Temporarily change `scope="function"` to `scope="request"` in `dependencies.py` and run `uv run pytest tests/integration/api/test_commit_timing.py -v`. Expected: FAIL (`201 != 500`). Revert.
Temporarily remove the `app.exception_handler(...)` line in `app.py` and run `uv run pytest "tests/integration/api/test_validation.py" -v -k lone_surrogate`. Expected: FAIL (500 or `UnicodeEncodeError`). Revert.

- [ ] **Step 6: Run the full suite, lint, commit (print for the user)**

Run: `uv run pytest -v && uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli migrations/env.py`

```bash
git add caching_service/core/db.py caching_service/api tests/integration/api
git commit -m "feat: expose payload API with commit-before-response and storage-safe 422s"
```

---

### Task 9: CLI settings and input/output helpers

**Files:**
- Create: `cache_cli/constants.py`, `cache_cli/settings.py`, `cache_cli/io.py`
- Test: `tests/units/cli/test_settings.py`, `tests/units/cli/test_io.py`

**Interfaces:**
- Consumes: `PayloadCreateRequest` (Task 3).
- Produces:
  - `cache_cli.constants`: `PROG_NAME`, `DEFAULT_HOST`, `STDIO_MARKER`, `HTTP_TIMEOUT_SECONDS`, `EXIT_OK`, `EXIT_REQUEST_FAILED`, `EXIT_INVALID_INPUT`.
  - `CacheCliSettings` fields `host: AnyHttpUrl`, `repeat: PositiveInt`, `input_file: str | None`, `json_input: str | None`, `output_file: str`.
  - `parse_settings(argv: Sequence[str]) -> CacheCliSettings`. Raises `pydantic.ValidationError` on bad values, `SystemExit(0)` on `--help`, `SystemExit(2)` on argparse errors.
  - `load_request(settings: CacheCliSettings, stdin: TextIO) -> PayloadCreateRequest`. Raises `OSError` or `ValueError` (incl. `ValidationError`).
  - `open_sink(output_file: str, stdout: TextIO) -> ContextManager[TextIO]`.

- [ ] **Step 1: Write the failing tests**

`tests/units/cli/test_settings.py`:

```python
import pytest
from pydantic import ValidationError

from cache_cli.settings import parse_settings

JSON_ARGS = ["-j", '{"list_1":["a"],"list_2":["b"]}']


def test_defaults() -> None:
    settings = parse_settings(JSON_ARGS)

    assert str(settings.host) == "http://localhost:8000/"
    assert settings.repeat == 1
    assert settings.input_file is None
    assert settings.json_input == JSON_ARGS[1]
    assert settings.output_file == "-"


def test_short_h_sets_the_host() -> None:
    assert str(parse_settings(["-h", "http://example:9000", *JSON_ARGS]).host) == "http://example:9000/"


def test_long_flags() -> None:
    settings = parse_settings(
        ["--host", "http://example:9000", "--repeat", "3", "--input", "in.json", "--output", "out.jsonl"]
    )

    assert str(settings.host) == "http://example:9000/"
    assert settings.repeat == 3
    assert settings.input_file == "in.json"
    assert settings.output_file == "out.jsonl"


def test_help_flag_prints_usage_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        parse_settings(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    for flag in ("--host", "--repeat", "--input", "--json", "--output"):
        assert flag in help_text


@pytest.mark.parametrize("argv", [["-i", "in.json", *JSON_ARGS], []], ids=["both", "neither"])
def test_requires_exactly_one_input_source(argv: list[str]) -> None:
    with pytest.raises(ValidationError, match="exactly one of --input or --json"):
        parse_settings(argv)


@pytest.mark.parametrize("repeat", ["0", "-1"])
def test_rejects_non_positive_repeat(repeat: str) -> None:
    with pytest.raises(ValidationError):
        parse_settings(["-r", repeat, *JSON_ARGS])


def test_rejects_non_numeric_repeat() -> None:
    with pytest.raises((ValidationError, SystemExit)):
        parse_settings(["-r", "abc", *JSON_ARGS])


@pytest.mark.parametrize("host", ["localhost:8000", "ftp://example"])
def test_rejects_non_http_hosts(host: str) -> None:
    with pytest.raises(ValidationError):
        parse_settings(["-h", host, *JSON_ARGS])


def test_unknown_flag_exits_with_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        parse_settings(["--bogus", *JSON_ARGS])

    assert exit_info.value.code == 2


def test_environment_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {"HOST": "http://evil:1", "REPEAT": "5", "OUTPUT": "/tmp/evil", "h": "http://evil:2"}.items():
        monkeypatch.setenv(name, value)

    settings = parse_settings(JSON_ARGS)

    assert str(settings.host) == "http://localhost:8000/"
    assert settings.repeat == 1
    assert settings.output_file == "-"
```

`tests/units/cli/test_io.py`:

```python
import io
from pathlib import Path

import pytest
from pydantic import ValidationError

from cache_cli.io import load_request, open_sink
from cache_cli.settings import parse_settings
from caching_service.schemas.payload import PayloadCreateRequest

SAMPLE_JSON = '{"list_1":["a"],"list_2":["b"]}'
EXPECTED = PayloadCreateRequest(list_1=["a"], list_2=["b"])


def test_loads_inline_json() -> None:
    assert load_request(parse_settings(["-j", SAMPLE_JSON]), io.StringIO()) == EXPECTED


def test_loads_a_file(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    input_path.write_text(SAMPLE_JSON, encoding="utf-8")

    assert load_request(parse_settings(["-i", str(input_path)]), io.StringIO()) == EXPECTED


def test_loads_stdin_for_dash() -> None:
    assert load_request(parse_settings(["-i", "-"]), io.StringIO(SAMPLE_JSON)) == EXPECTED


def test_missing_file_raises_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load_request(parse_settings(["-i", str(tmp_path / "missing.json")]), io.StringIO())


@pytest.mark.parametrize("raw", ["not json", '{"list_1":["a","b"],"list_2":["c"]}'], ids=["not_json", "unequal"])
def test_invalid_input_raises_validation_error(raw: str) -> None:
    with pytest.raises(ValidationError):
        load_request(parse_settings(["-j", raw]), io.StringIO())


def test_dash_sink_is_stdout_and_stays_open() -> None:
    stdout = io.StringIO()

    with open_sink("-", stdout) as sink:
        sink.write("line\n")

    assert sink is stdout
    assert not stdout.closed
    assert stdout.getvalue() == "line\n"


def test_file_sink_writes_utf8(tmp_path: Path) -> None:
    output_path = tmp_path / "out.jsonl"

    with open_sink(str(output_path), io.StringIO()) as sink:
        sink.write("straße\n")

    assert output_path.read_text(encoding="utf-8") == "straße\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/units/cli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cache_cli.settings'`

- [ ] **Step 3: Implement**

`cache_cli/constants.py`:

```python
PROG_NAME = "cache-cli"
DEFAULT_HOST = "http://localhost:8000"
STDIO_MARKER = "-"
HTTP_TIMEOUT_SECONDS = 30.0

EXIT_OK = 0
EXIT_REQUEST_FAILED = 1
EXIT_INVALID_INPUT = 2
```

`cache_cli/settings.py`:

```python
from argparse import ArgumentParser
from collections.abc import Sequence
from typing import Self

from pydantic import AliasChoices, AnyHttpUrl, Field, PositiveInt, model_validator
from pydantic_settings import BaseSettings, CliApp, CliSettingsSource, PydanticBaseSettingsSource

from cache_cli.constants import DEFAULT_HOST, PROG_NAME, STDIO_MARKER

HELP_DESCRIPTION = (
    "POST a payload to the caching service and GET it back, N times. "
    "Note: -h is --host (as in the service brief); use --help for this message."
)


class CacheCliSettings(BaseSettings):
    """Validated command-line arguments of ``cache-cli``.

    Attributes:
        host: Base URL of the caching service.
        repeat: Number of POST+GET iterations.
        input_file: Path of a JSON request file, or ``-`` for stdin.
        json_input: The JSON request given inline.
        output_file: Path for result lines, or ``-`` for stdout.
    """

    host: AnyHttpUrl = Field(
        default=AnyHttpUrl(DEFAULT_HOST),
        validation_alias=AliasChoices("h", "host"),
        description="Base URL of the caching service.",
    )
    repeat: PositiveInt = Field(
        default=1, validation_alias=AliasChoices("r", "repeat"), description="Number of POST+GET iterations."
    )
    input_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices("i", "input"),
        description=f"Read the request JSON from FILE ('{STDIO_MARKER}' for stdin).",
    )
    json_input: str | None = Field(
        default=None, validation_alias=AliasChoices("j", "json"), description="The request JSON, inline."
    )
    output_file: str = Field(
        default=STDIO_MARKER,
        validation_alias=AliasChoices("o", "output"),
        description=f"Write result lines to FILE ('{STDIO_MARKER}' for stdout).",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read nothing but the command line.

        ``env_prefix`` does not apply to aliased fields, so the default env source would let a stray
        ``HOST`` or ``REPEAT`` variable in the user's shell silently change the CLI's behaviour.

        Args:
            settings_cls: The settings class.
            init_settings: Values passed to ``__init__`` (where ``CliApp.run`` puts parsed arguments).
            env_settings: Environment source (dropped).
            dotenv_settings: Dotenv source (dropped).
            file_secret_settings: Secrets-directory source (dropped).

        Returns:
            Only ``init_settings``. ``CliApp.run`` layers the CLI source on top.
        """
        return (init_settings,)

    @model_validator(mode="after")
    def _exactly_one_input_source(self) -> Self:
        """Require exactly one of ``--input`` / ``--json``.

        Returns:
            The validated settings.

        Raises:
            ValueError: If both or neither source is given.
        """
        if (self.input_file is None) == (self.json_input is None):
            raise ValueError("exactly one of --input or --json is required")
        return self


def parse_settings(argv: Sequence[str]) -> CacheCliSettings:
    """Parse and validate ``cache-cli`` arguments.

    ``-h`` belongs to ``--host`` (as in the brief's usage line), so argparse's built-in ``-h/--help`` is
    disabled and ``--help`` is registered on its own.

    Args:
        argv: Arguments without the program name.

    Returns:
        Validated settings.

    Raises:
        pydantic.ValidationError: If a value fails validation (URL, repeat, input sources).
        SystemExit: Code 0 on ``--help``; code 2 on argparse errors such as unknown flags.
    """
    parser = ArgumentParser(prog=PROG_NAME, description=HELP_DESCRIPTION, add_help=False)
    parser.add_argument("--help", action="help", help="Show this help message and exit.")
    cli_source = CliSettingsSource(CacheCliSettings, root_parser=parser)
    return CliApp.run(CacheCliSettings, cli_args=list(argv), cli_settings_source=cli_source)
```

`cache_cli/io.py`:

```python
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from cache_cli.constants import STDIO_MARKER
from cache_cli.settings import CacheCliSettings
from caching_service.schemas.payload import PayloadCreateRequest


def load_request(settings: CacheCliSettings, stdin: TextIO) -> PayloadCreateRequest:
    """Read the request JSON from the chosen source and validate it with the server's rules.

    Validating here means malformed input never reaches the network.

    Args:
        settings: Parsed CLI settings.
        stdin: Stream read when ``--input -`` is given.

    Returns:
        The validated request body.

    Raises:
        OSError: If the input file cannot be read.
        ValueError: If no source is set, the text is not UTF-8, or the JSON breaks the payload rules
            (``pydantic.ValidationError`` is a ``ValueError``).
    """
    if settings.json_input is not None:
        raw = settings.json_input
    elif settings.input_file == STDIO_MARKER:
        raw = stdin.read()
    elif settings.input_file is not None:
        raw = Path(settings.input_file).read_text(encoding="utf-8")
    else:
        raise ValueError("no input source given")
    return PayloadCreateRequest.model_validate_json(raw)


@contextmanager
def open_sink(output_file: str, stdout: TextIO) -> Iterator[TextIO]:
    """Open the output destination.

    Args:
        output_file: Path, or ``-`` for stdout.
        stdout: Stream used for ``-``. It is never closed here.

    Yields:
        A writable text stream.

    Raises:
        OSError: If the file cannot be opened for writing.
    """
    if output_file == STDIO_MARKER:
        yield stdout
        return
    with Path(output_file).open("w", encoding="utf-8") as sink:
        yield sink
```

If `test_short_h_sets_the_host` or `test_long_flags` fails because parsed CLI values are ignored, `CliApp.run` is not layering the CLI source over the reduced source tuple in the installed pydantic-settings version. Read `_settings_build_values` in `.venv/lib/python3.12/site-packages/pydantic_settings/main.py` and report back before changing the design: dropping the env override would reopen Review Focus item 4.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/units/cli -v`
Expected: PASS

- [ ] **Step 5: Lint and commit (print for the user)**

Run: `uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli migrations/env.py`

```bash
git add cache_cli tests/units/cli
git commit -m "feat: add cache-cli argument parsing and input/output handling"
```

---

### Task 10: CLI runner and entry point

**Files:**
- Create: `cache_cli/runner.py`, `cache_cli/main.py`
- Test: `tests/units/cli/test_main.py`, `tests/integration/cli/test_cli_end_to_end.py`

**Interfaces:**
- Consumes: `parse_settings`, `CacheCliSettings`, `load_request`, `open_sink`, CLI constants (Task 9); `PayloadCreateResponse`, `PayloadReadResponse` (Task 3); `create_app`, `get_session_factory`, `get_transformer` (Task 8); `get_settings` (Task 4); `truncate_tables` (Task 4); `CountingTransformerClient` (Task 6); `SAMPLE_REQUEST`/`SAMPLE_OUTPUT` (Task 7).
- Produces:
  - `run_iterations(client: httpx.Client, request: PayloadCreateRequest, repeat: int) -> Iterator[str]`
  - `main(argv: Sequence[str], stdin: TextIO | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None, http_client_factory: Callable[[CacheCliSettings], httpx.Client] = build_http_client) -> int`
  - `entrypoint() -> None` (the `cache-cli` console script).

- [ ] **Step 1: Write the failing tests**

`tests/units/cli/test_main.py`:

```python
import io
import json
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from cache_cli.main import main
from cache_cli.settings import CacheCliSettings

PAYLOAD_ID = "8f14e45f-ceea-467a-9575-3ad7d2c1f1a1"
SAMPLE_JSON = '{"list_1":["a"],"list_2":["b"]}'


@dataclass
class CliRun:
    code: int
    stdout: str
    stderr: str
    requests: list[httpx.Request]


def _run(argv: list[str], *, fail_from: int | None = None, refuse_connection: bool = False) -> CliRun:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if refuse_connection:
            raise httpx.ConnectError("connection refused", request=request)
        if fail_from is not None and len(requests) >= fail_from:
            return httpx.Response(500, json={"detail": "boom"})
        if request.method == "POST":
            first_post = sum(item.method == "POST" for item in requests) == 1
            return httpx.Response(201 if first_post else 200, json={"id": PAYLOAD_ID, "message": "ignored"})
        return httpx.Response(200, json={"output": "A, B"})

    def factory(settings: CacheCliSettings) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), base_url=str(settings.host))

    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(argv, stdin=io.StringIO(SAMPLE_JSON), stdout=stdout, stderr=stderr, http_client_factory=factory)
    return CliRun(code, stdout.getvalue(), stderr.getvalue(), requests)


def test_single_iteration_writes_one_json_line() -> None:
    run = _run(["-j", SAMPLE_JSON])

    assert run.code == 0, run.stderr
    assert [json.loads(line) for line in run.stdout.splitlines()] == [
        {"iteration": 1, "id": PAYLOAD_ID, "created": True, "output": "A, B"}
    ]
    assert [(request.method, request.url.path) for request in run.requests] == [
        ("POST", "/payload"),
        ("GET", f"/payload/{PAYLOAD_ID}"),
    ]
    assert json.loads(run.requests[0].content) == {"list_1": ["a"], "list_2": ["b"]}


def test_stdin_input_is_used_for_dash() -> None:
    run = _run(["-i", "-"])

    assert run.code == 0, run.stderr
    assert len(run.stdout.splitlines()) == 1


def test_repeat_runs_n_iterations_and_reports_creation() -> None:
    run = _run(["-j", SAMPLE_JSON, "-r", "3"])

    lines = [json.loads(line) for line in run.stdout.splitlines()]
    assert [line["iteration"] for line in lines] == [1, 2, 3]
    assert [line["created"] for line in lines] == [True, False, False]


def test_output_file_receives_the_lines(tmp_path: Path) -> None:
    output_path = tmp_path / "out.jsonl"

    run = _run(["-j", SAMPLE_JSON, "-o", str(output_path)])

    assert run.code == 0
    assert run.stdout == ""
    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 1


def test_server_error_exits_1() -> None:
    run = _run(["-j", SAMPLE_JSON], fail_from=1)

    assert run.code == 1
    assert "request failed" in run.stderr


def test_connection_error_exits_1() -> None:
    run = _run(["-j", SAMPLE_JSON], refuse_connection=True)

    assert run.code == 1
    assert "request failed" in run.stderr


def test_failure_mid_run_keeps_earlier_lines() -> None:
    run = _run(["-j", SAMPLE_JSON, "-r", "3"], fail_from=3)  # request 3 is the second iteration's POST

    assert run.code == 1
    assert len(run.stdout.splitlines()) == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["-j", '{"list_1":["a","b"],"list_2":["c"]}'],
        ["-j", "not json"],
        ["-i", "-", "-j", SAMPLE_JSON],
        ["-j", SAMPLE_JSON, "-r", "0"],
        ["-j", SAMPLE_JSON, "-h", "ftp://example"],
    ],
    ids=["unequal_lists", "not_json", "both_sources", "zero_repeat", "bad_host"],
)
def test_invalid_input_exits_2_without_any_request(argv: list[str]) -> None:
    run = _run(argv)

    assert run.code == 2
    assert "invalid input" in run.stderr
    assert run.requests == []


def test_missing_input_file_exits_2_without_any_request(tmp_path: Path) -> None:
    run = _run(["-i", str(tmp_path / "missing.json")])

    assert run.code == 2
    assert run.requests == []


def test_unwritable_output_exits_2_without_any_request(tmp_path: Path) -> None:
    run = _run(["-j", SAMPLE_JSON, "-o", str(tmp_path / "missing-dir" / "out.jsonl")])

    assert run.code == 2
    assert run.requests == []
```

`tests/integration/cli/test_cli_end_to_end.py` (synchronous: `TestClient` runs the app on its own loop, so the engine uses NullPool and is created outside any loop):

```python
import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from cache_cli.main import main
from caching_service.api.app import create_app
from caching_service.api.dependencies import get_session_factory, get_transformer
from caching_service.core.config import get_settings
from tests.fakes import CountingTransformerClient
from tests.integration.database import set_postgres_env, truncate_tables
from tests.samples import SAMPLE_OUTPUT, SAMPLE_REQUEST


def test_cli_repeats_against_the_real_app(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    set_postgres_env(monkeypatch, postgres_url)
    get_settings.cache_clear()
    truncate_tables(postgres_url)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    transformer = CountingTransformerClient()
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: async_sessionmaker(engine, expire_on_commit=False)
    app.dependency_overrides[get_transformer] = lambda: transformer
    stdout, stderr = io.StringIO(), io.StringIO()

    try:
        code = main(
            ["-j", json.dumps(SAMPLE_REQUEST), "-r", "3"],
            stdin=io.StringIO(),
            stdout=stdout,
            stderr=stderr,
            http_client_factory=lambda _settings: TestClient(app),
        )
    finally:
        get_settings.cache_clear()

    assert code == 0, stderr.getvalue()
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [line["created"] for line in lines] == [True, False, False]
    assert len({line["id"] for line in lines}) == 1
    assert {line["output"] for line in lines} == {SAMPLE_OUTPUT}
    assert len(transformer.calls) == 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/units/cli/test_main.py tests/integration/cli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cache_cli.main'`

- [ ] **Step 3: Implement**

`cache_cli/runner.py`:

```python
import json
from collections.abc import Iterator
from http import HTTPStatus

import httpx

from caching_service.schemas.payload import PayloadCreateRequest, PayloadCreateResponse, PayloadReadResponse


def run_iterations(client: httpx.Client, request: PayloadCreateRequest, repeat: int) -> Iterator[str]:
    """POST the payload and GET it back ``repeat`` times, yielding one JSON line per iteration.

    Lines are yielded as each iteration finishes, so a later failure keeps the earlier results.

    Args:
        client: HTTP client with ``base_url`` pointing at the service.
        request: Validated request body.
        repeat: Number of iterations (≥ 1).

    Yields:
        A JSON object with ``iteration`` (1-based), ``id``, ``created`` and ``output``.

    Raises:
        httpx.HTTPError: On a connection failure or a non-2xx response.
    """
    body = request.model_dump()
    for iteration in range(1, repeat + 1):
        create_response = client.post("/payload", json=body)
        create_response.raise_for_status()
        created = PayloadCreateResponse.model_validate(create_response.json())

        read_response = client.get(f"/payload/{created.id}")
        read_response.raise_for_status()
        payload = PayloadReadResponse.model_validate(read_response.json())

        yield json.dumps(
            {
                "iteration": iteration,
                "id": str(created.id),
                "created": create_response.status_code == HTTPStatus.CREATED,
                "output": payload.output,
            },
            ensure_ascii=False,
        )
```

`cache_cli/main.py`:

```python
import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from typing import TextIO

import httpx

from cache_cli.constants import EXIT_INVALID_INPUT, EXIT_OK, EXIT_REQUEST_FAILED, HTTP_TIMEOUT_SECONDS, PROG_NAME
from cache_cli.io import load_request, open_sink
from cache_cli.runner import run_iterations
from cache_cli.settings import CacheCliSettings, parse_settings

HttpClientFactory = Callable[[CacheCliSettings], httpx.Client]


def build_http_client(settings: CacheCliSettings) -> httpx.Client:
    """Create the HTTP client for a real run.

    Args:
        settings: Parsed CLI settings.

    Returns:
        A client whose ``base_url`` is ``settings.host``.
    """
    return httpx.Client(base_url=str(settings.host), timeout=HTTP_TIMEOUT_SECONDS)


def main(
    argv: Sequence[str],
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    http_client_factory: HttpClientFactory = build_http_client,
) -> int:
    """Run ``cache-cli``.

    Everything that can fail on bad input (arguments, input parsing, opening the output file) happens
    before the first request, so invalid input never reaches the server.

    Args:
        argv: Arguments without the program name.
        stdin: Input stream for ``--input -``. Defaults to ``sys.stdin``.
        stdout: Output stream for ``--output -``. Defaults to ``sys.stdout``.
        stderr: Stream for error messages. Defaults to ``sys.stderr``.
        http_client_factory: Builds the HTTP client. Tests inject a mock or a ``TestClient``.

    Returns:
        ``0`` on success, ``1`` on HTTP or connection failure, ``2`` on invalid arguments or input.
    """
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    with ExitStack() as stack:
        try:
            settings = parse_settings(argv)
            request = load_request(settings, stdin)
            sink = stack.enter_context(open_sink(settings.output_file, stdout))
        except (ValueError, OSError) as error:
            print(f"{PROG_NAME}: invalid input: {error}", file=stderr)
            return EXIT_INVALID_INPUT

        client = stack.enter_context(http_client_factory(settings))
        try:
            for line in run_iterations(client, request, settings.repeat):
                sink.write(f"{line}\n")
                sink.flush()
        except httpx.HTTPError as error:
            print(f"{PROG_NAME}: request failed: {error}", file=stderr)
            return EXIT_REQUEST_FAILED
    return EXIT_OK


def entrypoint() -> None:
    """Console-script entry point for ``cache-cli``."""
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/units/cli tests/integration/cli -v`
Expected: PASS

- [ ] **Step 5: Smoke-test the console script**

Run: `uv run cache-cli --help`
Expected: exit 0. Usage line starts `usage: cache-cli` and lists `-h HOST, --host HOST` (or similar) and `--help`.

- [ ] **Step 6: Full suite, lint, commit (print for the user)**

Run: `uv run pytest -v && uv run ruff check . && uv run black --check . && uv run mypy caching_service cache_cli migrations/env.py`

```bash
git add cache_cli tests/units/cli tests/integration/cli
git commit -m "feat: add cache-cli runner and console entry point"
```

---

### Task 11: Docker, compose and README

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `README.md`

**Interfaces:**
- Consumes: `caching_service.api.app:create_app` (uvicorn factory), `alembic.ini` + `migrations/`, env vars `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `LOG_LEVEL`. Public PyPI only, so the build needs no secrets.
- Produces: `docker compose up --build` → `postgres` (healthy) → `migrations` (exits 0) → `caching-service` on `:8000` with a `/health` healthcheck.

- [ ] **Step 1: Write the Dockerfile**

`Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependencies first, so code edits do not invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY caching_service ./caching_service
COPY cache_cli ./cache_cli
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "caching_service.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write the compose file**

`docker-compose.yml`:

```yaml
# Local development only: these credentials never leave the compose network.
# The same POSTGRES_* names configure both the postgres image and the service.
x-db-env: &db-env
  POSTGRES_USER: caching
  POSTGRES_PASSWORD: caching
  POSTGRES_DB: caching

x-app-env: &app-env
  <<: *db-env
  POSTGRES_HOST: postgres
  POSTGRES_PORT: "5432"
  LOG_LEVEL: INFO

services:
  postgres:
    image: postgres:16-alpine
    environment: *db-env
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U caching -d caching"]
      interval: 2s
      timeout: 3s
      retries: 15

  migrations:
    build: .
    image: caching-service:local
    environment: *app-env
    command: ["alembic", "upgrade", "head"]
    depends_on:
      postgres:
        condition: service_healthy

  caching-service:
    build: .
    image: caching-service:local
    environment: *app-env
    ports:
      - "8000:8000"
    depends_on:
      migrations:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 5s
      timeout: 3s
      retries: 6

volumes:
  pg_data:
```

- [ ] **Step 3: Write the README**

`README.md`:

````markdown
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

Configuration (environment): `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (required),
`POSTGRES_HOST` (default `localhost`), `POSTGRES_PORT` (default `5432`), `LOG_LEVEL` (default `INFO`).

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

## Shortcuts and assumptions

- The transformer is `str.upper()` with no latency, behind the `TransformerClient` protocol.
- Postgres is the only cache tier: no Redis, no in-process LRU, no expiry (uppercase is deterministic).
- Two concurrent requests that first see the same string at the same moment may each call the
  transformer once. `ON CONFLICT DO NOTHING` keeps one row. No cross-request locking.
- Empty lists, non-string items, NUL characters and lone surrogates are rejected with `422`.
- Limits: 1–1000 items per list, ≤ 10 000 characters per item.
- Payload identity is order-sensitive. The input lists are not stored, only the output.
````

- [ ] **Step 4: Verify the stack (M-1, M-2)**

Run: `docker compose up --build -d && sleep 20 && curl -fsS localhost:8000/health`
Expected: `{"status":"ok"}`. `docker compose ps` shows `migrations` exited with code 0.

Run: `echo '{"list_1":["first string","second string","third string"],"list_2":["other string","another string","last string"]}' | uv run cache-cli -i - -r 2`
Expected: two lines with the same `id`, `output` = `"FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"`. `created` is `true` then `false` on a fresh database.

- [ ] **Step 5: Verify logging reaches the container (M-3)**

Run: `docker compose logs caching-service | grep -c "Payload stored"`
Expected: `≥ 1` (from the Step 4 CLI run).

Run: `docker compose down`

- [ ] **Step 6: Commit (print for the user)**

```bash
git add Dockerfile docker-compose.yml README.md
git commit -m "build: add Dockerfile, compose stack and README"
```

---

## Spec Coverage Map

| AC | Task / test |
|---|---|
| AC-1, AC-2, AC-19 | T8 `test_sample_input_is_created_and_read_back`; T7 `test_new_input_produces_the_sample_output` |
| AC-3..AC-8 | T3 schema tests; T8 `test_invalid_bodies_are_rejected_without_side_effects`, `test_unequal_lengths_error_names_the_rule` |
| AC-9 | T3 `test_accepts_empty_string_items`; T8 `test_empty_string_item_produces_a_leading_separator` |
| AC-10 | T7 `test_known_input_takes_the_fast_path_without_transforming`; T8 `test_repeated_input_returns_the_same_id_without_new_work` |
| AC-11 | T2 hash tests; T8 `test_swapped_lists_are_a_different_payload` |
| AC-12, AC-13, AC-14 | T6 service tests; T8 cache tests |
| AC-15 | T7 `test_create_returns_the_existing_id_when_the_insert_loses`; T8 `test_concurrent_identical_posts_converge_on_one_payload` |
| AC-39 | T8 `test_overlapping_requests_in_opposite_order_do_not_deadlock` |
| AC-16 | T5 `test_concurrent_sessions_inserting_the_same_hash_keep_one_row`, `test_saving_an_existing_hash_keeps_the_original_row` |
| AC-17, AC-18 | T5 `test_values_longer_than_a_btree_entry_round_trip`; T6 transformer tests; T8 `test_unicode_long_and_separator_strings_round_trip` |
| AC-20, AC-21, AC-24 | T8 `test_unknown_id_returns_404`, `test_malformed_id_returns_422`, `test_health` |
| AC-22 | T8 `test_commit_failure_reaches_the_client` |
| AC-23 | T8 `test_statement_budget.py` |
| AC-25 | T8 `test_real_lifespan_serves_health_create_and_read` |
| AC-26..AC-36 | T9 settings/io tests; T10 `test_main.py`, `test_cli_repeats_against_the_real_app` |
| AC-37 | T11 Steps 4–5 |
| AC-38 | T4 `test_migrations.py` |
