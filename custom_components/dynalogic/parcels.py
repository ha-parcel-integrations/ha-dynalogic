"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping apart from the coordinator (which is nearly identical
everywhere), and it makes the mapping trivially unit-testable without spinning
up HA.

**Read this before changing the mapping.** Exactly **one** populated tracking
response has ever been observed — a delivered order, captured 2026-08-05 — and
it corrected two things the reconstruction had wrong (the timestamp format, and
the claim that the carrier ships no status text) while leaving the expensive
gaps open: it was already delivered, so the delivery window, the driver position
and the map pins the app renders for a parcel *in transit* remain unseen.

So the rule here is unchanged: read the fields we are sure exist, publish
``None`` for everything else, and make every remaining guess announce itself
once via :func:`_warn_once` so the next real parcel corrects it instead of
passing silently. The suite's pre-1.0 obligation is exactly this.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry

from .const import (
    CARRIER_TIMEZONE,
    COMPLETE_RESULT_CODES,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    KEY_ACTIVE_STEP,
    KEY_ACTIVITIES,
    KEY_ADDRESSEE,
    KEY_CUSTOMER_NAME,
    KEY_EXECUTED,
    KEY_ORDER_DATA,
    KEY_ORDER_STATUS,
    KEY_RESULT_CODE,
    KEY_SCENARIO,
    KEY_TRACKING_NUMBER,
    KNOWN_ORDER_STATUSES,
    KNOWN_RESULT_CODES,
    KNOWN_SCENARIOS,
    KNOWN_TOP_LEVEL_KEYS,
    MAX_ACTIVE_STEP,
    MIN_ACTIVE_STEP,
    TIMESTAMP_FORMAT,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Built once at import time: constructing a ZoneInfo reads from disk, which is
# not something to do inside the event loop on every timestamp.
_CARRIER_TZ = ZoneInfo(CARRIER_TIMEZONE)

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-dynalogic/issues/new"
    "?template=unrecognised_status.yml"
)

# Everything already reported, so each surprise is logged once per HA session
# instead of on every poll. Keyed by a short tag so the different kinds of
# surprise (a scenario, a result code, a drifted schema) cannot mask each other.
_warned: set[str] = set()


def _warn_once(key: str, message: str, *args: Any) -> None:
    """Log ``message`` once per session, with a copy-paste issue link.

    Every unverified assumption in this module funnels through here. The suite
    ships carriers below 1.0 on reconstructed payloads deliberately, on the
    condition that each thing we are unsure about asks a real user to report it
    — a passive TODO in the code never produces the data.
    """
    if key in _warned:
        return
    _warned.add(key)
    _LOGGER.warning(
        message + "\n  Please report it — open an issue with this line: %s",
        *args,
        NEW_ISSUE_URL,
    )


def report_unknown_parcel(tracking_code: str) -> None:
    """Report, once per order number, that the carrier does not know it.

    Without this the parcel simply sits at ``unknown`` forever and the user has
    no idea why. The three causes are worth spelling out, because the second is
    by far the most common and the least obvious: Dynalogic answers the same
    bare 404 for an unknown order number, for a postcode that is not the one
    the parcel is being delivered to, and for an order it has not created yet.
    """
    _warn_once(
        f"not_found:{tracking_code}",
        "Dynalogic does not know order number %s with the postcode you gave "
        "it. Either the order number is wrong, the postcode is not the "
        "delivery address for this parcel, or the carrier has not registered "
        "the order yet — the last one resolves itself.",
        tracking_code,
    )


