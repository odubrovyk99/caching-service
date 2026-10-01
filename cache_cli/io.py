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
