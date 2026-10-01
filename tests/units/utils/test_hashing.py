from caching_service.utils.hashing import payload_input_hash, sha256_hex


def test_sha256_hex_matches_known_vector() -> None:
    assert sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_hex_returns_64_lowercase_hex_chars_for_unicode() -> None:
    digest = sha256_hex("Straße 👋")

    assert len(digest) == 64
    assert digest == digest.lower()
    int(digest, 16)


def test_payload_input_hash_is_deterministic() -> None:
    assert payload_input_hash(["a", "b"], ["c", "d"]) == payload_input_hash(["a", "b"], ["c", "d"])


def test_payload_input_hash_changes_when_lists_are_swapped() -> None:
    assert payload_input_hash(["a"], ["b"]) != payload_input_hash(["b"], ["a"])


def test_payload_input_hash_changes_when_items_are_reordered() -> None:
    assert payload_input_hash(["a", "b"], ["c", "d"]) != payload_input_hash(["b", "a"], ["c", "d"])


def test_payload_input_hash_does_not_collide_on_separator_characters() -> None:
    assert payload_input_hash(["a,b"], ["c"]) != payload_input_hash(["a"], ["b,c"])
