"""Tests for Dynalogic diagnostics."""
from datetime import timedelta
from unittest.mock import MagicMock

from custom_components.dynalogic.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.dynalogic.parcels import normalize_parcel

from .payloads import ACTIVE_CODE, POSTCODE, active_sample


async def _diagnostics(hass, parcel):
    """Run diagnostics over one normalised parcel."""
    entry = MagicMock()
    entry.options = {
        "parcels": [{"tracking_code": ACTIVE_CODE, "postal_code": POSTCODE}],
        "postal_code": POSTCODE,
    }
    entry.runtime_data.coordinator.data = [parcel]
    entry.runtime_data.coordinator.delivered = []
    entry.runtime_data.coordinator.current_tier_minutes = 15
    entry.runtime_data.coordinator.update_interval = timedelta(minutes=15)
    return await async_get_config_entry_diagnostics(hass, entry)


async def test_diagnostics_redacts_every_identifier_in_a_real_response(hass):
    """The regression the first real capture exposed.

    `barcode` was redacted while `OrderData.OrderLines[].Barcode` — the physical
    parcel barcode, and a *different* value — went out in the clear, together
    with the shipper's own order number and the driver's id. `async_redact_data`
    matches keys case-sensitively, so each carrier spelling has to be listed
    next to ours.
    """
    result = await _diagnostics(hass, normalize_parcel(active_sample()))
    parcel = result["incoming"][0]
    order_data = parcel["raw"]["OrderData"]

    assert parcel["barcode"] == "**REDACTED**"
    assert parcel["sender"] == "**REDACTED**"
    assert parcel["receiver"] == "**REDACTED**"
    assert order_data["OrderLines"][0]["Barcode"] == "**REDACTED**"
    assert order_data["CustomerOrderNumber"] == "**REDACTED**"
    assert order_data["OrderId"] == "**REDACTED**"
    assert order_data["OrderNumber"] == "**REDACTED**"
    assert order_data["DriverName"] == "**REDACTED**"
    assert order_data["DriverId"] == "**REDACTED**"
    assert order_data["Addressee"] == "**REDACTED**"
    # the recipient's own standing delivery instructions
    assert order_data["TransportConditions"] == "**REDACTED**"

    # ...and the fields that make diagnostics worth pasting survive.
    assert parcel["raw"]["Scenario"] == "DEL_DEF"
    assert parcel["raw"]["ActiveStep"] == 3
    assert parcel["raw"]["DetailCaption"] == "Onderweg"
    assert order_data["CustomerName"] == "bol."
    assert order_data["OrderTypeDescription"] == "Bezorging"
    assert order_data["Activities"][0]["Description"]


async def test_diagnostics_surfaces_polling_state(hass):
    """The tier and interval last computed by the coordinator, for support reports."""
    result = await _diagnostics(hass, normalize_parcel(active_sample()))
    assert result["polling"] == {
        "tier_minutes": 15,
        "update_interval_seconds": 900.0,
        "suspended": False,
    }


async def test_diagnostics_reports_suspended_polling(hass):
    """``update_interval is None`` (full stop) must be visible, not just absent."""
    entry = MagicMock()
    entry.options = {
        "parcels": [{"tracking_code": ACTIVE_CODE, "postal_code": POSTCODE}],
        "postal_code": POSTCODE,
    }
    entry.runtime_data.coordinator.data = []
    entry.runtime_data.coordinator.delivered = []
    entry.runtime_data.coordinator.current_tier_minutes = None
    entry.runtime_data.coordinator.update_interval = None

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["polling"] == {
        "tier_minutes": None,
        "update_interval_seconds": None,
        "suspended": True,
    }


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    entry = MagicMock()
    entry.options = {
        "parcels": [{"tracking_code": ACTIVE_CODE, "postal_code": POSTCODE}],
        "postal_code": POSTCODE,
    }
    entry.runtime_data.coordinator.current_tier_minutes = None
    entry.runtime_data.coordinator.update_interval = None
    entry.runtime_data.coordinator.data = [
        {
            "barcode": ACTIVE_CODE,
            "status": "out_for_delivery",
            "raw_status": "DEL_DEF/3/27",
            "raw": {
                "TrackAndTraceNumber": ACTIVE_CODE,
                "Scenario": "DEL_DEF",
                "OrderData": {
                    "Addressee": {
                        "Name": "Jane Doe",
                        "Street": "Coolsingel",
                        "PostalCode": "3011AD",
                    }
                },
                "ContactInformation": {"contact_email_address": "info@example.test"},
            },
        }
    ]
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["counts"] == {"incoming_active": 1, "delivered": 0}
    # order numbers and postcodes are redacted at every nesting level
    options_parcel = result["entry_options"]["parcels"][0]
    assert options_parcel["tracking_code"] == "**REDACTED**"
    assert options_parcel["postal_code"] == "**REDACTED**"
    assert result["entry_options"]["postal_code"] == "**REDACTED**"
    assert result["incoming"][0]["barcode"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["TrackAndTraceNumber"] == "**REDACTED**"
    # the addressee goes as a whole block: its unrecovered leaves are exactly
    # the ones a per-leaf list would miss
    assert result["incoming"][0]["raw"]["OrderData"]["Addressee"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["ContactInformation"] == "**REDACTED**"
    # non-identifying fields survive, or the diagnostics would be useless
    assert result["incoming"][0]["status"] == "out_for_delivery"
    assert result["incoming"][0]["raw"]["Scenario"] == "DEL_DEF"