def _coerce_result_code(value: Any) -> int | None:
    """Return ``TransportResultCode`` as an int, or ``None`` if it is absent.

    The vendor's client treats it as a number; whether the JSON carries it as
    one is unconfirmed, so a numeric string is accepted too.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        _warn_once(
            f"result_code_type:{value!r}",
            "Dynalogic reported a non-numeric TransportResultCode (%r).",
            value,
        )
        return None


def map_parcel_status(
    scenario: str | None, active_step: Any, result_code: Any
) -> ParcelStatus:
    """Map Dynalogic's three status fields onto one canonical status.

    Dynalogic has no single status field. It reports *which kind of job* this is
    (``Scenario``), *how far along* it is (``ActiveStep``, 1–4) and a
    ``TransportResultCode`` whose 16 values are all known but only one of which
    has a known meaning: ``0`` is the completed state, per the vendor's own
    client. So the mapping leans on the two fields that are legible and treats a
    non-zero result code as "not finished yet".

    The rules, in the order they are applied:

    * a ``_FAIL`` scenario is a ``problem`` at any step — the job's own course
      says it went wrong, which outranks how far along it got;
    * a return (``RS_DEF``) is ``returning`` throughout, including once it
      completes: the canonical vocabulary has no "returned" terminal state, and
      ``returning`` stays the truest of the eight;
    * otherwise the completed result code at the last step is ``delivered``;
    * otherwise the step decides: 4 or 3 ``out_for_delivery``, 2
      ``in_transit``, 1 ``registered``.

    Delivery to a neighbour (``DEL_NB``) maps to plain ``delivered``, like every
    other suite carrier's neighbour/safe-place variants — the canonical
    vocabulary deliberately has one delivered state, and the scenario survives
    on ``raw_status`` and in ``raw`` for anyone who needs the distinction.

    **One combination of the mapping is now observed**, ``DEL_DEF``/4/0 →
    ``delivered``, and a real order confirmed it three ways over: the step, the
    result code, and the carrier's own ``DetailCaption`` and
    ``OrderStatusForAddressee``. Every other combination is still a reading of
    two fields no real parcel has exercised, which is why they all still warn.
    """
    if scenario is not None:
        scenario = str(scenario).strip().upper()
        if scenario and scenario not in KNOWN_SCENARIOS:
            _warn_once(
                f"scenario:{scenario}",
                "Unrecognised Dynalogic scenario %r — reported as 'unknown'.",
                scenario,
            )
            scenario = None

    code = _coerce_result_code(result_code)
    if code is not None and code not in KNOWN_RESULT_CODES:
        _warn_once(
            f"result_code:{code}",
            "Unrecognised Dynalogic TransportResultCode %s — the parcel's "
            "status may be wrong.",
            code,
        )

    step = _coerce_result_code(active_step)
    if step is not None and not MIN_ACTIVE_STEP <= step <= MAX_ACTIVE_STEP:
        _warn_once(
            f"active_step:{step}",
            "Dynalogic reported ActiveStep %s, outside the known range %s-%s.",
            step,
            MIN_ACTIVE_STEP,
            MAX_ACTIVE_STEP,
        )
        step = None

    if scenario is None and step is None:
        # A parcel the carrier 404s on: nothing to map and nothing to report.
        return ParcelStatus.UNKNOWN

    status = _status_for(scenario, step, code)
    _report_combination(scenario, step, code, status)
    return status


def _status_for(
    scenario: str | None, step: int | None, code: int | None
) -> ParcelStatus:
    """Apply the mapping rules — see :func:`map_parcel_status` for the why."""
    if scenario is not None and scenario.endswith("_FAIL"):
        return ParcelStatus.PROBLEM
    if scenario == "RS_DEF":
        return ParcelStatus.RETURNING
    if code in COMPLETE_RESULT_CODES and step == MAX_ACTIVE_STEP:
        return ParcelStatus.DELIVERED
    if step is None:
        return ParcelStatus.UNKNOWN
    if step >= 3:
        return ParcelStatus.OUT_FOR_DELIVERY
    if step == 2:
        return ParcelStatus.IN_TRANSIT
    return ParcelStatus.REGISTERED


# ``(Scenario, ActiveStep, TransportResultCode)`` triples a real order has been
# seen carrying, with the status this module reads them as independently
# confirmed by the carrier's own text. Add to this only from a capture, never
# from reasoning — the whole value of the list is that it means "seen".
CONFIRMED_COMBINATIONS = frozenset(
    {
        # Captured 2026-08-05: a completed bol.com delivery. `DetailCaption`
        # said "Succesvol bezorgd" and `OrderStatusForAddressee` "COMPLETED".
        ("DEL_DEF", 4, 0),
    }
)


def _report_combination(
    scenario: str | None, step: int | None, code: int | None, status: ParcelStatus
) -> None:
    """Report each distinct status combination once, with what we made of it.

    This is the one that settles ``TransportResultCode``. Fifteen of its
    sixteen values have no known meaning, and the only way to learn them is to
    see which combination a real parcel carries at a moment its owner can
    describe ("it was on the van when this fired"). One line per distinct
    combination is a bounded amount of noise — at most a handful per parcel —
    and it is the difference between guessing the vocabulary and knowing it.

    Combinations a real order has already confirmed are skipped: asking users
    to re-report the one case we are sure of would spend their goodwill on the
    answer we have. Every parcel ends up delivered, so without this the plain
    completed state would be the loudest line in the log.
    """
    if (scenario, step, code) in CONFIRMED_COMBINATIONS:
        return
    _warn_once(
        f"combination:{scenario}/{step}/{code}",
        "Dynalogic reported Scenario=%s ActiveStep=%s TransportResultCode=%s, "
        "which this integration reads as '%s'. Only result code 0 has a "
        "documented meaning, so if that does not match what Dynalogic's own "
        "app or website shows for this parcel, we have it wrong.",
        scenario,
        step,
        code,
        status,
    )


def raw_status(scenario: Any, active_step: Any, result_code: Any) -> str | None:
    """Return the carrier's own status, verbatim, as one string.

    Dynalogic has no single status *field*, so the three that carry the status
    are joined: ``"DEL_DEF/4/0"``.

    The first real capture showed the carrier does ship human-readable text
    after all — ``DetailCaption`` ("Succesvol bezorgd"), ``DetailTextLine2``,
    and a machine-readable ``OrderStatusForAddressee`` ("COMPLETED"). 0.9.x said
    it shipped none; that was wrong, and it is corrected here rather than acted
    on. The triple stays because it is the better automation key: it is
    complete (never absent while the parcel has a status at all), it is not
    localised, and it preserves the scenario the canonical status flattens away
    — a neighbour delivery is ``delivered`` here and ``DEL_NB/4/0`` there. The
    prose rides in ``raw`` for anyone who wants to display it, and
    ``OrderStatusForAddressee`` is being collected by :func:`check_order_status`
    against the day it has enough known values to cross-check the mapping.
    """
    parts = [scenario, active_step, result_code]
    if all(part is None for part in parts):
        return None
    return "/".join("?" if part is None else str(part) for part in parts)


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for a Dynalogic timestamp field.

    Two forms are accepted, and the difference between them cost this
    integration its whole history until a real response arrived:

    * **ISO 8601, naive** — ``2026-08-04T13:34:10.507``, fractional seconds of
      any length, no offset. This is what the middleware actually sends; it is
      the only form ever observed.
    * **``YYYYMMDDHHmmss``** — what the vendor's *web* client detects with a
      bare 14-digit match. 0.9.0 accepted only this, on the strength of that
      client, and consequently dropped every timestamp a real order carried:
      no ``history``, no ``delivered_at``. Kept because the web client plainly
      handles it, so some route or some order kind presumably emits it.

    Neither form carries a zone, so both are read as Europe/Amsterdam — an
    assumption, and one with live counter-evidence; see ``CARRIER_TIMEZONE``.
    A stamp that *does* carry an offset is trusted as-is. Anything else warns
    once and is dropped rather than guessed at.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    parsed: datetime | None = None
    try:
        parsed = datetime.strptime(text, TIMESTAMP_FORMAT)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None

    if parsed is None:
        _warn_once(
            "timestamp_format",
            "Dynalogic sent a timestamp in a format we cannot read (%r) — it "
            "was dropped, so a parcel may be missing its history or delivery "
            "time.",
            text,
        )
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_CARRIER_TZ)
    return parsed.isoformat()


# Candidate keys for an activity's own description. ``ExecutedDateTime`` is the
# only field of an ``Activities[]`` element that was recovered — the rest of the
# element is unseen, so the description is looked for under the names a .NET DTO
# would plausibly use, and the ones that miss are reported by
# :func:`_activity_text` rather than silently yielding a blank history.
# The three fields every transport order must carry — they are the status.
# Their absence from a real response is a bigger surprise than an extra field.
_EXPECTED_KEYS = (KEY_SCENARIO, KEY_ACTIVE_STEP, KEY_RESULT_CODE)

_ACTIVITY_TEXT_KEYS = (
    "Description",
    "ActivityDescription",
    "Text",
    "Name",
    "Status",
    "StatusDescription",
    "ActivityCode",
    "Code",
)


def _activity_text(activity: dict) -> str | None:
    """Return an activity's own description, or ``None`` when it has none."""
    for key in _ACTIVITY_TEXT_KEYS:
        value = activity.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            text = str(value).strip()
            if text:
                return text
    _warn_once(
        "activity_shape",
        "A Dynalogic activity carried no recognised description field. Its "
        "keys are: %s (values withheld — they may contain personal data).",
        sorted(activity),
    )
    return None


