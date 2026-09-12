"""Tests for the Dynalogic config and options flow."""
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import aiohttp
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynalogic.api import DynalogicApiError
from custom_components.dynalogic.config_flow import (
    normalize_postcode,
    normalize_tracking_code,
    valid_postcode,
    valid_tracking_code,
)
from custom_components.dynalogic.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_INCLUDE_HISTORY,
    CONF_PARCELS,
    CONF_POSTAL_CODE,
    CONF_TRACKING_CODE,
    DOMAIN,
)

from .payloads import POSTCODE, active_sample

OTHER_POSTCODE = "3011AA"


@contextmanager
def _patch_lookup(result=..., error: Exception | None = None):
    """Patch the one API call the options flow makes when adding a parcel."""
    get_parcel = AsyncMock(
        return_value=active_sample() if result is ... else result,
        side_effect=error,
    )
    with patch(
        "custom_components.dynalogic.config_flow.DynalogicApiClient"
    ) as client_cls:
        client_cls.return_value.async_get_parcel = get_parcel
        yield get_parcel


# ---------------------------------------------------------------------------
# input sanitising
# ---------------------------------------------------------------------------


def test_normalize_tracking_code_strips_and_uppercases():
    assert normalize_tracking_code("1234 567-890") == "1234567890"
    assert normalize_tracking_code("") == ""
    assert normalize_tracking_code(None) == ""


def test_valid_tracking_code_accepts_any_non_empty_code():
    """Dynalogic publishes no order-number format; only emptiness is rejected."""
    assert valid_tracking_code("1234567890")
    assert valid_tracking_code("ABC12345")
    assert valid_tracking_code("AB")
    assert not valid_tracking_code("")


def test_normalize_and_validate_postcode():
    """NL is 4 digits + 2 letters; BE is the same 4 digits with no letters."""
    assert normalize_postcode(" 1012 ab ") == "1012AB"
    assert valid_postcode("1012AB")  # NL
    assert valid_postcode("1012")  # BE
    assert not valid_postcode("0123AB")  # no NL/BE postcode starts with 0
    assert not valid_postcode("0123")
    assert not valid_postcode("ABCDEF")


# ---------------------------------------------------------------------------
# config flow — the hub
# ---------------------------------------------------------------------------


async def test_user_flow_asks_for_the_postcode(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"


async def test_user_flow_creates_hub_with_the_postcode(hass):
    """Setup does not hit the API — the endpoint needs an order number."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POSTAL_CODE: "1012 ab"}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Dynalogic"
    assert result["options"][CONF_POSTAL_CODE] == POSTCODE
    assert result["options"][CONF_PARCELS] == []


async def test_user_flow_rejects_a_bad_postcode(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POSTAL_CODE: "nope"}
    )
    assert result["type"] == "form"
    assert result["errors"][CONF_POSTAL_CODE] == "invalid_postcode"


async def test_second_hub_rejected(hass):
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "abort"
    # single_config_entry in the manifest aborts before the flow runs.
    assert result["reason"] == "single_instance_allowed"


# ---------------------------------------------------------------------------
# options flow — tracked parcels
# ---------------------------------------------------------------------------


def _hub(parcels: list[dict]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_PARCELS: parcels, CONF_POSTAL_CODE: POSTCODE},
    )


def _parcel(code: str, postcode: str = POSTCODE) -> dict:
    return {CONF_TRACKING_CODE: code, CONF_POSTAL_CODE: postcode}


def _init_input(
    *, add="", postcode="", remove=None, history=False,
    filter_type="days", amount=7,
) -> dict:
    """Build the sectioned options-form submission."""
    parcels: dict = {"add": add, CONF_POSTAL_CODE: postcode}
    if remove is not None:
        parcels["remove"] = remove
    return {
        "parcels": parcels,
        "delivered": {
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        "history": {CONF_INCLUDE_HISTORY: history},
    }


async def _open_options_step(hass, entry, step_id: str):
    """Start the options flow and select one of its two top-level routes."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    assert result["menu_options"] == ["parcels", "settings"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step_id}
    )


async def test_options_parcel_list_can_be_cleared(hass):
    """A submitted empty list removes the final manually tracked parcel."""
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_PARCELS: [{CONF_TRACKING_CODE: "EXAMPLE111111"}], CONF_POSTAL_CODE: "1234AB"})
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": []}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == []


async def test_options_settings_preserve_parcel_list(hass):
    """Saving settings must never replace the manually tracked parcel list."""
    parcels = [{CONF_TRACKING_CODE: "EXAMPLE111111"}]
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_PARCELS: parcels, CONF_POSTAL_CODE: "1234AB"})
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "settings")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DELIVERED_FILTER_TYPE: "days", CONF_DELIVERED_FILTER_AMOUNT: 7, CONF_INCLUDE_HISTORY: False}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == parcels


async def test_options_add_parcel_rejects_an_invalid_hub_postcode(hass):
    """A stored hub postcode that is no longer valid blocks adding a parcel."""
    entry = MockConfigEntry(
        domain=DOMAIN, options={CONF_PARCELS: [], CONF_POSTAL_CODE: "nope"}
    )
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    with _patch_lookup() as get_parcel:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"tracking_codes": ["EXAMPLE111111"]}
        )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_postcode"
    get_parcel.assert_not_called()


async def test_options_add_parcel_reports_a_transport_error(hass):
    """A connection failure while verifying a new code surfaces as cannot_connect."""
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    with _patch_lookup(error=aiohttp.ClientError()) as get_parcel:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"tracking_codes": ["EXAMPLE111111"]}
        )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"
    get_parcel.assert_called_once()


async def test_options_add_parcel_reports_an_unknown_order(hass):
    """A carrier 404 (unknown order number or wrong postcode) blocks the add."""
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    with _patch_lookup(result=None) as get_parcel:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"tracking_codes": ["EXAMPLE111111"]}
        )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "parcel_not_found"
    get_parcel.assert_called_once()


async def test_options_add_parcel_accepts_a_verified_code(hass):
    """A code that resolves against the API is added to the tracked list."""
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    with _patch_lookup() as get_parcel:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"tracking_codes": ["EXAMPLE111111"]}
        )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [{CONF_TRACKING_CODE: "EXAMPLE111111"}]
    get_parcel.assert_called_once()


async def test_async_parcel_error_reports_cannot_connect_on_api_error(hass):
    """DynalogicApiError from the client is treated the same as a transport error."""
    with _patch_lookup(error=DynalogicApiError("boom")):
        from custom_components.dynalogic.config_flow import async_parcel_error

        assert await async_parcel_error(hass, "EXAMPLE111111", POSTCODE) == "cannot_connect"
