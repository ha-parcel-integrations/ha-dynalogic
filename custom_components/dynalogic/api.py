"""Dynalogic public tracking API client.

The endpoint is the ``track-middleware`` API the vendor's own app talks to. It
needs **no** authentication: no key, no cookie, no header ritual — its own
OpenAPI document declares no security scheme at all, and a bare request answers.

The contract the coordinator relies on:

* ``async_get_parcel`` returns the raw per-parcel dict on success,
* returns ``None`` when the order number is unknown *or* the postcode does not
  belong to it (both are a plain 404 — a normal, expected state, never an
  error),
* raises :class:`DynalogicApiError` for anything else,
* lets ``aiohttp.ClientError`` propagate untouched — ``DataUpdateCoordinator``
  already wraps those into ``UpdateFailed``.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import TRACKING_API_URL

_LOGGER = logging.getLogger(__name__)


class DynalogicApiError(Exception):
    """Raised when a Dynalogic API call returns an unexpected response."""

    def __init__(self, detail: str) -> None:
        """Store the detail that triggered the error."""
        super().__init__(f"Dynalogic API request failed: {detail}")
        self.detail = detail


class DynalogicApiClient:
    """Client for the keyless Dynalogic tracking middleware.

    Two routes, one resource. ``full`` takes the order number *and* the
    postcode and is the only one that returns ``OrderData`` (the activity
    history and the addressee); ``partial`` takes the order number alone and
    returns progress only. The postcode is an authorization second factor, not
    a lookup key — the same order resolves either way, the caller just proves it
    may see the personal data.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def _async_get(self, url: str, what: str) -> dict[str, Any] | None:
        """GET ``url``, returning the JSON object, or ``None`` on a 404."""
        async with self._session.get(url) as response:
            if response.status == 404:
                # RFC 9110 problem+json. The upstream service's own problem
                # document is nested inside `detail` as a JSON *string*, so
                # there is nothing worth parsing — the status is the signal.
                return None
            if response.status != 200:
                raise DynalogicApiError(f"HTTP {response.status} for {what}")
            try:
                # content_type=None: keep parsing even if the middleware ever
                # labels a body text/plain, as consumer endpoints often do.
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise DynalogicApiError(f"unparseable body ({err})") from err

        if not isinstance(payload, dict):
            raise DynalogicApiError("unexpected body (not a JSON object)")
        return payload

    async def async_get_parcel(
        self, ordernumber: str, postal_code: str
    ) -> dict[str, Any] | None:
        """Fetch one parcel's full tracking details.

        Returns the transport order for a known parcel, or ``None`` when the
        middleware 404s — which covers an unknown order number, a postcode that
        does not belong to it, and an order that has not been created yet.
        """
        url = TRACKING_API_URL.format(
            ordernumber=ordernumber,
            # The vendor's own client lower-cases the postcode; the server does
            # not appear to care, but there is no reason to differ from it.
            zipcode=postal_code.lower(),
        )
        return await self._async_get(url, f"order {ordernumber}")

    # Deliberately not implemented: the postcode-free `partial` route.
    #
    # It would let the config flow tell "no such order number" (partial 404s
    # too) from "wrong postcode for this order" (partial answers, full 404s),
    # turning one generic error into two actionable ones for one extra request
    # at setup. That truth table is read off the route semantics and has never
    # been exercised against a real order number — every probe so far used a
    # bogus one and hit the first row only. Wire it up once a real order has
    # confirmed it; until then one honest error beats two confident guesses.
    # The URL is ready in `const.TRACKING_API_PARTIAL_URL`.