def build_history(
    events: list | None, *, max_events: int = HISTORY_MAX_EVENTS
) -> list[dict]:
    """Build the canonical ``history`` list from ``OrderData.Activities``.

    Each entry is ``{timestamp, status, raw_status}`` — identical across all
    suite carriers, and top-level (not under ``raw``) so it survives the
    aggregator's ``strip_raw()``. Sorted oldest → newest and capped to the most
    recent ``max_events``.

    ``status`` is always ``None`` here: an activity carries a timestamp and a
    description, and nothing that maps onto the canonical vocabulary. ``None``
    (rather than ``unknown``) is the contract's way of saying "no mapping
    attempted", so a consumer can tell the two apart.
    """
    parseable: list[tuple[datetime, dict]] = []
    unparseable: list[dict] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        timestamp = to_iso_timestamp(event.get(KEY_EXECUTED))
        if not timestamp:
            continue
        entry = {
            "timestamp": timestamp,
            "status": None,
            "raw_status": _activity_text(event),
        }
        parsed = parse_iso(timestamp)
        if parsed is None:
            unparseable.append(entry)
        else:
            parseable.append((parsed, entry))
    parseable.sort(key=lambda item: item[0])
    ordered = [entry for _, entry in parseable] + unparseable
    return ordered[-max_events:]


