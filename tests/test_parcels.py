"""Tests for the pure parcel-mapping helpers.

These need no Home Assistant instance — the whole point of keeping
``parcels.py`` free of I/O is that the carrier-specific mapping can be tested
as plain functions.

Everything here tests the *mapping*, not the carrier: no real Dynalogic
response has been observed, so a green run means "the code does what we decided
it should do", never "this is what the carrier sends". The one-shot warnings
are tested as carefully as the mapping itself, because below 1.0 they are how
the mapping gets corrected.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.dynalogic.parcels as parcels_module
from custom_components.dynalogic.const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DOMAIN,
    ParcelStatus,
)
from custom_components.dynalogic.parcels import (
    apply_delivered_filter,
    build_history,
    check_response_shape,
    map_parcel_status,
    normalize_parcel,
    parse_iso,
    raw_status,
    sort_parcels_by_ts,
    to_iso_timestamp,
)

from .payloads import (
    ACTIVE_CODE,
    DELIVERED_CODE,
    active_sample,
    activity,
    delivered_sample,
    failed_sample,
    neighbour_sample,
    partial_sample,
)


@pytest.fixture(autouse=True)
def _reset_one_shot_warnings():
    """Clear the module's one-shot set so warning tests do not mask each other."""
    parcels_module._warned.clear()
    yield
    parcels_module._warned.clear()


# ---------------------------------------------------------------------------
# map_parcel_status — scenario x step x result code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario,step,code,expected",
    [
        # The completed result code at the last step is the only delivery.
        ("DEL_DEF", 4, 0, ParcelStatus.DELIVERED),
        # A neighbour delivery is still a delivery — the canonical vocabulary
        # has one delivered state, and DEL_NB survives on raw_status.
        ("DEL_NB", 4, 0, ParcelStatus.DELIVERED),
        # The last step without the completed code is not done yet.
        ("DEL_DEF", 4, 27, ParcelStatus.OUT_FOR_DELIVERY),
        ("DEL_DEF", 3, 27, ParcelStatus.OUT_FOR_DELIVERY),
        ("DEL_DEF", 2, 22, ParcelStatus.IN_TRANSIT),
        ("DEL_DEF", 1, 22, ParcelStatus.REGISTERED),
        # A _FAIL scenario outranks how far along the job got.
        ("DEL_FAIL", 1, 22, ParcelStatus.PROBLEM),
        ("PU_FAIL", 4, 0, ParcelStatus.PROBLEM),
        # A return stays "returning" even once it completes: there is no
        # canonical "returned".
        ("RS_DEF", 2, 22, ParcelStatus.RETURNING),
        ("RS_DEF", 4, 0, ParcelStatus.RETURNING),
        # Other job types complete like a delivery does.
        ("SW_DEF", 4, 0, ParcelStatus.DELIVERED),
        ("PU_DEF", 3, 27, ParcelStatus.OUT_FOR_DELIVERY),
    ],
)
def test_map_parcel_status_known_combinations(scenario, step, code, expected):
    assert map_parcel_status(scenario, step, code) == expected


def test_map_parcel_status_without_any_field_is_unknown():
    """A parcel the carrier 404s on has no fields at all, and says so."""
    assert map_parcel_status(None, None, None) == ParcelStatus.UNKNOWN


def test_map_parcel_status_falls_back_to_the_step_alone():
    """The step is legible even when the scenario is missing."""
    assert map_parcel_status(None, 2, None) == ParcelStatus.IN_TRANSIT


def test_map_parcel_status_scenario_only_is_unknown():
    """Knowing the job type but not its progress says nothing about status."""
    assert map_parcel_status("DEL_DEF", None, None) == ParcelStatus.UNKNOWN


def test_map_parcel_status_accepts_numeric_strings():
    """Whether the JSON carries these as numbers is unconfirmed."""
    assert map_parcel_status("DEL_DEF", "4", "0") == ParcelStatus.DELIVERED


def test_unknown_scenario_warns_once_and_reports_unknown(caplog):
    assert map_parcel_status("TELEPORT_DEF", None, 0) == ParcelStatus.UNKNOWN
    assert map_parcel_status("TELEPORT_DEF", None, 0) == ParcelStatus.UNKNOWN
    assert caplog.text.count("TELEPORT_DEF") == 1
    assert "issues/new" in caplog.text


def test_unknown_result_code_warns_but_still_maps(caplog):
    """An unknown code is reported; the step still yields a usable status."""
    assert map_parcel_status("DEL_DEF", 3, 999) == ParcelStatus.OUT_FOR_DELIVERY
    assert "999" in caplog.text
    assert "issues/new" in caplog.text


