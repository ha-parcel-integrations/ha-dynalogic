"""Diagnostics support for the Dynalogic parcel tracker integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import DynalogicConfigEntry

# Diagnostics are pasted into public issues, so redact anything that
# identifies a person, an address or a specific parcel. Over-redacting is
# cheap; under-redacting leaks a user's home address into a GitHub thread.
#
# This carrier needs a wider net than most: no populated response has ever been
# seen, so the payload's leaf names are not fully known — and the app's own
# assets prove it carries a driver and map coordinates that no recovered field
# accounts for. `Addressee` is redacted as a whole block for that reason:
# redacting the leaves we happen to know would leave the ones we do not.
TO_REDACT = {
    # canonical fields we publish ourselves
    "tracking_code",
    "barcode",
    "sender",
    "receiver",
    "url",
    "postal_code",
    # carrier payload — the recipient block, whole
    "Addressee",
    "TrackAndTraceNumber",
    # per-order contact block: phone numbers and mail addresses
    "ContactInformation",
    # the driver and where the van is; names unconfirmed, listed pre-emptively
    "Driver",
    "DriverName",
    "DriverPhoto",
    "Latitude",
    "Longitude",
    "Position",
    "Coordinates",
    # generic leaves, whatever block they turn up in
    "Name",
    "Street",
    "HouseNumber",
    "City",
    "PostalCode",
    "Email",
    "PhoneNumber",
    "Signature",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DynalogicConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the Dynalogic config entry."""
    coordinator = entry.runtime_data.coordinator

    return {
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "counts": {
            "incoming_active": len(coordinator.data or []),
            "delivered": len(coordinator.delivered or []),
        },
        "incoming": async_redact_data(coordinator.data or [], TO_REDACT),
        "delivered": async_redact_data(coordinator.delivered or [], TO_REDACT),
    }
