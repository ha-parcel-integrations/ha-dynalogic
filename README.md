# Dynalogic Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-dynalogic.svg)](https://github.com/ha-parcel-integrations/ha-dynalogic/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [Dynalogic](https://track.mydynalogic.eu) parcels. Dynalogic is a Benelux last-mile carrier, delivering in the Netherlands and Belgium. No account is needed — you enter the order number and the delivery postcode yourself, exactly as you would on their tracking page.

**You may be a Dynalogic customer without knowing it.** The same delivery network — and the same tracking — runs behind a number of consumer brands: MediaMarkt, Samsung, Nespresso (machinereparatie), Menken, Dynasure and Dynahealth. If your tracking link points at one of those sites, this integration tracks that parcel.

> **This is a pre-1.0 release.** Dynalogic publishes no documentation for the data it returns. This integration was built without a real parcel to check it against, and one user's report has since confirmed most of it — including a fix for a bug that was quietly throwing away every parcel's delivery history. What is still missing is the **delivery window**: the only response we have ever seen was of an already-delivered parcel, which does not carry one, so the *next delivery* sensor and the calendar stay empty for now. Anything the integration does not recognise is logged as a warning with a link to report it — those reports are what gets this to 1.0.

Part of the [ha-parcel-integrations](https://github.com/ha-parcel-integrations) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Dynalogic parcels by order number + postcode — no account needed
- Covers every brand on the same network (MediaMarkt, Samsung, Nespresso, Menken, Dynasure, Dynahealth)
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `out_for_delivery` / `delivered` / …), the sender and recipient, the carrier's own status fields and the delivery history
- Summary sensors: incoming parcels, next delivery, recently delivered parcels
- Read-only **Deliveries** calendar
- `dynalogic.track_parcel` / `dynalogic.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2024.12 or newer
- A Dynalogic order number (from the shipping confirmation or the tracking
  mail) **and** the postcode the parcel is being delivered to — no account
  needed. Dynalogic uses the postcode to prove you may see the parcel's
  details, so both are required.

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-dynalogic` as an **Integration**.
3. Install **Dynalogic** and restart Home Assistant.

### Manual

Copy `custom_components/dynalogic` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Dynalogic**. It asks for one thing: the postcode your parcels are delivered to. That becomes the default for every parcel you add, so you only type it once.

Then add parcels via the integration's **Configure** dialog, the [`dynalogic.track_parcel`](#services) action, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). A parcel going to a different address can carry its own postcode.

Adding a parcel checks it with Dynalogic straight away, so a mistyped order number or the wrong postcode is caught there rather than showing up as a parcel that never moves.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked order numbers. Changes apply immediately, no restart. |
| Parcels | Postcode | hub postcode | Only for a parcel delivered to a different address than the one you set up. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |
| Polling | Refresh every | 30 min | How often Dynalogic is checked. Slower is gentler on their API. |

## Removal

Standard HA removal applies: **Settings → Devices & Services → Dynalogic → ⋮ → Delete**. Nothing is stored on Dynalogic's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.dynalogic_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.dynalogic_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.dynalogic_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.dynalogic_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.dynalogic_last_successful_update` | Diagnostic: when Dynalogic was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

A **Deliveries** calendar entity is also created, showing expected delivery
dates for active parcels — read-only, no extra API calls. As noted above, it
stays empty until a captured payload confirms Dynalogic's delivery-window
field.

A **Refresh** button entity forces an immediate poll, without waiting for the
next scheduled interval.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family:

| Status | Meaning |
|---|---|
| `registered` | Announced / received by Dynalogic |
| `in_transit` | In the sorting network |
| `out_for_delivery` | With the courier |
| `delivered` | Delivered — including delivered to a neighbour |
| `returning` | Going back to the sender |
| `problem` | The delivery, pickup or swap failed |
| `unknown` | Not registered by Dynalogic yet, or a status we have not mapped |

Dynalogic never reports `at_pickup_point`: it delivers to the door.

Dynalogic does not send a status *text*. It reports which kind of job this is
(`Scenario`), how far along it is (`ActiveStep` 1–4) and a numeric result code,
so `raw_status` carries all three as `DEL_DEF/3/27`. Useful ones to recognise:
`DEL_NB` is a delivery to a neighbour (still `delivered`), anything ending in
`_FAIL` is a failed attempt, and `RS_` is a return.

## Events

The integration fires these on the event bus (also available as device triggers on the Dynalogic device):

| Event | When |
|---|---|
| `dynalogic_parcel_registered` | A new parcel appears in the active list |
| `dynalogic_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `dynalogic_parcel_delivered` | A parcel is delivered |
| `dynalogic_parcel_delivery_time_changed` | The expected delivery window changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `dynalogic.track_parcel` | `tracking_code`, `postal_code` (optional) | Start tracking a parcel |
| `dynalogic.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.dynalogic: debug
```

## Troubleshooting

- **A parcel shows `unknown`** — Dynalogic does not know that order number with that postcode (yet). The most common cause is a postcode that is not the delivery address; a parcel added through the Configure dialog is checked at that moment, one added through the action is not.
- **No delivery window, and an empty calendar** — Dynalogic's tracking API has no field for it that we have been able to identify. The only full response anyone has shared with us was of a parcel that had already been delivered, and those do not carry a window at all. **If you have a parcel that is still on its way, a diagnostics download from that entry is the single most useful thing you can send us** — it is what would give this integration its calendar. Download it from the integration's ⋮ menu → *Download diagnostics*; everything identifying is stripped out before it is written.
- **Warnings in the log** — expected below 1.0, and deliberate. Parts of Dynalogic's response have still never been seen, so the integration reports every assumption it makes: the response's structure (field names and types only, no values — safe to paste), each status combination it maps and what it made of it, an unrecognised scenario or result code, a timestamp it could not parse, and an order number the carrier does not know. Each is logged **once**, not every poll. Please [open an issue](https://github.com/ha-parcel-integrations/ha-dynalogic/issues/new?template=unrecognised_status.yml) with what you see — that is what gets this to 1.0. If you would rather not see them at all, `logger:` can silence `custom_components.dynalogic.parcels`.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://github.com/ha-parcel-integrations) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://github.com/ha-parcel-integrations) for the current list of supported carriers.

## Disclaimer

This integration uses the same public tracking endpoint as Dynalogic's own app. It is not affiliated with, endorsed by, or supported by Dynalogic or Dyna Group. Be gentle with the polling interval.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
