import io
import json
from dataclasses import dataclass
from pathlib import Path

import httpx2
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
    requests: list[httpx2.Request]


def _run(argv: list[str], *, fail_from: int | None = None, refuse_connection: bool = False) -> CliRun:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if refuse_connection:
            raise httpx2.ConnectError("connection refused", request=request)
        if fail_from is not None and len(requests) >= fail_from:
            return httpx2.Response(500, json={"detail": "boom"})
        if request.method == "POST":
            first_post = sum(item.method == "POST" for item in requests) == 1
            return httpx2.Response(201 if first_post else 200, json={"id": PAYLOAD_ID, "message": "ignored"})
        return httpx2.Response(200, json={"output": "A, B"})

    def factory(settings: CacheCliSettings) -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(handler), base_url=str(settings.host))

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