def _order_data(raw: dict) -> dict:
    """Return the ``OrderData`` block, or an empty dict when it is absent.

    Absent on the ``partial`` route, and on a ``full`` response the postcode did
    not unlock — :func:`check_response_shape` is what complains about the
    second case, so callers here can simply read through it.
    """
    order_data = raw.get(KEY_ORDER_DATA)
    return order_data if isinstance(order_data, dict) else {}


def _activities(raw: dict) -> list:
    """Return ``OrderData.Activities`` — the parcel's own event list."""
    activities = _order_data(raw).get(KEY_ACTIVITIES)
    return activities if isinstance(activities, list) else []


def _sender(raw: dict) -> str | None:
    """Return the shipper's name from ``OrderData.CustomerName``.

    Observed and unambiguous — the captured order carried ``"bol."``. Dynalogic
    is a contract carrier, so its "customer" is whoever handed it the parcel,
    which is the sender from the recipient's point of view.
    """
    value = _order_data(raw).get(KEY_CUSTOMER_NAME)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


# Candidate keys for the addressee's name, used only if ``Addressee`` turns out
# to be an object. Same approach as `_ACTIVITY_TEXT_KEYS` and for the same
# reason: the block is personal data, so the one capture we have has it redacted
# whole and its shape is genuinely unknown.
_ADDRESSEE_NAME_KEYS = ("Name", "FullName", "Addressee", "ContactName", "CompanyName")


def _receiver(raw: dict) -> str | None:
    """Return the addressee's name from ``OrderData.Addressee``.

    ``Addressee`` is confirmed to exist and confirmed to be personal data, which
    is exactly why its shape is not: every copy we can look at has the whole
    block redacted. The reconstruction from the web client suggested an object
    with ``PostalCode`` / ``CountryName``; the field name reads like a scalar.
    Both are handled, and an object whose name field we cannot find reports its
    keys once rather than publishing a silent ``None`` forever.
    """
    value = _order_data(raw).get(KEY_ADDRESSEE)
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict) or not value:
        return None
    for key in _ADDRESSEE_NAME_KEYS:
        name = value.get(key)
        if isinstance(name, str) and name.strip():
            return name.strip()
    _warn_once(
        "addressee_shape",
        "Dynalogic's Addressee block carried no recognised name field, so the "
        "parcel's recipient is empty. Its keys are: %s (values withheld — this "
        "block is the recipient's name and address).",
        sorted(value),
    )
    return None


