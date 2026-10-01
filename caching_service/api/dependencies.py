from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from caching_service.clients.transformer_client import TransformerClient
from caching_service.db.repositories.payload_repository import PayloadRepository
from caching_service.db.repositories.transformation_repository import TransformationRepository
from caching_service.services.payload_service import PayloadService
from caching_service.services.transformation_service import TransformationService
from caching_service.use_cases.create_payload import CreatePayloadUseCase
from caching_service.use_cases.get_payload import GetPayloadUseCase


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """Return the session factory created in ``lifespan``.

    Args:
        request: Current request.

    Returns:
        The process-wide session factory.
    """
    return cast(async_sessionmaker[AsyncSession], request.state.session_factory)


def get_transformer(request: Request) -> TransformerClient:
    """Return the transformer created in ``lifespan``.

    Args:
        request: Current request.

    Returns:
        The process-wide transformer client.
    """
    return cast(TransformerClient, request.state.transformer)


async def get_session(
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    """Open one session per request, commit on success, roll back on any error.

    Args:
        session_factory: Factory from ``lifespan``.

    Yields:
        The request's session.
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# scope="function" runs the commit above before the response is sent. With FastAPI's default
# ("request"), the client would already hold its 201 when the commit runs: commit failures would be
# invisible, and a quick GET could miss the row it was just told exists.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
TransformerDep = Annotated[TransformerClient, Depends(get_transformer)]


def get_create_payload_use_case(session: SessionDep, transformer: TransformerDep) -> CreatePayloadUseCase:
    """Assemble the create-payload use case for one request.

    Args:
        session: The request's session.
        transformer: The process-wide transformer.

    Returns:
        A use case bound to this request's session.
    """
    return CreatePayloadUseCase(
        payload_service=PayloadService(PayloadRepository(session)),
        transformation_service=TransformationService(TransformationRepository(session), transformer),
    )


def get_get_payload_use_case(session: SessionDep) -> GetPayloadUseCase:
    """Assemble the get-payload use case for one request.

    Args:
        session: The request's session.

    Returns:
        A use case bound to this request's session.
    """
    return GetPayloadUseCase(payload_service=PayloadService(PayloadRepository(session)))
