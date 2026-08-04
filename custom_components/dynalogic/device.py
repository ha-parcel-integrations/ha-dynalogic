"""The device every entity of this integration belongs to.

One place, because sensors, the button and the calendar must all land on the
*same* device entry — and because the account-based variant only has to change
this file to name devices per account.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, TRACKING_SITE_URL

# The consumer tracking site. Not a per-parcel link — Dynalogic's own tracking
# links carry an encrypted token we cannot construct — so it lands on the page
# where an order number can be typed in.
CONFIGURATION_URL = TRACKING_SITE_URL

ATTRIBUTION = "Data provided by Dynalogic"


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the DeviceInfo shared by every entity of this hub."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Dynalogic",
        manufacturer="Dynalogic",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=CONFIGURATION_URL,
    )
