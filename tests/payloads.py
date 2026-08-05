"""Sample Dynalogic API payloads shared by the test modules.

**This is a real capture, redacted.** A populated `full` response was captured
on 2026-08-05 — one completed bol.com delivery — and these fixtures are shaped
from it rather than from the reconstruction that preceded it. The redacted copy
and the field-by-field notes live in `carrier-research/api/dynalogic/`.

What the capture settles, and what it does not:

* **Settled** — the top-level key set (ten keys the reconstruction never saw),
  `ExecutedDateTime` being naive ISO 8601 and *not* `YYYYMMDDHHmmss`, the
  activity description living under `Description`, `OrderData.CustomerName`
  being the shipper, and `DEL_DEF`/4/0 meaning delivered. A day later
  (2026-08-06) the *same* order arrived again as the raw sensor attributes
  rather than as diagnostics — diagnostics redact, the sensor's `raw` attribute
  does not — which settled the two blocks the first copy had blanked whole:
  `OrderData.Addressee` and `ContactInformation`.
* **Not settled** — everything an order carries while it is still *moving*. The
  captured order was already delivered, so `TransportProgress` was `null`, there
  was no delivery-window field, and no driver position. `active_sample` below is
  therefore still a construction: it is the delivered capture wound back, not an
  observed in-transit body.

Every identifier is substituted (see `_CUSTOMER_ORDER_NUMBER` and friends) and
every personal block is blanked, per the research repo's redaction rules.
"""
from __future__ import annotations

ACTIVE_CODE = "1234567890"
DELIVERED_CODE = "9876543210"
POSTCODE = "1012AB"

# Substituted for the captured order's real identifiers. The physical parcel
# barcode opens with the shipper's Dynalogic customer id followed by (most of)
# the shipper's own order number; on the one order seen unredacted it is also
# byte-for-byte the `TrackAndTraceNumber` the user types in. They are kept
# *distinct* here on purpose — the integration reads the order number from
# `TrackAndTraceNumber`, and a fixture where both spellings hold the same value
# could not tell a correct read from a lucky one.
_CUSTOMER_ID = 18987                       # bol.'s account with Dynalogic
_CUSTOMER_ORDER_NUMBER = "00000000001"
_BARCODE = f"{_CUSTOMER_ID}{_CUSTOMER_ORDER_NUMBER}"

# The addressee block is personal data, so the diagnostics capture had it
# redacted whole. Its shape came from a user's sensor state on 2026-08-06: an
# object, with the recipient's name on `Name1`. Values are substituted, keys are
# the real ones. `_receiver` still handles a scalar too and the fixtures exercise
# both — one shipper's fill-in is not the whole vocabulary.
ADDRESSEE = "A. Bewoner"
ADDRESSEE_BLOCK = {
    "Company": ADDRESSEE,
    "Name1": ADDRESSEE,
    "Name2": "",
    "Name3": "",
    "Name4": "",
    "Street": "Teststraat",
    "HouseNumber": "1",
    "HouseNumberAddition": "",
    "PostalCode": "1012 AB",
    "City": "Amsterdam",
    "CountryName": "Nederland",
    "EmailAddress": "a.bewoner@example.invalid",
    "Phone1": "0600000000",
    "Phone2": "",
    "Phone3": "",
    "Phone4": "",
}

# The carrier's *own* contact desk — not the recipient's details. Shape observed
# alongside the addressee block; diagnostics still redact it whole, because the
# cost of that is nil and it is per-order.
CONTACT_INFORMATION = {
    "WhatsAppPhoneNumber": "31600000000",
    "ContactEmailAddress": "afspraak@dynalogic.eu",
    "ComplaintEmailAddress": None,
    "ContactPageUrl": None,
    "ContactEmailOpening": None,
    "OpeningHours": [
        {
            "Weekday": "Monday",
            "IsOpened": True,
            "OpenedFrom": "08:30:00",
            "OpenedTo": "20:30:00",
        },
        {
            "Weekday": "Sunday",
            "IsOpened": False,
            "OpenedFrom": None,
            "OpenedTo": None,
        },
    ],
    "PhoneNumbers": [],
    "WhatsappNumbers": [],
}


