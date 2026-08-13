"""Config flow for the Dynalogic parcel tracker integration."""
from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DynalogicApiClient, DynalogicApiError
from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_INCLUDE_HISTORY,
    CONF_PARCELS,
    CONF_POSTAL_CODE,
    CONF_REFRESH_INTERVAL,
    CONF_TRACKING_CODE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    DEFAULT_INCLUDE_HISTORY,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    POSTCODE_RE,
    REFRESH_INTERVAL_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

# The order number as printed on the shipping confirmation or the tracking
# mail. Deliberately generous: Dynalogic publishes no format, neither of its
# own clients validates one, and a 10-digit and an alphanumeric probe were
# treated identically by the API. A false negative here — rejecting a code that
# would have worked — is far worse than accepting a bad one, which simply comes
# back "not found". Narrow it once real order numbers show a shape.
_TRACKING_CODE_RE = re.compile(r"^[A-Z0-9]{4,30}$")
_POSTCODE_RE = re.compile(POSTCODE_RE)


def normalize_tracking_code(value: str) -> str:
    """Return the order number upper-cased with separators stripped.

    Mirrors what a consumer site's own sanitiser does (uppercase, drop
    everything that is not ``A-Z0-9``), so codes pasted with spaces or dashes
    still work.
    """
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())


def valid_tracking_code(value: str) -> bool:
    """Whether ``value`` looks like a Dynalogic order number."""
    return bool(_TRACKING_CODE_RE.match(value))


def normalize_postcode(value: str) -> str:
    """Return the postcode without spaces and upper-cased (``1234AB``)."""
    return re.sub(r"\s+", "", (value or "")).upper()


def valid_postcode(value: str) -> bool:
    """Whether ``value`` is a Dutch or Belgian postcode.

    Dynalogic delivers in the Netherlands and Belgium; the API itself
    validates nothing (it only checks the postcode against the order it
    belongs to), so this is our own guard against a typo becoming a parcel
    that silently never resolves.
    """
    return bool(_POSTCODE_RE.match(value))


def _current_parcels(entry: ConfigEntry) -> list[dict[str, str]]:
    """Return a mutable copy of the tracked parcels list."""
    return [dict(item) for item in entry.options.get(CONF_PARCELS, [])]


async def async_parcel_error(
    hass, tracking_code: str, postal_code: str
) -> str | None:
    """Check a code/postcode pair against the carrier; return an error key.

    Adding a parcel costs one request, and it is worth it: a wrong postcode is
    otherwise invisible — the parcel is accepted, never resolves, and sits at
    ``unknown`` forever with nothing to say why.

    ``None`` means the pair resolves. ``parcel_not_found`` covers both an
    unknown order number and a postcode that does not belong to it: the carrier
    answers the same bare 404 either way, and telling the two apart needs a
    second route whose behaviour no real order has confirmed yet.
    ``cannot_connect`` means we could not ask.
    """
    client = DynalogicApiClient(async_get_clientsession(hass))
    try:
        parcel = await client.async_get_parcel(tracking_code, postal_code)
    except (DynalogicApiError, aiohttp.ClientError) as err:
        _LOGGER.warning("Could not verify Dynalogic parcel %s: %s", tracking_code, err)
        return "cannot_connect"
    return None if parcel is not None else "parcel_not_found"


