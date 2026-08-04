"""Sample Dynalogic API payloads shared by the test modules.

**These are reconstructions, not captures.** No populated `transportorder`
response has ever been observed: the field names come from the vendor's web
client, the endpoint's own OpenAPI document declares no success schema, and the
app's assets prove the real body carries more than this (a driver, stop
coordinates, a delayed live position). They are shaped the way the integration
expects, which makes them a test of the mapping — not evidence about the wire.

Replace them wholesale with a redacted real response as soon as one exists; the
whole point of keeping them in one module is that there is then exactly one
place to fix.
"""
from __future__ import annotations

ACTIVE_CODE = "1234567890"
DELIVERED_CODE = "9876543210"
POSTCODE = "1012AB"


def activity(executed: str, description: str) -> dict:
    """One entry of the order's own activity list."""
    return {"ExecutedDateTime": executed, "Description": description}


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """A completed delivery: last step, and the code the client calls done."""
    return {
        "TrackAndTraceNumber": code,
        "TransportResultCode": 0,
        "Scenario": "DEL_DEF",
        "ActiveStep": 4,
        "OrderData": {
            "Activities": [
                activity("20260429131242", "Afgeleverd"),
                activity("20260429084600", "Onderweg"),
                activity("20260428155217", "Gesorteerd in het depot"),
                activity("20260427230358", "Zending aangemeld"),
            ],
            "Addressee": {"PostalCode": POSTCODE, "CountryName": "Nederland"},
        },
        "ContactInformation": {"contact_email_address": "redacted@example.test"},
    }


def active_sample(code: str = ACTIVE_CODE) -> dict:
    """A parcel on the van: step 3, result code not yet the completed one."""
    sample = delivered_sample(code)
    sample.update({"TransportResultCode": 27, "ActiveStep": 3})
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


def partial_sample(code: str = ACTIVE_CODE) -> dict:
    """What the postcode-free route is understood to return: no OrderData.

    The integration never asks for this, but a `full` response arriving without
    `OrderData` is one of the pre-1.0 things it must complain about, and this is
    that response.
    """
    sample = active_sample(code)
    sample.pop("OrderData")
    return sample
