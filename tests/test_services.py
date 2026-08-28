"""Tests for the Dynalogic services (track_parcel / untrack_parcel)."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynalogic.const import (
    CONF_PARCELS,
    CONF_POSTAL_CODE,
    CONF_TRACKING_CODE,
    DOMAIN,
)

from .payloads import POSTCODE, active_sample

_SAMPLE = active_sample()
CODE = "1234567890"
def _parcel(code: str = CODE) -> dict:
    return {CONF_TRACKING_CODE: code}


async def _setup(hass, parcels: list[dict] | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_PARCELS: parcels or [], CONF_POSTAL_CODE: POSTCODE},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.dynalogic.api.DynalogicApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _call(hass, service: str, data: dict) -> None:
    with patch(
        "custom_components.dynalogic.api.DynalogicApiClient.async_get_parcel",
        new=AsyncMock(return_value=_SAMPLE),
    ):
        await hass.services.async_call(DOMAIN, service, data, blocking=True)
        await hass.async_block_till_done()


async def test_track_parcel_inherits_the_hub_postcode(hass):
    """An automation reacting to a shipping mail has no postcode to offer."""
    entry = await _setup(hass)
    await _call(hass, "track_parcel", {CONF_TRACKING_CODE: CODE})

    assert entry.options[CONF_PARCELS] == [_parcel()]


async def test_track_parcel_validates_an_optional_postcode(hass):
    entry = await _setup(hass)
    await _call(
        hass,
        "track_parcel",
        {CONF_TRACKING_CODE: CODE, CONF_POSTAL_CODE: "3011 aa"},
    )

    assert entry.options[CONF_PARCELS] == [_parcel()]


async def test_track_parcel_normalizes_code(hass):
    entry = await _setup(hass)
    await _call(hass, "track_parcel", {CONF_TRACKING_CODE: "1234-567 890"})

    assert entry.options[CONF_PARCELS] == [_parcel()]


async def test_track_parcel_rejects_invalid_code(hass):
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "track_parcel", {CONF_TRACKING_CODE: "abc"}, blocking=True
        )


async def test_track_parcel_rejects_invalid_postcode(hass):
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "track_parcel",
            {CONF_TRACKING_CODE: CODE, CONF_POSTAL_CODE: "nope"},
            blocking=True,
        )


async def test_track_parcel_does_not_call_the_carrier(hass):
    """Unlike the options flow: a parcel the carrier has not registered *yet*
    must not be lost, so the service validates shape only."""
    await _setup(hass)
    get_parcel = AsyncMock(return_value=None)
    with patch(
        "custom_components.dynalogic.api.DynalogicApiClient.async_get_parcel",
        new=get_parcel,
    ):
        await hass.services.async_call(
            DOMAIN, "track_parcel", {CONF_TRACKING_CODE: CODE}, blocking=True
        )
    get_parcel.assert_not_awaited()


async def test_track_parcel_duplicate_is_noop(hass):
    entry = await _setup(hass)
    for _ in range(2):
        await _call(hass, "track_parcel", {CONF_TRACKING_CODE: CODE})

    assert len(entry.options[CONF_PARCELS]) == 1


async def test_untrack_parcel_removes_from_options(hass):
    entry = await _setup(hass, parcels=[_parcel()])
    await _call(hass, "untrack_parcel", {CONF_TRACKING_CODE: CODE})

    assert entry.options[CONF_PARCELS] == []


async def test_untrack_unknown_code_is_noop(hass):
    entry = await _setup(hass, parcels=[_parcel()])
    await _call(hass, "untrack_parcel", {CONF_TRACKING_CODE: "0000000000"})

    assert len(entry.options[CONF_PARCELS]) == 1
