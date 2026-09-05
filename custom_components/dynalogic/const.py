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

# Every optional key the parcel contract defines. CAPABILITIES below must be a
# subset of this — it exists so a typo in CAPABILITIES fails a test instead of
# silently dropping this carrier off a table on the docs site.
KNOWN_CAPABILITIES = frozenset(
    {"weight", "dimensions", "delivery_window", "pickup_point", "url", "history"}
)

# Which optional contract fields this carrier's API actually populates — feeds
# the comparison table on the docs site. Keep in lockstep with
# normalize_parcel() in parcels.py: everything not listed here comes back as a
# literal None there. The one delivered order captured so far has no delivery
# window, no pickup-point signal, no constructible tracking URL, and no
# weight/dimensions — only history is populated.
CAPABILITIES = frozenset({"history"})

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

# Dutch postcode: four digits, two letters. Belgian postcode: the same four
# digits, no letters. Stored normalised (no space, upper case) and lower-cased
# on the wire, which is what the vendor's own client does.
POSTCODE_RE = r"^[1-9][0-9]{3}([A-Z]{2})?$"

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
# `full` response (captured 2026-08-05, one order). The rest are still
# reconstruction.
KEY_TRACKING_NUMBER = "TrackAndTraceNumber"   # observed
KEY_RESULT_CODE = "TransportResultCode"       # observed
KEY_SCENARIO = "Scenario"                     # observed
KEY_ACTIVE_STEP = "ActiveStep"                # observed
KEY_ORDER_DATA = "OrderData"                  # observed
KEY_ACTIVITIES = "Activities"                 # observed
KEY_EXECUTED = "ExecutedDateTime"             # observed
KEY_ADDRESSEE = "Addressee"                   # observed — object, shape known
KEY_CONTACT = "ContactInformation"            # observed — object, shape known
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
# Neither form carries a zone, and Amsterdam is **confirmed** (2026-08-05): the
# captured order's delivery activity is stamped 13:34 and the recipient put the
# actual delivery at about 13:30. Read as UTC it would have been 15:34, so the
# two readings are two hours apart and the answer is not close.
#
# Nothing in that payload argues the other way. 0.9.x recorded one thing that
# seemed to — an "Afspraak gepland voor vandaag" activity stamped 23:33 on the
# day *before* the window it announces — and put it down to a sloppy message
# template. The unredacted payload (2026-08-06) shows the activity actually says
# "Afspraak gepland voor **dinsdag 4 augustus**", stamped the Monday night: it
# names the day and is perfectly consistent. The "vandaag" was introduced by the
# date substitution in the redacted copy. Recorded here so nobody re-opens the
# question on seeing either version.
CARRIER_TIMEZONE = "Europe/Amsterdam"
TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"

# Delivered-parcels retention: keep delivered parcels visible for the last N
# days, or keep only the N most recent — identical across the suite.
CONF_DELIVERED_FILTER_TYPE = "delivered_filter_type"
CONF_DELIVERED_FILTER_AMOUNT = "delivered_filter_amount"
DEFAULT_DELIVERED_FILTER_TYPE = "days"
DEFAULT_DELIVERED_FILTER_AMOUNT = 7

# Dynamic, status-driven polling — unconditional, no user-facing interval
# option.
#
# Quiet window: no polling between these local hours except the two anchors
# below, for overnight / end-of-day catch-up.
QUIET_WINDOW_START_HOUR = 0
QUIET_WINDOW_END_HOUR = 6

# Cadence while polling is active (minutes). Hot = at least one tracked,
# not-yet-delivered parcel is out_for_delivery within HOT_LOOKAHEAD_HOURS of
# its planned_from (or has no planned_from at all — the only case this
# carrier's payload has ever produced, since no delivery-window field is
# known yet); mid = anything else still in flight. This is a barcode-based
# coordinator (Section 2.1): when every tracked parcel is delivered, or
# nothing is tracked, polling stops entirely instead of falling to the mid
# tier — see coordinator.py's ``_hottest_tier_minutes``.
HOT_INTERVAL_MINUTES = 15
MID_INTERVAL_MINUTES = 45
HOT_LOOKAHEAD_HOURS = 1

# Small, stable per-install offset added to every computed interval so
# different installs don't all hit an anchor or tier boundary at the same
# second. Deterministic (hash of the config entry id), not random.
STAGGER_MINUTES = 7

# Per-parcel status history is opt-in and off by default, identical across the
# suite. Keep it off by default even when — as here — the timeline arrives in
# the same response and costs no extra request: it is a large attribute, and on
# carriers that need a second call per parcel the cost is real.
CONF_INCLUDE_HISTORY = "include_history"
DEFAULT_INCLUDE_HISTORY = False

# Cap each parcel's history to the most recent N events so the attribute stays
# well under HA's ~16 KB state-attribute limit.
HISTORY_MAX_EVENTS = 20