def check_order_status(raw: dict) -> None:
    """Report an ``OrderStatusForAddressee`` value we have not seen before.

    This is the carrier's *own* machine-readable status, and it only surfaced
    with the first real capture — the reconstruction never saw it. One value is
    known (``COMPLETED``, on a delivered order). The mapping deliberately does
    not use it yet: a single known value is not a vocabulary, and swapping a
    mapping that works for one built on guesswork would be a step backwards.
    Collecting the domain is what makes it usable as a cross-check on the
    ``Scenario`` / ``ActiveStep`` / ``TransportResultCode`` triple.
    """
    value = raw.get(KEY_ORDER_STATUS)
    if not isinstance(value, str) or not value.strip():
        return
    value = value.strip()
    if value in KNOWN_ORDER_STATUSES:
        return
    _warn_once(
        f"order_status:{value}",
        "Dynalogic reported OrderStatusForAddressee=%r, which we have not seen "
        "before. It is the carrier's own status name and we are collecting its "
        "values — please say what the carrier's app or website showed for this "
        "parcel at the same moment.",
        value,
    )


def _latest_activity_timestamp(raw: dict) -> str | None:
    """Return the most recent activity timestamp, or ``None``.

    Used as the delivery time: the newest activity on a completed order is the
    delivery itself. Inferred — there is no dedicated delivered-at field in the
    recovered payload, and no real one to check it against yet.
    """
    stamps = [
        (parsed, stamp)
        for event in _activities(raw)
        if isinstance(event, dict)
        and (stamp := to_iso_timestamp(event.get(KEY_EXECUTED)))
        and (parsed := parse_iso(stamp))
    ]
    if not stamps:
        return None
    # Compare the parsed datetimes, not the strings: the offset flips between
    # +01:00 and +02:00 across DST, so ISO strings do not sort reliably.
    return max(stamps, key=lambda item: item[0])[1]


def check_response_shape(raw: dict) -> None:
    """Report, once, anything about a response we did not expect.

    Two things are worth hearing about. **Unknown top-level keys** are the
    payload telling us what the reconstruction missed — the first real capture
    turned up ten of them at once, and the stop coordinates and the delayed live
    position the app renders for a parcel in transit still have no name. A
    **``full`` response without ``OrderData``** would mean the postcode was
    accepted but the two routes split their data differently than read, which
    would invalidate the decision to require a postcode at all.

    Called by the coordinator on a real response only — a parcel the carrier
    404s on is served from a placeholder, which has no shape to check.

    Keys only, never values: a response body carries an address and a name.
    """
    unexpected = sorted(set(raw) - KNOWN_TOP_LEVEL_KEYS)
    if unexpected:
        _warn_once(
            "top_level_keys:" + ",".join(unexpected),
            "Dynalogic returned fields we do not map yet: %s. These may hold "
            "the delivery window, the driver or the live position (values "
            "withheld — they may contain personal data).",
            unexpected,
        )

    missing = [key for key in _EXPECTED_KEYS if key not in raw]
    if missing:
        _warn_once(
            "missing_keys:" + ",".join(missing),
            "A Dynalogic response arrived without %s. Those fields carry the "
            "parcel's status, so it will show as 'unknown' or worse.",
            missing,
        )

    if KEY_ORDER_DATA not in raw:
        _warn_once(
            "missing_order_data",
            "A Dynalogic response arrived without %s, so this parcel has no "
            "history. That is unexpected when a postcode was supplied — it "
            "would mean the two tracking routes divide their data differently "
            "than we read them.",
            KEY_ORDER_DATA,
        )
    elif not _activities(raw):
        _warn_once(
            "empty_activities",
            "A Dynalogic response carried %s but no %s, so there is no history "
            "and no delivery timestamp. Either the list is genuinely empty for "
            "this parcel, or it lives under another name.",
            KEY_ORDER_DATA,
            KEY_ACTIVITIES,
        )

    check_order_status(raw)
    report_structure(raw)


# How deep the structure report walks. Six levels is well past anything the
# reconstruction suggests; the cap is there so a self-referential or absurdly
# nested payload cannot turn a log line into a hang.
_MAX_STRUCTURE_DEPTH = 6


