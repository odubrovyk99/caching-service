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
