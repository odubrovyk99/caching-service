# Test Checklist: Caching Service

Spec: `docs/02-spec.yaml` · RFC: `docs/01-RFC.md` · Tasks: `docs/04-tasks.md`

Unit tests live in `tests/units/` and need no Docker. Integration tests live in `tests/integration/`. They
start one `postgres:16-alpine` testcontainer per session, migrate it with Alembic, and `TRUNCATE` both
tables before each test.

> **Read first — three things that fail silently or only at runtime:**
> 1. **Commit timing (AC-22).** With FastAPI's default `yield`-dependency scope, the commit runs *after*
>    the response is sent. Every happy-path test still passes. Only I-14 (a `commit()` that raises must
>    produce `500`) catches the regression.
> 2. **Empty-string cache hits (AC-14).** `if not cached_output:` treats a cached `""` as a miss and
>    re-calls the transformer. Every test without `""` still passes. U-7d and I-6b pin it.
> 3. **CLI env leakage (AC-35).** `env_prefix` does not apply to aliased fields. A stray `HOST` env var
>    silently retargets the CLI. Only U-10h catches it.

---

## Unit — pure helpers (`tests/units/utils/`)

- [ ] **U-1** `sha256_hex("abc")` == `ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad`; result
      is 64 lowercase hex chars. *(algorithms.transformation_key)*
- [ ] **U-2a** `payload_input_hash` is deterministic for the same input.
- [ ] **U-2b** Swapping `list_1`/`list_2` changes the hash. *(AC-11)*
- [ ] **U-2c** Reordering items within a list changes the hash. *(AC-11)*
- [ ] **U-2d** Inputs that would collide under a separator join hash differently:
      `(["a,b"],["c"])` ≠ `(["a"],["b,c"])`.
- [ ] **U-3a** `interleave(["a","b"], ["c","d"])` == `["a","c","b","d"]`.
- [ ] **U-3b** `interleave` with unequal lengths raises `ValueError`.

## Unit — schema (`tests/units/schemas/test_payload_schema.py`)

- [ ] **U-4a** Equal-length lists validate. *(AC-1)*
- [ ] **U-4b** Unequal lengths → `ValidationError` mentioning "same length". *(AC-3)*
- [ ] **U-4c** Empty lists → error. *(AC-4)*
- [ ] **U-4d** `123`, `None`, `True`, `{"x":1}` as items → error. No coercion. *(AC-5)*
- [ ] **U-4e** Extra key `list_3` → error. Missing `list_2` → error. *(AC-6)*
- [ ] **U-4f** 1000 items OK, 1001 → error. 10000-char item OK, 10001 → error. *(AC-7)*
- [ ] **U-4g** Item with `"\x00"` → error. Item with lone surrogate `"\ud800"` → error. *(AC-8)*
- [ ] **U-4h** `""` item validates. *(AC-9)*

## Unit — transformer client (`tests/units/clients/`)

- [ ] **U-6** `UppercaseTransformerClient.transform`: `"first string"`→`"FIRST STRING"`, `"straße"`→`"STRASSE"`,
      `""`→`""`. *(AC-2, AC-18)*

## Unit — services and use cases (fakes, no DB) (`tests/units/services/`, `tests/units/use_cases/`)

- [ ] **U-7a** `TransformationService.transform_all` on an empty cache calls the transformer once per distinct
      value and returns a full mapping.
- [ ] **U-7b** Duplicates within the input → one call per distinct value. *(AC-13)*
- [ ] **U-7c** Values already in the repo are not sent to the transformer. *(AC-12)*
- [ ] **U-7d** A cached `""` output is a hit. *(AC-14)*
- [ ] **U-7e** Only misses are passed to `save_many`, each with the correct hash.
- [ ] **U-8a** `PayloadService.create`: insert wins → `created=True` with the generated id.
- [ ] **U-8b** Insert loses (conflict) → returns the existing id, `created=False`. *(AC-15 path)*
- [ ] **U-8c** Insert loses but no row is visible → `RuntimeError`.
- [ ] **U-9a** `CreatePayloadUseCase`: existing hash → fast path, 0 transformer calls, `created=False`. *(AC-10)*
- [ ] **U-9b** New input → sample output string exactly. *(AC-2)*

## Unit — CLI (`tests/units/cli/`)

- [ ] **U-10a** Defaults: host `http://localhost:8000/`, repeat 1, output `-`.
- [ ] **U-10b** `-h http://example:9000` sets host. Long flags work too. *(AC-32)*
- [ ] **U-10c** `--help` → `SystemExit(0)`, help text lists all five long flags. *(AC-32)*
- [ ] **U-10d** Both `-i` and `-j` → `ValidationError`. Neither → `ValidationError`. *(AC-30)*
- [ ] **U-10e** `-r 0`, `-r -1` → `ValidationError`. `-r abc` → `ValidationError` or `SystemExit(2)`. *(AC-31)*
- [ ] **U-10f** `-h localhost:8000`, `-h ftp://x` → `ValidationError`. *(AC-31)*
- [ ] **U-10g** Unknown flag → `SystemExit(2)`.
- [ ] **U-10h** Env `HOST`, `REPEAT`, `OUTPUT` set → ignored. *(AC-35)*
- [ ] **U-11a** `load_request` from `-j`, from file, from stdin `-`. All give the same `PayloadCreateRequest`. *(AC-27)*
- [ ] **U-11b** Missing file → `OSError`. Invalid JSON → `ValidationError`. Unequal lengths → `ValidationError`. *(AC-33)*
- [ ] **U-12a** `main` with `httpx2.MockTransport`: one iteration writes one correct JSON line, exit 0. *(AC-26)*
- [ ] **U-12b** `-r 3` → 3 lines, iterations 1..3, `created` taken from the 201/200 status. *(AC-28)*
- [ ] **U-12c** `-o file` → file has the lines, stdout empty. *(AC-29)*
- [ ] **U-12d** Server 500 → exit 1, "request failed" on stderr. *(AC-34)*
- [ ] **U-12e** `httpx2.ConnectError` → exit 1. *(AC-34)*
- [ ] **U-12f** Failure on iteration 2 of 3 → line 1 present in the output, exit 1. *(AC-34)*
- [ ] **U-12g** Invalid input (unequal lists, both sources, bad `-r`) → exit 2, **transport saw 0 requests**. *(AC-30, AC-31, AC-33)*
- [ ] **U-12h** `-o /nonexistent-dir/x.jsonl` → exit 2, transport saw 0 requests. *(AC-36)*

