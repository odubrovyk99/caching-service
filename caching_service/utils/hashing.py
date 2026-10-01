import hashlib
import json
from collections.abc import Sequence


def sha256_hex(value: str) -> str:
    """Hash a string into the fixed-width key used by the cache tables.

    A fixed-width key is used instead of the raw text because a Postgres btree index entry is capped at
    about 2.7 KB, so a unique index on raw text would reject long inputs.

    Args:
        value: Text to hash. Must be encodable as UTF-8.

    Returns:
        The SHA-256 digest as 64 lowercase hex characters.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def payload_input_hash(list_1: Sequence[str], list_2: Sequence[str]) -> str:
    """Compute the identity of a payload request.

    The lists are encoded as a JSON array rather than joined with a separator, so items that contain the
    separator cannot make two different inputs collide. Order matters: reordering changes the output, so
    it must change the identity.

    Args:
        list_1: First input list, in request order.
        list_2: Second input list, in request order.

    Returns:
        The SHA-256 hex digest of the canonical JSON encoding of both lists.
    """
    canonical = json.dumps([list(list_1), list(list_2)], ensure_ascii=False, separators=(",", ":"))
    return sha256_hex(canonical)
