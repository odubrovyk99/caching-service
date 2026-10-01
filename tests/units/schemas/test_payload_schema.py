import pytest
from pydantic import ValidationError

from caching_service.constants import MAX_LIST_LENGTH, MAX_STRING_LENGTH
from caching_service.schemas.payload import PayloadCreateRequest


def test_accepts_equal_length_lists() -> None:
    request = PayloadCreateRequest.model_validate({"list_1": ["a", "b"], "list_2": ["c", "d"]})

    assert request.list_1 == ["a", "b"]
    assert request.list_2 == ["c", "d"]


def test_rejects_lists_of_different_length() -> None:
    with pytest.raises(ValidationError, match="same length"):
        PayloadCreateRequest.model_validate({"list_1": ["a", "b"], "list_2": ["c"]})


def test_rejects_empty_lists() -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": [], "list_2": []})


@pytest.mark.parametrize("bad_item", [123, None, True, {"x": 1}])
def test_rejects_non_string_items_without_coercion(bad_item: object) -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": [bad_item], "list_2": ["a"]})


def test_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": ["a"], "list_2": ["b"], "list_3": ["c"]})


def test_rejects_missing_keys() -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": ["a"]})


def test_accepts_lists_at_the_length_limit() -> None:
    items = ["x"] * MAX_LIST_LENGTH

    PayloadCreateRequest.model_validate({"list_1": items, "list_2": items})


def test_rejects_lists_over_the_length_limit() -> None:
    items = ["x"] * (MAX_LIST_LENGTH + 1)

    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": items, "list_2": items})


def test_accepts_items_at_the_string_limit() -> None:
    PayloadCreateRequest.model_validate({"list_1": ["x" * MAX_STRING_LENGTH], "list_2": ["y"]})


def test_rejects_items_over_the_string_limit() -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": ["x" * (MAX_STRING_LENGTH + 1)], "list_2": ["y"]})


@pytest.mark.parametrize("unstorable", ["a\x00b", "\ud800"], ids=["nul_character", "lone_surrogate"])
def test_rejects_strings_postgres_cannot_store(unstorable: str) -> None:
    with pytest.raises(ValidationError):
        PayloadCreateRequest.model_validate({"list_1": [unstorable], "list_2": ["a"]})


def test_accepts_empty_string_items() -> None:
    request = PayloadCreateRequest.model_validate({"list_1": [""], "list_2": ["a"]})

    assert request.list_1 == [""]