def activity(executed: str, description: str) -> dict:
    """One entry of the order's own activity list.

    `RefundStatusId` rides along because the real ones carry it; it is `None` on
    every activity seen so far and nothing reads it.
    """
    return {
        "ExecutedDateTime": executed,
        "Description": description,
        "RefundStatusId": None,
    }


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """A completed delivery — the captured response, with identifiers swapped."""
    return {
        "OrderData": {
            "OrderId": 10000001,
            "OrderNumber": 100000002,
            "CustomerOrderNumber": _CUSTOMER_ORDER_NUMBER,
            "OrderKindDescription": "Bol.com 1XL Afleveropdracht Drempel Service",
            "OrderTypeDescription": "Bezorging",
            "CodAmount": 0.0,
            "CustomerName": "bol.",
            "CustomerLogoGuid": "00000000-0000-0000-0000-000000000000",
            "CustomCarIconUrl": (
                "https://track.mydynalogic.eu/assets/img/dynalogic"
                "/map-icons/bolcom_right.svg"
            ),
            "DriverId": 10001,
            "DriverName": "R. Chauffeur",
            "DriverBadgeNumber": None,
            "Addressee": dict(ADDRESSEE_BLOCK),
            "Activities": [
                activity("2026-08-04T13:34:10.507", "Opdracht succesvol uitgevoerd"),
                activity(
                    "2026-08-04T09:12:21.1",
                    "Onze medewerker is begonnen aan de route",
                ),
                activity(
                    "2026-08-04T04:55:54.49",
                    "De route is klaargemaakt voor onze medewerker",
                ),
                activity("2026-08-04T04:55:54.33", "Uw zending is door ons ontvangen"),
                activity(
                    "2026-08-03T23:33:36.097",
                    "Afspraak gepland voor dinsdag 4 augustus tussen 8:00u en 22:00u",
                ),
                activity(
                    "2026-08-03T23:33:36.043",
                    "De transportdata is bij ons aangemeld door de opdrachtgever",
                ),
            ],
            "OrderLines": [
                {
                    "LineNumber": 1,
                    "Direction": "Delivery",
                    "ItemDescription": "Consumer goods",
                    "Barcode": _BARCODE,
                }
            ],
            "TransportConditions": [
                {
                    "Id": 5,
                    "Name": "Niet bij buren",
                    "Description": (
                        "Als u afwezig bent mogen we niet bij een van de buren "
                        "leveren."
                    ),
                    "TypeId": 1,
                    "InstructionUri": None,
                }
            ],
        },
        "OrderGroup": None,
        "ContactInformation": dict(CONTACT_INFORMATION),
        "TrackAndTraceNumber": code,
        "OnlineAppointmentEnabled": 0,
        "Scenario": "DEL_DEF",
        "CustomerId": _CUSTOMER_ID,
        "TransportResultCode": 0,
        "ActiveStep": 4,
        "DetailCaption": "Succesvol bezorgd",
        "DetailTextLine1": "",
        "DetailTextLine2": (
            "We hebben de zending op dinsdag 4 augustus succesvol bezorgd."
        ),
        "ProgressData": [
            {"StepNumber": step, "Status": 1, "Overlay": 0} for step in range(1, 5)
        ],
        "TransportProgress": None,
        "PushNotificationsEnabled": False,
        "OrderStatusForAddressee": "COMPLETED",
    }


def active_sample(code: str = ACTIVE_CODE) -> dict:
    """A parcel on the van: step 3, result code not yet the completed one.

    **Constructed, not captured** — no in-transit response has been seen. The
    delivery-completed activity is dropped and the two status fields wound back,
    which is what the shape of the delivered capture implies but does not prove.
    A real one is expected to carry *more*, not less: a delivery window, and a
    non-null `TransportProgress`.
    """
    sample = delivered_sample(code)
    sample.update(
        {
            "TransportResultCode": 27,
            "ActiveStep": 3,
            "DetailCaption": "Onderweg",
            "DetailTextLine1": "",
            "DetailTextLine2": "Uw zending is vandaag onderweg.",
            # Deliberately left at the one value we have ever seen: the domain
            # of this field is unknown, and inventing an "IN_TRANSIT" here would
            # put a fabricated carrier value in a fixture.
            "OrderStatusForAddressee": "COMPLETED",
            "ProgressData": [
                {"StepNumber": step, "Status": 1 if step <= 3 else 0, "Overlay": 0}
                for step in range(1, 5)
            ],
        }
    )
    sample["OrderData"] = dict(sample["OrderData"])
    sample["OrderData"]["Activities"] = sample["OrderData"]["Activities"][1:]
    return sample


def neighbour_sample(code: str = DELIVERED_CODE) -> dict:
    """Delivered to a neighbour — a separate scenario, not a separate code."""
    sample = delivered_sample(code)
    sample["Scenario"] = "DEL_NB"
    return sample


def failed_sample(code: str = ACTIVE_CODE) -> dict:
    """A failed delivery attempt: the scenario itself carries the failure."""
    sample = active_sample(code)
    sample["Scenario"] = "DEL_FAIL"
    return sample


def addressee_scalar_sample(code: str = DELIVERED_CODE) -> dict:
    """The delivered capture with `Addressee` as a bare string.

    The observed block is an object (see `ADDRESSEE_BLOCK`, which is what
    `delivered_sample` carries), but the field *name* reads like a scalar and
    one shipper's fill-in is not the whole vocabulary, so `_receiver` keeps
    handling both and this exercises the other branch.
    """
    sample = delivered_sample(code)
    sample["OrderData"] = dict(sample["OrderData"])
    sample["OrderData"]["Addressee"] = ADDRESSEE
    return sample


def partial_sample(code: str = ACTIVE_CODE) -> dict:
    """What the postcode-free route is understood to return: no OrderData.

    The integration never asks for this, but a `full` response arriving without
    `OrderData` is one of the pre-1.0 things it must complain about, and this is
    that response.
    """
    sample = active_sample(code)
    sample.pop("OrderData")
    return sample
