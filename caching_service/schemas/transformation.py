from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TransformationRecord:
    """A transformer result ready to be cached.

    Attributes:
        input_hash: ``sha256_hex(input_value)``.
        input_value: The original string.
        output_value: The transformer's result for ``input_value``.
    """

    input_hash: str
    input_value: str
    output_value: str