def test_out_of_range_step_warns_and_is_ignored(caplog):
    assert map_parcel_status("DEL_DEF", 9, 22) == ParcelStatus.UNKNOWN
    assert "ActiveStep 9" in caplog.text


def test_non_numeric_result_code_warns_once(caplog):
    assert map_parcel_status("DEL_DEF", 3, "later") == ParcelStatus.OUT_FOR_DELIVERY
    assert "non-numeric" in caplog.text


# ---------------------------------------------------------------------------
# raw_status
# ---------------------------------------------------------------------------


def test_raw_status_joins_the_three_fields():
    """Dynalogic ships no status text, so the fields themselves are the text."""
    assert raw_status("DEL_NB", 4, 0) == "DEL_NB/4/0"


def test_raw_status_marks_missing_parts_and_is_none_when_empty():
    assert raw_status("DEL_DEF", None, 0) == "DEL_DEF/?/0"
    assert raw_status(None, None, None) is None


# ---------------------------------------------------------------------------
# timestamp helpers
# ---------------------------------------------------------------------------


def test_parse_iso_handles_offsets_naive_and_garbage():
    assert parse_iso("2026-04-29T13:12:42+02:00").tzinfo is not None
    # A naive value is assumed UTC so mixed lists still sort.
    assert parse_iso("2026-04-29T13:12:42").tzinfo == timezone.utc
    assert parse_iso("not-a-date") is None
    assert parse_iso(None) is None


def test_to_iso_timestamp_reads_amsterdam_local_time():
    """`YYYYMMDDHHmmss`, no offset — assumed Europe/Amsterdam, summer time."""
    assert to_iso_timestamp("20260429131242") == "2026-04-29T13:12:42+02:00"


def test_to_iso_timestamp_applies_winter_offset():
    """The same assumption in January, to prove it is a zone and not +02:00."""
    assert to_iso_timestamp("20260105080000") == "2026-01-05T08:00:00+01:00"


def test_to_iso_timestamp_ignores_empty_values():
    assert to_iso_timestamp(None) is None
    assert to_iso_timestamp("  ") is None


def test_to_iso_timestamp_warns_once_on_another_format(caplog):
    """If the format assumption is wrong, the user hears about it."""
    assert to_iso_timestamp("2026-04-29T13:12:42Z") is None
    assert to_iso_timestamp("2026-04-29T13:12:42Z") is None
    assert caplog.text.count("YYYYMMDDHHmmss") == 1


# ---------------------------------------------------------------------------
# build_history
# ---------------------------------------------------------------------------


def test_build_history_orders_oldest_to_newest():
    history = build_history(delivered_sample()["OrderData"]["Activities"])
    assert len(history) == 4
    assert history[0]["raw_status"] == "Zending aangemeld"
    assert history[-1]["raw_status"] == "Afgeleverd"


def test_build_history_never_maps_a_canonical_status():
    """An activity carries a time and a description, nothing mappable."""
    history = build_history(delivered_sample()["OrderData"]["Activities"])
    assert {entry["status"] for entry in history} == {None}


def test_build_history_caps_to_max_events():
    events = [activity(f"202604{day:02d}100000", "moved") for day in range(1, 26)]
    assert len(build_history(events, max_events=20)) == 20


def test_build_history_handles_missing_and_malformed():
    assert build_history(None) == []
    assert build_history([{"Description": "no timestamp"}]) == []
    assert build_history(["not-a-dict"]) == []


def test_build_history_warns_once_about_an_undescribed_activity(caplog):
    """The activity element's shape is unseen — an unknown one must be reported."""
    history = build_history(
        [{"ExecutedDateTime": "20260429131242", "Whatever": "unmapped"}]
    )
    assert history[0]["raw_status"] is None
    assert "Whatever" in caplog.text
    assert "issues/new" in caplog.text


def test_build_history_does_not_log_activity_values(caplog):
    """Keys are safe to log; values may be an address or a name."""
    build_history([{"ExecutedDateTime": "20260429131242", "Street": "Kerkstraat 1"}])
    assert "Kerkstraat" not in caplog.text


# ---------------------------------------------------------------------------
# check_response_shape — the pre-1.0 obligation
# ---------------------------------------------------------------------------


def test_check_response_shape_is_silent_on_a_known_payload(caplog):
    check_response_shape(delivered_sample())
    assert caplog.text == ""


def test_check_response_shape_reports_unknown_keys_once(caplog):
    raw = delivered_sample()
    raw["EstimatedDeliveryWindow"] = {"From": "20260429130000"}
    check_response_shape(raw)
    check_response_shape(raw)
    assert caplog.text.count("EstimatedDeliveryWindow") == 1


def test_check_response_shape_reports_a_full_response_without_order_data(caplog):
    """That would mean the two routes split their data differently than read."""
    check_response_shape(partial_sample())
    assert "OrderData" in caplog.text