def _interval_selector() -> selector.SelectSelector:
    """Return the refresh-interval dropdown selector (options translated via strings)."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[str(m) for m in REFRESH_INTERVAL_OPTIONS],
            translation_key=CONF_REFRESH_INTERVAL,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


class DynalogicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI-driven configuration flow for the Dynalogic integration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> DynalogicOptionsFlowHandler:
        """Return the options flow handler."""
        return DynalogicOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the Dynalogic hub, asking only for the delivery postcode.

        Every lookup needs an order number **and** the delivery postcode, so
        the postcode is asked once here and becomes the default for every
        parcel added afterwards — a parcel to a different address can override
        it when it is added. Setup does not hit the API: the endpoint needs an
        order number, and there is none yet.

        One hub is enough (``single_config_entry`` in the manifest enforces
        it): the postcode is per parcel, not per hub, so a second entry would
        buy nothing.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            postal_code = normalize_postcode(user_input[CONF_POSTAL_CODE])
            if not valid_postcode(postal_code):
                errors[CONF_POSTAL_CODE] = "invalid_postcode"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Dynalogic",
                    data={},
                    options={
                        CONF_PARCELS: [],
                        CONF_POSTAL_CODE: postal_code,
                        CONF_DELIVERED_FILTER_TYPE: DEFAULT_DELIVERED_FILTER_TYPE,
                        CONF_DELIVERED_FILTER_AMOUNT: DEFAULT_DELIVERED_FILTER_AMOUNT,
                        CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
                        CONF_INCLUDE_HISTORY: DEFAULT_INCLUDE_HISTORY,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_POSTAL_CODE): str}),
            errors=errors,
        )


class DynalogicOptionsFlowHandler(OptionsFlow):
    """Manage tracked parcels, history and polling in one sectioned form.

    Mirrors the other suite carriers' section layout (here: ``parcels`` /
    ``delivered`` / ``history`` / ``polling``). Adding a parcel needs only its
    order number — the postcode is inherited from the hub unless the parcel
    goes to a different address, in which case the second field takes it.
    Changes apply live via HA's options-update listener (which refreshes the
    coordinator), so new/removed per-parcel sensors appear and disappear
    immediately.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and handle the single sectioned options form."""
        errors: dict[str, str] = {}
        parcels = _current_parcels(self.config_entry)
        hub_postcode = self.config_entry.options.get(CONF_POSTAL_CODE, "")

        if user_input is not None:
            parcels_section = user_input.get("parcels", {})
            delivered_section = user_input.get("delivered", {})
            history_section = user_input.get("history", {})
            polling_section = user_input.get("polling", {})

            # Remove first, then add — so re-adding a just-removed code works.
            to_remove = set(parcels_section.get("remove", []))
            parcels = [p for p in parcels if p[CONF_TRACKING_CODE] not in to_remove]

            add_code = normalize_tracking_code(parcels_section.get("add") or "")
            add_postcode = (
                normalize_postcode(parcels_section.get(CONF_POSTAL_CODE) or "")
                or hub_postcode
            )
            if add_code:
                if not valid_tracking_code(add_code):
                    errors["base"] = "invalid_tracking_code"
                elif not valid_postcode(add_postcode):
                    errors["base"] = "invalid_postcode"
                elif any(p[CONF_TRACKING_CODE] == add_code for p in parcels):
                    errors["base"] = "already_tracked"
                elif error := await async_parcel_error(
                    self.hass, add_code, add_postcode
                ):
                    errors["base"] = error
                else:
                    parcels.append(
                        {
                            CONF_TRACKING_CODE: add_code,
                            CONF_POSTAL_CODE: add_postcode,
                        }
                    )

            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_POSTAL_CODE: hub_postcode,
                        CONF_PARCELS: parcels,
                        CONF_DELIVERED_FILTER_TYPE: delivered_section[
                            CONF_DELIVERED_FILTER_TYPE
                        ],
                        CONF_DELIVERED_FILTER_AMOUNT: int(
                            delivered_section[CONF_DELIVERED_FILTER_AMOUNT]
                        ),
                        CONF_INCLUDE_HISTORY: bool(
                            history_section[CONF_INCLUDE_HISTORY]
                        ),
                        CONF_REFRESH_INTERVAL: int(
                            polling_section[CONF_REFRESH_INTERVAL]
                        ),
                    },
                )

        current = self.config_entry.options

        parcels_fields: dict[Any, Any] = {
            vol.Optional("add", default=""): str,
            vol.Optional(CONF_POSTAL_CODE, default=""): str,
        }
        if parcels:
            parcels_fields[vol.Optional("remove", default=[])] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=p[CONF_TRACKING_CODE],
                            label=(
                                f"{p[CONF_TRACKING_CODE]} "
                                f"({p.get(CONF_POSTAL_CODE, '')})"
                            ),
                        )
                        for p in parcels
                    ],
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )

        schema = vol.Schema(
            {
                vol.Required("parcels"): section(
                    vol.Schema(parcels_fields), {"collapsed": False}
                ),
                vol.Required("delivered"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_DELIVERED_FILTER_TYPE,
                                default=current.get(
                                    CONF_DELIVERED_FILTER_TYPE,
                                    DEFAULT_DELIVERED_FILTER_TYPE,
                                ),
                            ): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=["days", "parcels"],
                                    translation_key=CONF_DELIVERED_FILTER_TYPE,
                                    mode=selector.SelectSelectorMode.LIST,
                                )
                            ),
                            vol.Required(
                                CONF_DELIVERED_FILTER_AMOUNT,
                                default=current.get(
                                    CONF_DELIVERED_FILTER_AMOUNT,
                                    DEFAULT_DELIVERED_FILTER_AMOUNT,
                                ),
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=1, max=365, step=1, mode=selector.NumberSelectorMode.BOX
                                )
                            ),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required("history"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_INCLUDE_HISTORY,
                                default=current.get(
                                    CONF_INCLUDE_HISTORY, DEFAULT_INCLUDE_HISTORY
                                ),
                            ): selector.BooleanSelector(),
                        }
                    ),
                    {"collapsed": True},
                ),
                vol.Required("polling"): section(
                    vol.Schema(
                        {
                            vol.Required(
                                CONF_REFRESH_INTERVAL,
                                # str(): selector option values are strings, so a
                                # stored int default trips "expected str" on submit.
                                default=str(
                                    current.get(
                                        CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                                    )
                                ),
                            ): _interval_selector(),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
