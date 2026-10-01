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
