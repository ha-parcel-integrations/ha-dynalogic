"""Tests for Dynalogic diagnostics."""
from unittest.mock import MagicMock

from custom_components.dynalogic.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .payloads import ACTIVE_CODE, POSTCODE


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    entry = MagicMock()
    entry.options = {
        "parcels": [{"tracking_code": ACTIVE_CODE, "postal_code": POSTCODE}],
        "postal_code": POSTCODE,
    }
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
