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
