import logging

import pytest

from caching_service.services.payload_service import PayloadService
from caching_service.services.transformation_service import TransformationService
from caching_service.use_cases.create_payload import CreatePayloadUseCase
from caching_service.utils.hashing import payload_input_hash
from tests.fakes import CountingTransformerClient, InMemoryPayloadRepository, InMemoryTransformationRepository
from tests.samples import SAMPLE_OUTPUT, SAMPLE_REQUEST


def _use_case(
    payload_repository: InMemoryPayloadRepository, transformer: CountingTransformerClient
) -> CreatePayloadUseCase:
    return CreatePayloadUseCase(
        payload_service=PayloadService(payload_repository),
        transformation_service=TransformationService(InMemoryTransformationRepository(), transformer),
    )


async def test_new_input_produces_the_sample_output() -> None:
    payload_repository = InMemoryPayloadRepository()
    transformer = CountingTransformerClient()

    result = await _use_case(payload_repository, transformer).execute(
        SAMPLE_REQUEST["list_1"], SAMPLE_REQUEST["list_2"]
    )

    assert result.created is True
    assert payload_repository.outputs_by_id[result.payload_id] == SAMPLE_OUTPUT
    assert len(transformer.calls) == 6


async def test_known_input_takes_the_fast_path_without_transforming() -> None:
    payload_repository = InMemoryPayloadRepository()
    first = await _use_case(payload_repository, CountingTransformerClient()).execute(
        SAMPLE_REQUEST["list_1"], SAMPLE_REQUEST["list_2"]
    )
    # Fresh transformation cache: only the payload fast path can avoid calling the transformer now.
    transformer = CountingTransformerClient()

    second = await _use_case(payload_repository, transformer).execute(
        SAMPLE_REQUEST["list_1"], SAMPLE_REQUEST["list_2"]
    )

    assert second.created is False
    assert second.payload_id == first.payload_id
    assert transformer.calls == []
    assert set(payload_repository.ids_by_hash) == {
        payload_input_hash(SAMPLE_REQUEST["list_1"], SAMPLE_REQUEST["list_2"])
    }


async def test_storing_a_payload_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="caching_service")

    result = await _use_case(InMemoryPayloadRepository(), CountingTransformerClient()).execute(["a"], ["b"])

    assert f"payload_id={result.payload_id} created=True" in caplog.text
