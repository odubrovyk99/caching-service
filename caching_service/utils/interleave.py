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
