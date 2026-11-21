"""The parcel contract's checks, run over every normalised sample."""

from datetime import date, datetime

import pytest

from custom_components.dynalogic.const import ParcelStatus
from custom_components.dynalogic.parcels import (
    _CARRIER_TZ,
    normalize_parcel,
    parse_iso,
    planned_for_status,
    planned_window,
)

from .payloads import (
    active_sample,
    delivered_sample,
    failed_sample,
    neighbour_sample,
    partial_sample,
)

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


def _scenario(scenario: str) -> dict:
    sample = delivered_sample()
    sample["Scenario"] = scenario
    return sample


def _returned() -> dict:
    sample = _scenario("RS_DEF")
    sample["ActiveStep"] = 3
    return sample


SAMPLES = {
    "delivered": delivered_sample,
    "neighbour": neighbour_sample,
    "active": active_sample,
    "failed": failed_sample,
    "partial": partial_sample,
    "returning": _returned,
    "drop_off": lambda: _scenario("DP_DEF"),
    "bare": lambda: {"TrackAndTraceNumber": "1234567890"},
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return normalize_parcel(SAMPLES[request.param](), include_history=True)


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if parcel["delivered"]:
        assert parcel["delivered_at"] is not None
    else:
        assert parcel["delivered_at"] is None


def test_planned_window_is_ordered_and_anchored(parcel):
    if parcel["planned_to"] is not None:
        assert parcel["planned_from"] is not None
        assert parse_iso(parcel["planned_to"]) > parse_iso(parcel["planned_from"])


def test_planned_is_empty_when_the_parcel_is_done_or_waiting(parcel):
    if parcel["status"] in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None


def test_pickup_is_constant_false_and_the_point_is_empty(parcel):
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None


def test_a_returning_parcel_is_not_delivered():
    parcel = normalize_parcel(_returned())
    assert parcel["status"] is ParcelStatus.RETURNING
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None


def test_a_moment_ends_at_the_end_of_that_day():
    start, end = planned_window("2099-04-29T13:00:00", None, zone=_CARRIER_TZ)
    assert start == "2099-04-29T13:00:00+02:00"
    last = datetime.fromisoformat(end)
    assert (last.hour, last.minute, last.second, last.microsecond) == (23, 59, 59, 0)
    assert last.date() == date(2099, 4, 29)
    assert last.utcoffset() == datetime.fromisoformat(start).utcoffset()


def test_a_utc_moment_ends_on_the_carrier_day():
    _, end = planned_window("2099-04-29T22:30:00Z", None, zone=_CARRIER_TZ)
    assert datetime.fromisoformat(end).date() == date(2099, 4, 30)


def test_a_date_covers_the_whole_day():
    start, end = planned_window("2099-04-29", None, zone=_CARRIER_TZ)
    first = datetime.fromisoformat(start)
    last = datetime.fromisoformat(end)
    assert (first.hour, first.minute, first.second) == (0, 0, 0)
    assert (last.hour, last.minute, last.second, last.microsecond) == (23, 59, 59, 0)
    assert first.date() == last.date()


def test_the_window_is_emptied_for_a_parcel_at_its_destination():
    window = planned_window("2099-04-29", None, zone=_CARRIER_TZ)
    assert planned_for_status(ParcelStatus.OUT_FOR_DELIVERY, *window) == window
    for status in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert planned_for_status(status, *window) == (None, None)
