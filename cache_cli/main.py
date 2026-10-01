import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from typing import TextIO

import httpx2

from cache_cli.constants import EXIT_INVALID_INPUT, EXIT_OK, EXIT_REQUEST_FAILED, HTTP_TIMEOUT_SECONDS, PROG_NAME
from cache_cli.io import load_request, open_sink
from cache_cli.runner import run_iterations
from cache_cli.settings import CacheCliSettings, parse_settings

HttpClientFactory = Callable[[CacheCliSettings], httpx2.Client]


def build_http_client(settings: CacheCliSettings) -> httpx2.Client:
    """Create the HTTP client for a real run.

    Args:
        settings: Parsed CLI settings.

    Returns:
        A client whose ``base_url`` is ``settings.host``.
    """
    return httpx2.Client(base_url=str(settings.host), timeout=HTTP_TIMEOUT_SECONDS)


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
        except httpx2.HTTPError as error:
            print(f"{PROG_NAME}: request failed: {error}", file=stderr)
            return EXIT_REQUEST_FAILED
    return EXIT_OK


def entrypoint() -> None:
    """Console-script entry point for ``cache-cli``."""
    sys.exit(main(sys.argv[1:]))
