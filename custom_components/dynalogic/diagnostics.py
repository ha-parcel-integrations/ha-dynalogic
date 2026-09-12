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
# This carrier needs a wider net than most: only one populated response has ever
# been seen, and it was a delivered order — the payload an in-transit parcel
# carries (the app renders a driver and map coordinates) is still unknown, so
# those names are listed pre-emptively. Whole blocks are redacted rather than
# their leaves for the same reason: redacting the leaves we happen to know
# would leave the ones we do not.
#
# `async_redact_data` matches keys **case-sensitively and at every depth**, so
# the carrier's PascalCase spelling has to be listed next to our own snake_case
# one. The first real capture proved that matters: `barcode` was redacted while
# `OrderData.OrderLines[].Barcode` — the physical parcel barcode, which on the
# one order seen unredacted is the same value as the order number — went out in
# the clear.
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
    # the recipient's own standing delivery instructions ("do not leave with a
    # neighbour"), which say something about the household
    "TransportConditions",
    # every identifier that resolves back to this one shipment. `Barcode` and
    # `CustomerOrderNumber` are the carrier's own spellings of the parcel
    # number; `OrderId` / `OrderNumber` reach the same order.
    "Barcode",
    "CustomerOrderNumber",
    "OrderId",
    "OrderNumber",
    # the driver and where the van is. `DriverName` and the two driver ids are
    # observed; the position field names are not, and `TransportProgress` is
    # the prime suspect for the delayed live position.
    "Driver",
    "DriverName",
    "DriverId",
    "DriverBadgeNumber",
    "DriverPhoto",
    "TransportProgress",
    "Latitude",
    "Longitude",
    "Position",
    "Coordinates",
    # generic leaves, whatever block they turn up in. The `Addressee` block is
    # already redacted whole; these are its **observed** leaf names (2026-08-06)
    # listed separately so the same leaf is caught in a block we have not seen
    # yet — a proof of delivery, a neighbour's details, a second address.
    "Name",
    "Name1",
    "Name2",
    "Name3",
    "Name4",
    "Company",
    "Street",
    "HouseNumber",
    "HouseNumberAddition",
    "City",
    "PostalCode",
    "Email",
    "EmailAddress",
    "PhoneNumber",
    "Phone1",
    "Phone2",
    "Phone3",
    "Phone4",
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
            "skipped_from_fetch": len(coordinator.delivered_codes),
        },
        "polling": {
            "tier_minutes": coordinator.current_tier_minutes,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "suspended": coordinator.update_interval is None,
        },
        "incoming": async_redact_data(coordinator.data or [], TO_REDACT),
        "delivered": async_redact_data(coordinator.delivered or [], TO_REDACT),
    }
