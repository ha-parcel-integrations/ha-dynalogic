"""Constants for the Dynalogic parcel tracker integration."""
from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "dynalogic"


class ParcelStatus(StrEnum):
    """Carrier-agnostic parcel status.

    **Do not extend or rename these members.** Every integration in the parcel
    suite publishes exactly this vocabulary on the ``status`` field of each
    normalised parcel, so cross-carrier automations and the aggregator can
    target ``status: out_for_delivery`` regardless of carrier. Listed in
    roughly the order a parcel moves through.
    """

    REGISTERED = "registered"               # Sender announced the parcel; not handed over yet
    IN_TRANSIT = "in_transit"               # In the carrier's network
    OUT_FOR_DELIVERY = "out_for_delivery"   # On a delivery vehicle today
    AT_PICKUP_POINT = "at_pickup_point"     # Ready to collect at a pickup location
    DELIVERED = "delivered"                 # Handed over
    RETURNING = "returning"                 # Failed delivery, going back to sender
    PROBLEM = "problem"                     # Carrier reports an exception/issue
    UNKNOWN = "unknown"                     # Raw status we have not mapped yet


PLATFORMS = [Platform.BUTTON, Platform.CALENDAR, Platform.SENSOR]

# The two endpoints the integration talks to. Both live on the *app*
# middleware, not on the website's `/api` mirror: the middleware is versioned,
# needs no headers at all, and is what the vendor's own app calls. The website
# mirror answers 403 to everything unless an `X-Requested-With` header and a
# same-host `Referer` are both present — a same-origin guard, not a credential,
# but a needless dependency for us.
#
# No authentication of any kind. Errors are RFC 9110 `application/problem+json`;
# an unknown order number (or a postcode that does not belong to it) is a plain
# 404, so branch on the HTTP status and not on the body. Rate limiting is
# **unknown** — nothing was observed, but only a few dozen probe requests ever
# ran, which is why the poll interval stays user-visible and gentle.
#
# `full` needs the postcode and is the one the coordinator polls: it is the only
# route that returns `OrderData` (activity history + addressee), and without it
# a parcel is a status enum and nothing else. `partial` needs no postcode and
# returns progress only; it is kept for the config flow, where it can separate
# "unknown order number" from "wrong postcode for this order".
#
# Full write-up in this carrier's directory under the private
# `carrier-research/api/` — endpoints, the postcode's role, the status
# vocabularies and the (unconfirmed) payload shape.
API_BASE_URL = "https://api.dynagroup.nl/track-middleware/v1"
TRACKING_API_URL = (
    f"{API_BASE_URL}/transportorder/full/ordernumber/{{ordernumber}}"
    "/zipcode/{zipcode}"
)
TRACKING_API_PARTIAL_URL = (
    f"{API_BASE_URL}/transportorder/partial/ordernumber/{{ordernumber}}"
)

# The consumer tracking site. Used as the device's configuration URL only —
# there is deliberately **no** per-parcel deep link (see `normalize_parcel`):
# the links Dynalogic e-mails out carry a server-side AES-encrypted token we
# cannot construct, and no order-number query format is known.
TRACKING_SITE_URL = "https://track.mydynalogic.eu"

# Tracked parcels live in the config entry options as a list of
# ``{tracking_code, postal_code}`` dicts — this carrier has no account or parcel
# feed, so the user enters the codes themselves, and the postcode is the second
# factor that unlocks the parcel's history and addressee. Kept as dicts so
# future per-parcel fields slot in without an options migration.
CONF_PARCELS = "parcels"
CONF_TRACKING_CODE = "tracking_code"
CONF_POSTAL_CODE = "postal_code"

# Dutch postcode: four digits, two letters. Stored normalised (no space, upper
# case) and lower-cased on the wire, which is what the vendor's own client does.
POSTCODE_RE = r"^[1-9][0-9]{3}[A-Z]{2}$"

# Dynalogic carries its status on three fields at once, and none of them alone
# is a parcel status:
#
# * ``Scenario``   — *which kind of job* this is (delivery, pickup, swap, …),
#   13 closed values, each ending in ``_DEF`` (default course) or ``_FAIL``;
# * ``ActiveStep`` — 1–4, the position within that scenario;
# * ``TransportResultCode`` — an integer, 16 known values, of which only ``0``
#   has a known meaning: the vendor's own client calls it the completed state.
#
# All three key domains below are **complete** — they were read off the client's
# FAQ mapper, which has to name every value the backend can emit. What is *not*
# known is what the other 15 result codes mean individually, so the mapping in
# ``parcels.py`` leans on ``ActiveStep`` and treats a non-zero code as "not
# finished yet". A value outside these sets is a genuine surprise and warns once.
KNOWN_RESULT_CODES = frozenset(
    {0, 1, 3, 9, 11, 14, 22, 25, 27, 32, 52, 73, 76, 78, 79, 86}
)
COMPLETE_RESULT_CODES = frozenset({0})

