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

# Payload keys. Named as constants because most of the payload shape was
# reconstructed from the vendor's web client before one real response existed,
# so every read of a field is greppable from one place.
#
# The keys below marked *observed* were confirmed against a real delivered
# `full` response (captured 2026-08-05, one order, redacted copy in
# `carrier-research/api/dynalogic/`). The rest are still reconstruction.
KEY_TRACKING_NUMBER = "TrackAndTraceNumber"   # observed
KEY_RESULT_CODE = "TransportResultCode"       # observed
KEY_SCENARIO = "Scenario"                     # observed
KEY_ACTIVE_STEP = "ActiveStep"                # observed
KEY_ORDER_DATA = "OrderData"                  # observed
KEY_ACTIVITIES = "Activities"                 # observed
KEY_EXECUTED = "ExecutedDateTime"             # observed
KEY_ADDRESSEE = "Addressee"                   # observed (shape redacted, see below)
KEY_CONTACT = "ContactInformation"            # observed (shape redacted)
KEY_CUSTOMER_NAME = "CustomerName"            # observed — the shipper, e.g. "bol."
KEY_ORDER_STATUS = "OrderStatusForAddressee"  # observed — "COMPLETED"

# The carrier's own machine-readable status, alongside the three-field triple.
# One value has been seen; the domain is unknown, so anything else warns once —
# collecting it is how this becomes usable as a cross-check on the mapping.
KNOWN_ORDER_STATUSES = frozenset({"COMPLETED"})

# Top-level keys we know about. Anything else in a real response is schema
# drift worth hearing about. Ten of these were unknown until the first real
# capture, which is the measure of how partial the reconstruction was — and it
# is still partial: that capture was a *delivered* order, so the delivery
# window, the driver position and the map pins the app renders for a parcel in
# transit have still never been seen.
KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        KEY_TRACKING_NUMBER,
        KEY_RESULT_CODE,
        KEY_SCENARIO,
        KEY_ACTIVE_STEP,
        KEY_ORDER_DATA,
        KEY_CONTACT,
        KEY_ORDER_STATUS,
        # Prose the carrier's own page renders under the progress bar.
        "DetailCaption",
        "DetailTextLine1",
        "DetailTextLine2",
        # Per-step render state for the four-dot progress bar; `ActiveStep`
        # already says the same thing in one integer.
        "ProgressData",
        # Null on the delivered order we have. The prime suspect for the
        # delivery window and the delayed live position — see `parcels.py`.
        "TransportProgress",
        "OrderGroup",
        "CustomerId",
        "OnlineAppointmentEnabled",
        "PushNotificationsEnabled",
    }
)

# `ExecutedDateTime` arrives as a naive ISO 8601 stamp — `2026-08-04T13:34:10.507`,
# fractional seconds of any length, **no offset**. The vendor's *web* client also
# handles a compact `YYYYMMDDHHmmss` form (its `dynadatetime` pipe branches on a
# bare 14-digit match), so both are accepted; only ISO has been seen on the wire.
#
# Neither form carries a zone, and Amsterdam remains an *assumption* — a .NET
# `DateTime` with `Kind=Unspecified` conventionally serialises local time, and
# the carrier is a Dutch last-mile operation. There is real counter-evidence:
# the captured order's "Afspraak gepland voor vandaag" activity is stamped
# 23:33 on the day *before* the window it announces, which reads correctly only
# if the stamp is UTC. Unresolved; it needs one parcel whose real delivery time
# the reporter can state. Until then a wrong reading costs two hours on
# `delivered_at` and on every history entry, and nothing else.
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