def describe_structure(value: Any, path: str = "", depth: int = 0) -> list[str]:
    """Return the payload's shape as ``path: type`` lines, **values omitted**.

    A response we have never seen is worth more as a map than as a complaint:
    this is what tells us the delivery window is called
    ``PlannedDeliveryWindow.From`` rather than that "some field is missing". A
    list is described by its first element — the shape is the point, not the
    count — and only the *types* of leaves are reported, so a name, an address
    or a set of coordinates can never end up in a log a user pastes publicly.
    """
    if depth >= _MAX_STRUCTURE_DEPTH:
        return [f"{path}: … (nested deeper than {_MAX_STRUCTURE_DEPTH})"]
    if isinstance(value, dict):
        if not value:
            return [f"{path}: empty object"]
        lines: list[str] = []
        for key in sorted(value):
            child = f"{path}.{key}" if path else key
            lines += describe_structure(value[key], child, depth + 1)
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{path}[]: empty list"]
        return describe_structure(value[0], f"{path}[]", depth + 1)
    return [f"{path}: {type(value).__name__}"]


def report_structure(raw: dict) -> None:
    """Log the full shape of a response once per distinct shape.

    Keyed on the shape itself rather than on "first response ever", so a
    delivered parcel that carries fields an in-transit one does not — a proof
    of delivery, a neighbour's details — reports as well. Distinct shapes are
    few; this is not per-parcel noise.
    """
    lines = describe_structure(raw)
    _warn_once(
        "structure:" + "|".join(lines),
        "Dynalogic response structure (field names and types only, no values "
        "— safe to paste). This integration was built without ever seeing a "
        "real response, so this listing is the single most useful thing you "
        "can send us:\n    %s",
        "\n    ".join(lines),
    )


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The **keys of the returned dict are the contract**: every carrier in the
    suite returns exactly these, in this order, and the aggregator and
    cross-carrier dashboards depend on it. A key the carrier does not expose is
    ``None``, never omitted.

    The first real capture closed two of the six that shipped as ``None`` in
    0.9.0 — ``sender`` and ``receiver``. Four remain, deliberately:

    * ``planned_from`` / ``planned_to`` — still no delivery-window field. The
      one order we have carries its window as **prose inside an activity**
      ("Afspraak gepland voor vandaag tussen 8:00u en 22:00u"), which is not
      something to parse: it is localised, it is free text, and the structured
      field almost certainly exists on an order that has not been delivered yet.
      ``TransportProgress`` is the suspect — present at top level, ``null`` on a
      completed order. Until an in-transit capture names it the calendar and the
      *next delivery* sensor stay empty.
    * ``pickup_point`` — Dynalogic delivers to the door; the drop-off scenarios
      (``DP_*``) are a job type, not a parcel waiting in a shop, so nothing maps
      onto ``at_pickup_point``.
    * ``url`` — the tracking links Dynalogic e-mails carry a server-side
      AES-encrypted token that cannot be constructed, and no order-number query
      format for the site is known. A link that 404s is worse than no link.

    ``weight`` and ``dimensions`` follow the same rule: the carrier is a
    last-mile courier and exposes neither.

    ``barcode`` stays the **order number** (``TrackAndTraceNumber``), not
    ``OrderData.OrderLines[].Barcode``. The real capture proved the two differ —
    the order lines carry the physical parcel barcode — but the order number is
    what the user entered, what the sensor's unique id is built from, and what
    is present even on a 404 placeholder.
    """
    tracking_code = raw.get(KEY_TRACKING_NUMBER)
    scenario = raw.get(KEY_SCENARIO)
    active_step = raw.get(KEY_ACTIVE_STEP)
    result_code = raw.get(KEY_RESULT_CODE)

    status = map_parcel_status(scenario, active_step, result_code)
    delivered = status is ParcelStatus.DELIVERED

    return {
        "carrier": "Dynalogic",
        "barcode": tracking_code,
        "sender": _sender(raw),
        "receiver": _receiver(raw),
        "status": status,
        "raw_status": raw_status(scenario, active_step, result_code),
        "delivered": delivered,
        # No delivered-at field exists; the newest activity on a completed
        # order is the delivery. Inferred, like the status mapping.
        "delivered_at": _latest_activity_timestamp(raw) if delivered else None,
        "planned_from": None,
        "planned_to": None,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": None,
        "url": None,
        "weight": None,
        "dimensions": None,
        "history": build_history(_activities(raw)) if include_history else None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(
        CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE
    )
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(timezone.utc) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
