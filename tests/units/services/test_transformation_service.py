from prometheus_client import REGISTRY

from caching_service.schemas.transformation import TransformationRecord
from caching_service.services.transformation_service import TransformationService
from caching_service.utils.hashing import sha256_hex
from tests.fakes import CountingTransformerClient, InMemoryTransformationRepository


async def test_cold_cache_calls_the_transformer_once_per_value() -> None:
    transformer = CountingTransformerClient()
    service = TransformationService(InMemoryTransformationRepository(), transformer)

    outputs = await service.transform_all(["a", "b"])

    assert outputs == {"a": "A", "b": "B"}
    assert transformer.calls == ["a", "b"]


async def test_duplicates_within_one_call_are_transformed_once() -> None:
    transformer = CountingTransformerClient()
    service = TransformationService(InMemoryTransformationRepository(), transformer)

    outputs = await service.transform_all(["a", "a", "a", "b"])

    assert outputs == {"a": "A", "b": "B"}
    assert transformer.calls == ["a", "b"]


async def test_cached_values_are_not_sent_to_the_transformer() -> None:
    transformer = CountingTransformerClient()
    repository = InMemoryTransformationRepository({sha256_hex("a"): "A"})
    service = TransformationService(repository, transformer)

    outputs = await service.transform_all(["a", "x"])

    assert outputs == {"a": "A", "x": "X"}
    assert transformer.calls == ["x"]


async def test_cached_empty_string_counts_as_a_hit() -> None:
    transformer = CountingTransformerClient()
    repository = InMemoryTransformationRepository({sha256_hex(""): ""})
    service = TransformationService(repository, transformer)

    outputs = await service.transform_all([""])

    assert outputs == {"": ""}
    assert transformer.calls == []


async def test_only_misses_are_saved_with_their_hashes() -> None:
    repository = InMemoryTransformationRepository({sha256_hex("a"): "A"})
    service = TransformationService(repository, CountingTransformerClient())

    await service.transform_all(["a", "x"])

    assert repository.saved == [TransformationRecord(input_hash=sha256_hex("x"), input_value="x", output_value="X")]


def _transformer_calls_metric() -> float:
    return REGISTRY.get_sample_value("transformer_calls_total") or 0.0


async def test_every_transformer_call_increments_the_metric() -> None:
    repository = InMemoryTransformationRepository({sha256_hex("a"): "A"})
    service = TransformationService(repository, CountingTransformerClient())
    before = _transformer_calls_metric()

    await service.transform_all(["a", "x", "y", "x"])

    assert _transformer_calls_metric() - before == 2
