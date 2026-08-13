"""Tests for the Dynalogic config and options flow."""
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
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
    CONF_REFRESH_INTERVAL,
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


def test_valid_tracking_code_is_deliberately_generous():
    """Dynalogic publishes no order-number format and validates none itself."""
    assert valid_tracking_code("1234567890")
    assert valid_tracking_code("ABC12345")
    assert not valid_tracking_code("ABC")  # too short
    assert not valid_tracking_code("A" * 31)  # too long


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
    interval="30",
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
        "polling": {CONF_REFRESH_INTERVAL: interval},
    }


async def test_options_add_parcel_inherits_the_hub_postcode(hass):
    entry = _hub([])
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with _patch_lookup() as get_parcel:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _init_input(add="1234567890")
        )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [_parcel("1234567890")]
    get_parcel.assert_awaited_once_with("1234567890", POSTCODE)


async def test_options_add_parcel_with_its_own_postcode(hass):
    """A parcel to another address overrides the hub's postcode."""
    entry = _hub([])
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with _patch_lookup():
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _init_input(add="1234567890", postcode="3011 aa")
        )
    assert result["data"][CONF_PARCELS] == [_parcel("1234567890", OTHER_POSTCODE)]


async def test_options_add_code_with_separators(hass):
    """Pasted codes with spaces/dashes are sanitised like the consumer site."""
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with _patch_lookup():
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _init_input(add="1234-567 890")
        )
    assert result["data"][CONF_PARCELS] == [_parcel("1234567890")]


@pytest.mark.parametrize(
    "add,postcode,expected",
    [
        ("abc", "", "invalid_tracking_code"),
        ("1234567890", "nope", "invalid_postcode"),
    ],
)
async def test_options_add_rejects_bad_input_without_calling_the_api(
    hass, add, postcode, expected
):
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with _patch_lookup() as get_parcel:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _init_input(add=add, postcode=postcode)
        )
    assert result["errors"]["base"] == expected
    get_parcel.assert_not_awaited()


async def test_options_add_rejects_a_pair_the_carrier_does_not_know(hass):
    """The one request adding a parcel costs: a wrong postcode is otherwise
    invisible until the parcel never arrives."""
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with _patch_lookup(result=None):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _init_input(add="1234567890")
        )
    assert result["errors"]["base"] == "parcel_not_found"


@pytest.mark.parametrize(
    "error", [DynalogicApiError("boom"), aiohttp.ClientError("offline")]
)
async def test_options_add_reports_an_unreachable_carrier(hass, error):
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with _patch_lookup(error=error):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _init_input(add="1234567890")
        )
    assert result["errors"]["base"] == "cannot_connect"


async def test_options_add_duplicate_rejected(hass):
    entry = _hub([_parcel("1111111111")])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with _patch_lookup() as get_parcel:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _init_input(add="1111111111", remove=[])
        )
    assert result["errors"]["base"] == "already_tracked"
    get_parcel.assert_not_awaited()


async def test_options_remove_parcel(hass):
    entry = _hub([_parcel("1111111111"), _parcel("2222222222")])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _init_input(remove=["1111111111"])
    )
    assert result["type"] == "create_entry"
    codes = {p[CONF_TRACKING_CODE] for p in result["data"][CONF_PARCELS]}
    assert codes == {"2222222222"}


async def test_options_remove_then_readd_same_code(hass):
    """Remove-then-add order: re-adding a just-removed code works."""
    entry = _hub([_parcel("1111111111")])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with _patch_lookup():
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            _init_input(add="1111111111", remove=["1111111111"]),
        )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [_parcel("1111111111")]


async def test_options_keeps_the_hub_postcode(hass):
    """The hub's own postcode survives an options submission untouched."""
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _init_input()
    )
    assert result["data"][CONF_POSTAL_CODE] == POSTCODE


async def test_options_changes_interval_history_and_delivered(hass):
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _init_input(
            interval="120",
            history=True, filter_type="parcels", amount=5,
        ),
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_REFRESH_INTERVAL] == 120
    assert result["data"][CONF_INCLUDE_HISTORY] is True
    assert result["data"][CONF_DELIVERED_FILTER_TYPE] == "parcels"
    assert result["data"][CONF_DELIVERED_FILTER_AMOUNT] == 5
