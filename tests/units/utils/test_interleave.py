import pytest

from caching_service.utils.interleave import interleave


def test_interleave_alternates_items() -> None:
    assert interleave(["a", "b"], ["c", "d"]) == ["a", "c", "b", "d"]


def test_interleave_rejects_unequal_lengths() -> None:
    with pytest.raises(ValueError):
        interleave(["a", "b"], ["c"])
