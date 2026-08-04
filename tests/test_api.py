"""Tests for the Dynalogic API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.dynalogic.api import (
    DynalogicApiClient,
    DynalogicApiError,
)

from .payloads import ACTIVE_CODE, POSTCODE, active_sample


def _session_returning(status: int, body: object = None) -> MagicMock:
    response = AsyncMock()
    response.status = status
    if isinstance(body, str):
        response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        response.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


async def test_get_parcel_returns_the_transport_order():
    session = _session_returning(200, active_sample())
    client = DynalogicApiClient(session)

    parcel = await client.async_get_parcel(ACTIVE_CODE, POSTCODE)

    assert parcel["TrackAndTraceNumber"] == ACTIVE_CODE


async def test_get_parcel_sends_no_headers_and_lowercases_the_postcode():
    """The middleware needs nothing; its own client lower-cases the postcode."""
    session = _session_returning(200, active_sample())
    client = DynalogicApiClient(session)

    await client.async_get_parcel(ACTIVE_CODE, POSTCODE)

    url = session.get.call_args[0][0]
    assert url == (
        "https://api.dynagroup.nl/track-middleware/v1/transportorder/full"
        f"/ordernumber/{ACTIVE_CODE}/zipcode/{POSTCODE.lower()}"
    )
    assert session.get.call_args.kwargs == {}


async def test_get_parcel_returns_none_on_404():
    """Unknown order number, wrong postcode and not-yet-created all 404."""
    client = DynalogicApiClient(_session_returning(404, {"title": "Not Found"}))
    assert await client.async_get_parcel("0000000000", POSTCODE) is None


async def test_get_parcel_raises_on_server_error():
    client = DynalogicApiClient(_session_returning(500, {}))
    with pytest.raises(DynalogicApiError):
        await client.async_get_parcel(ACTIVE_CODE, POSTCODE)


async def test_get_parcel_raises_on_unparseable_body():
    client = DynalogicApiClient(_session_returning(200, "not json"))
    with pytest.raises(DynalogicApiError):
        await client.async_get_parcel(ACTIVE_CODE, POSTCODE)


async def test_get_parcel_raises_on_non_object_body():
    client = DynalogicApiClient(_session_returning(200, ["not", "a", "dict"]))
    with pytest.raises(DynalogicApiError):
        await client.async_get_parcel(ACTIVE_CODE, POSTCODE)


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = DynalogicApiClient(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(ACTIVE_CODE, POSTCODE)