## Integration — DB layer (`tests/integration/db/`)

- [ ] **I-1** Alembic: after `upgrade head`, both tables and both unique indexes exist (checked via
      `pg_indexes`). `downgrade base` drops them, and `upgrade head` restores them. *(AC-38)*
- [ ] **I-2a** `TransformationRepository.save_many` + `get_outputs_by_hashes` round-trip. Unknown hashes are absent.
- [ ] **I-2b** `save_many` with an existing hash does not raise and keeps the original row. *(AC-16)*
- [ ] **I-2c** A 10000-char value round-trips. *(AC-17)*
- [ ] **I-3a** `PayloadRepository.insert_if_absent` → `True` the first time, `False` for the same hash.
- [ ] **I-3b** `get_output_by_id` returns output or `None`. `get_id_by_input_hash` returns id or `None`.
- [ ] **I-13** Two sessions insert the same transformation. Both commit without error, and 1 row exists. *(AC-16)*

## Integration — API (`tests/integration/api/`), httpx2 `ASGITransport` + counting transformer

- [ ] **I-4** Sample input → 201, then GET returns the exact sample output, with 6 transformer calls. *(AC-1, AC-2, AC-19)*
- [ ] **I-5** Same POST twice → 200, same id, "Payload already exists", calls unchanged, row counts unchanged. *(AC-10)*
- [ ] **I-6a** Partial overlap → only new strings transformed. Output correct. *(AC-12)*
- [ ] **I-6b** `""` cached by request 1 is not re-transformed by request 2. *(AC-14)*
- [ ] **I-7** `["a","a"],["a","b"]` cold → 2 calls, output `"A, A, A, B"`. *(AC-13)*
- [ ] **I-8** Swapped lists → 201 with a different id. *(AC-11)*
- [ ] **I-9** Statement counter: new 1000+1000 distinct payload ≤ 5 statements. Repeat → exactly 1. *(AC-23)*
- [ ] **I-10** GET unknown uuid → 404 `{"detail":"Payload not found"}`. GET `not-a-uuid` → 422. *(AC-20, AC-21)*
- [ ] **I-11** Invalid bodies (unequal, empty, `123` item, extra key, NUL, lone surrogate, 1001 items) → 422,
      0 rows in both tables, 0 transformer calls. *(AC-3..AC-8)* The lone-surrogate case only passes because of
      the ASCII-rendering `RequestValidationError` handler. FastAPI's default handler returns 500 there.
- [ ] **I-12** 5 concurrent identical POSTs (`asyncio.gather`) → all ids equal, 1 payload row. *(AC-15)*
- [ ] **I-12b** 10 rounds of two concurrent POSTs sharing 100 fresh strings in opposite order → all 201, no
      deadlock. *(AC-39)*
- [ ] **I-14** Session factory whose `commit()` raises → POST returns 500 (client built with
      `raise_app_exceptions=False`). *(AC-22)*
- [ ] **I-15** No overrides. `POSTGRES_*` env → container (`set_postgres_env`). `with TestClient(create_app())`:
      `/health` 200, POST 201, GET 200. *(AC-24, AC-25)*
- [ ] **I-16** Unicode and long strings: `"straße"`, `"héllo 👋"`, a 10000-char string, and a string containing
      `", "` all round-trip through POST/GET. *(AC-17, AC-18)*
- [ ] **I-17** `[""]`, `["a"]` → output `", A"`. *(AC-9)*

## Integration — CLI against the real app (`tests/integration/cli/`)

- [ ] **I-18** `main(["-j", <sample>, "-r", "3"], http_client_factory=lambda _: TestClient(app))` → 3 lines,
      same id, `created == [True, False, False]`, exact sample output. This test is synchronous and uses
      a NullPool engine, because TestClient runs the app on its own event loop. *(AC-26, AC-28)*

## Manual / deployment

- [ ] **M-1** From a clean checkout with no credentials, `docker compose up --build` → `migrations` exits 0, and
      `curl localhost:8000/health` returns 200 within 30 s. *(AC-37)*
- [ ] **M-2** `echo '<sample json>' | uv run cache-cli -i - -r 2` against the compose stack → 2 lines, same id. *(AC-27)*
- [ ] **M-3** `docker compose logs caching-service` shows the `Payload stored` log line from M-2 (stdlib logging
      reaches container stdout).