# ---------------------------------------------------------------------------
# normalize_parcel — the canonical contract
# ---------------------------------------------------------------------------

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]


def test_normalize_publishes_exactly_the_canonical_keys():
    """The aggregator and cross-carrier dashboards depend on this key set."""
    assert list(normalize_parcel(delivered_sample())) == CANONICAL_KEYS


def test_normalize_delivered_parcel():
    parcel = normalize_parcel(delivered_sample())
    assert parcel["carrier"] == "Dynalogic"
    assert parcel["barcode"] == DELIVERED_CODE
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["raw_status"] == "DEL_DEF/4/0"
    assert parcel["delivered"] is True
    # No delivered-at field exists; the newest activity is the delivery.
    assert parcel["delivered_at"] == "2026-04-29T13:12:42+02:00"
    assert parcel["history"] is None  # opt-in, default off


def test_normalize_fields_this_carrier_does_not_expose_are_none():
    """Not oversights — see `normalize_parcel`'s docstring for each one."""
    parcel = normalize_parcel(delivered_sample())
    for key in ("sender", "receiver", "planned_from", "planned_to"):
        assert parcel[key] is None, key
    for key in ("pickup_point", "url", "weight", "dimensions"):
        assert parcel[key] is None, key
    assert parcel["pickup"] is False


def test_normalize_active_parcel():
    parcel = normalize_parcel(active_sample())
    assert parcel["barcode"] == ACTIVE_CODE
    assert parcel["status"] == ParcelStatus.OUT_FOR_DELIVERY
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None


def test_normalize_neighbour_delivery_is_delivered_and_keeps_the_scenario():
    parcel = normalize_parcel(neighbour_sample())
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["raw_status"] == "DEL_NB/4/0"


def test_normalize_failed_delivery_is_a_problem():
    assert normalize_parcel(failed_sample())["status"] == ParcelStatus.PROBLEM


def test_normalize_history_is_opt_in():
    parcel = normalize_parcel(delivered_sample(), include_history=True)
    assert len(parcel["history"]) == 4
    assert parcel["history"][-1]["timestamp"] == "2026-04-29T13:12:42+02:00"


def test_normalize_history_survives_a_response_without_order_data():
    parcel = normalize_parcel(partial_sample(), include_history=True)
    assert parcel["history"] == []


def test_normalize_pending_placeholder():
    """A tracked code the carrier 404s on still yields a full parcel dict."""
    parcel = normalize_parcel({"TrackAndTraceNumber": ACTIVE_CODE})
    assert parcel["barcode"] == ACTIVE_CODE
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["delivered"] is False
    assert parcel["raw_status"] is None


def test_normalize_keeps_raw_payload():
    raw = active_sample()
    assert normalize_parcel(raw)["raw"] is raw


# ---------------------------------------------------------------------------
# sort_parcels_by_ts
# ---------------------------------------------------------------------------


def test_sort_parcels_ascending_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "planned_from": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "planned_from": None},
        {"barcode": "c", "planned_from": "2026-05-01T10:00:00Z"},
    ]
    ordered = [p["barcode"] for p in sort_parcels_by_ts(parcels, "planned_from")]
    assert ordered == ["c", "a", "b"]


def test_sort_parcels_descending_still_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "delivered_at": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "delivered_at": "nonsense"},
        {"barcode": "c", "delivered_at": "2026-05-01T10:00:00Z"},
    ]
    ordered = [
        p["barcode"]
        for p in sort_parcels_by_ts(parcels, "delivered_at", descending=True)
    ]
    assert ordered == ["a", "c", "b"]


# ---------------------------------------------------------------------------
# apply_delivered_filter
# ---------------------------------------------------------------------------


def _entry(filter_type: str, amount: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        unique_id=DOMAIN,
    )


def _delivered_pair() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {"barcode": "RECENT", "delivered_at": (now - timedelta(days=1)).isoformat()},
        {"barcode": "OLD", "delivered_at": (now - timedelta(days=30)).isoformat()},
    ]


def test_delivered_filter_by_days():
    kept = apply_delivered_filter(_delivered_pair(), _entry("days", 7))
    assert [p["barcode"] for p in kept] == ["RECENT"]


def test_delivered_filter_by_count():
    parcels = _delivered_pair()
    assert apply_delivered_filter(parcels, _entry("parcels", 1)) == parcels[:1]


def test_delivered_filter_keeps_unparseable_timestamp():
    """Better to show a parcel with a broken date than to silently drop it."""
    parcels = [{"barcode": "WEIRD", "delivered_at": "nonsense"}]
    assert apply_delivered_filter(parcels, _entry("days", 7)) == parcels
