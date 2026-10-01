import pytest

from caching_service.clients.transformer_client import UppercaseTransformerClient


@pytest.mark.parametrize(
    ("value", "expected"),
    [("first string", "FIRST STRING"), ("straße", "STRASSE"), ("héllo 👋", "HÉLLO 👋"), ("", "")],
)
async def test_uppercase_transformer(value: str, expected: str) -> None:
    assert await UppercaseTransformerClient().transform(value) == expected