KNOWN_SCENARIOS = frozenset(
    {
        "DEL_DEF",   # delivery, default course
        "DEL_NB",    # delivery to a neighbour
        "DEL_FAIL",  # delivery failed
        "PU_DEF",    # pickup
        "PU_FAIL",
        "SW_DEF",    # swap: deliver the new item, take the old one
        "SW_FAIL",
        "RS_DEF",    # return / retour to the sender
        "RS_FAIL",
        "DP_DEF",    # drop-off
        "DP_FAIL",
        "COR_DEF",   # correction job
        "COR_FAIL",
    }
)
# The prefix expansions above are inference from the FAQ articles each scenario
# points at; the ``_DEF`` / ``_FAIL`` split and the 1–4 step count are certain.
MIN_ACTIVE_STEP = 1
MAX_ACTIVE_STEP = 4

# Payload keys. Named as constants because the payload shape is reconstructed
# from the vendor's web client rather than observed, so every read of a field we
# have never actually seen populated is greppable from one place.
KEY_TRACKING_NUMBER = "TrackAndTraceNumber"
KEY_RESULT_CODE = "TransportResultCode"
KEY_SCENARIO = "Scenario"
KEY_ACTIVE_STEP = "ActiveStep"
KEY_ORDER_DATA = "OrderData"
KEY_ACTIVITIES = "Activities"
KEY_EXECUTED = "ExecutedDateTime"
KEY_ADDRESSEE = "Addressee"
KEY_CONTACT = "ContactInformation"

# Top-level keys we know about. Anything else in a real response is schema
# drift worth hearing about — the reconstruction is known to be *incomplete*
# (the app renders a driver, map pins and a delayed live position that no
# recovered field accounts for), so this set is expected to grow.
KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        KEY_TRACKING_NUMBER,
        KEY_RESULT_CODE,
        KEY_SCENARIO,
        KEY_ACTIVE_STEP,
        KEY_ORDER_DATA,
        KEY_CONTACT,
    }
)

# `ExecutedDateTime` is `YYYYMMDDHHmmss` with no offset anywhere in it, and the
# carrier is a Dutch last-mile operation, so Amsterdam is the assumption. It is
# an *assumption*: the first real parcel must be checked against it, which is
# what the one-shot timestamp warning in `parcels.py` is for.
CARRIER_TIMEZONE = "Europe/Amsterdam"
TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"

# Delivered-parcels retention: keep delivered parcels visible for the last N
# days, or keep only the N most recent — identical across the suite.
CONF_DELIVERED_FILTER_TYPE = "delivered_filter_type"
CONF_DELIVERED_FILTER_AMOUNT = "delivered_filter_amount"
DEFAULT_DELIVERED_FILTER_TYPE = "days"
DEFAULT_DELIVERED_FILTER_AMOUNT = 7

# Refresh interval (minutes) controls how often the coordinator polls the
# carrier. Default 30 min keeps the load on a consumer endpoint gentle; the
# minimum is 15 min for the same reason.
#
# Deliberate divergence from the HA Core rule that polling intervals are not
# user-configurable: that rule targets core integrations, and in a HACS parcel
# tracker a tunable cadence is a wanted feature. Generate with
# ``--interval fixed`` instead when the carrier throttles or soft-bans unusual
# traffic — that drops the option entirely and hard-codes the cadence, so users
# cannot dial it down to something that gets them blocked.
CONF_REFRESH_INTERVAL = "refresh_interval"
REFRESH_INTERVAL_OPTIONS = (15, 30, 60, 120, 240)
DEFAULT_REFRESH_INTERVAL = 30

# Per-parcel status history is opt-in and off by default, identical across the
# suite. Keep it off by default even when — as here — the timeline arrives in
# the same response and costs no extra request: it is a large attribute, and on
# carriers that need a second call per parcel the cost is real.
CONF_INCLUDE_HISTORY = "include_history"
DEFAULT_INCLUDE_HISTORY = False

# Cap each parcel's history to the most recent N events so the attribute stays
# well under HA's ~16 KB state-attribute limit.
HISTORY_MAX_EVENTS = 20
