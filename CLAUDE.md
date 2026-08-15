# Working in this repository

Home Assistant custom integration for **Dynalogic** parcel tracking.
Distributed via HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
No DTO layer.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — exact key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| ship anything while below 1.0.0 (unconfirmed data) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed shape/code |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client, sync requests) | *Deliberate skill divergences* — likely intentional, don't re-flag |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).

## Carrier-specific notes

**API mechanics live in `carrier-research/api/dynalogic/` (private research
repo)** — the keyless middleware, the two `transportorder` routes, what the
postcode actually does, the AES-token route we do not use, the status key
domains and the payload reconstruction. Do not duplicate them here.

### The thing to know before changing anything

**Exactly one populated response has ever been observed** — a *delivered* order,
captured 2026-08-05 from a user's diagnostics and **completed 2026-08-06 from
the same order's raw sensor attributes** (diagnostics redact, the sensor's `raw`
attribute does not, so the second copy carried the `Addressee` and
`ContactInformation` blocks the first had blanked whole). Redacted into
`carrier-research/api/dynalogic/response-full-delivered.json` and into
`tests/payloads.py`. It corrected two things 0.9.0 asserted:

- **`ExecutedDateTime` is naive ISO 8601** (`2026-08-04T13:34:10.507`), not
  `YYYYMMDDHHmmss`. 0.9.0 accepted only the compact form and therefore dropped
  *every* timestamp a real order carried — no history, no `delivered_at`, on
  every parcel. The compact form is still accepted (the web client handles it);
  neither carries a zone.
- **The carrier does ship status text.** `DetailCaption` ("Succesvol bezorgd"),
  `DetailTextLine2`, and a machine-readable `OrderStatusForAddressee`
  ("COMPLETED"). `raw_status` stays the `DEL_DEF/4/0` triple anyway — the prose
  is localised and the triple keeps the scenario — but the *reason* recorded in
  0.9.x ("Dynalogic ships no status text at all") was simply wrong.

**The capture was of a delivered order, which is why the expensive gaps are
still open**: `TransportProgress` was `null`, there is no delivery-window field
anywhere, and the driver position and map pins the app renders are still unseen.
An **in-transit capture** is the one thing left worth asking for. So:

- **Do not extend `normalize_parcel` by guessing a field name.** Four canonical
  keys are `None` on purpose and the docstring says why for each:
  `planned_from`, `planned_to`, `pickup_point`, `url`. (`sender` and `receiver`
  were the other two until the capture named `OrderData.CustomerName` and
  confirmed `OrderData.Addressee`.) Reflected in `const.py`'s `CAPABILITIES`
  (feeds the docs site's comparison table) — keep the two in agreement if that
  ever changes.
- **`Addressee` is an object and the name is on `Name1`** (observed 2026-08-06;
  `Company` is the fallback, since on a business delivery that is the firm and
  `Name1` the person). 0.9.x looked for `Name`/`FullName`/`ContactName` — none
  of which exist — so it published `receiver: None` on *every real parcel*; its
  `addressee_shape` warning is what surfaced that. `_receiver` still handles a
  scalar and still reports the keys of an object it cannot find a name in.
- **`barcode` is the order number**, read from `TrackAndTraceNumber`. 0.9.x said
  the capture proved it differs from `OrderLines[].Barcode`; that was an artifact
  of the redaction substituting the two independently — on the wire they are the
  same value. Keep reading `TrackAndTraceNumber` anyway: it is what the user
  typed, what the sensor's unique id is built from, the only one of the two on a
  404 placeholder, and a multi-line order has several barcodes and one number.
- **Every assumption warns once** through `parcels._warn_once`, keyed so the
  different kinds cannot mask each other. The set *is* the pre-1.0 obligation
  for this carrier — do not quiet one without replacing it with a real answer:
  - `report_structure` — the whole payload as `path: type` lines, keyed on the
    shape itself so a delivered parcel reports separately from an in-transit
    one. **This is the one that matters**: it is what will name the delivery
    window and the driver. Types only, so it is safe for a user to paste.
  - `_report_combination` — every distinct `Scenario`/`ActiveStep`/
    `TransportResultCode` triple with the status we made of it. The only route
    to the meaning of the 15 undocumented result codes, and the reason the
    issue template asks what the carrier's own app showed at that moment.
    Triples in `CONFIRMED_COMBINATIONS` are skipped — currently just
    `DEL_DEF`/4/0, which the capture settled three ways over. **Add to that set
    only from a capture**, never from reasoning; its whole value is "seen".
  - `check_order_status` — collects `OrderStatusForAddressee` values. One is
    known. It is the best candidate to replace the three-field reading outright
    one day, which is why it is being collected rather than acted on.
  - `report_unknown_parcel` — a 404, once per order number, spelling out the
    three causes. Without it a wrong postcode is a parcel stuck on `unknown`
    with no explanation.
  - plus: unknown scenario, unknown result code, out-of-range step, a
    timestamp that is not `YYYYMMDDHHmmss`, an activity with no recognised
    description, unexpected top-level keys, a missing status field, a `full`
    response without `OrderData`, and an empty `Activities` list.
- `check_response_shape` runs in the **coordinator**, on real responses only.
  The 404 placeholder is ours and has no shape to complain about.

### Status is three fields, not one

`Scenario` (job type, 13 closed values) × `ActiveStep` (1–4) ×
`TransportResultCode` (16 values, only `0` understood = complete). The mapping
leans on the step and treats a non-zero code as "not finished". Decisions worth
keeping:

- **`DEL_NB` (neighbour) maps to plain `delivered`**, like DHL-NL's
  `DELIVERED_AT_NEIGHBOURS`. The canonical vocabulary has one delivered state;
  the distinction survives on `raw_status` and in `raw`.
- **`*_FAIL` outranks the step** → `problem`. **`RS_DEF` is `returning`** even
  once complete: there is no canonical "returned".
- **`raw_status` is `"DEL_DEF/3/27"`**, not prose. The carrier *does* ship prose
  (`DetailCaption`) — 0.9.x claimed otherwise and was wrong — but it is
  localised Dutch, while the triple is complete, stable and keeps the scenario
  the canonical status flattens away. The prose rides in `raw`.
- Swap / correction / repair jobs (`SW_*`, `COR_*`, and the `machinereparatie`
  brand) currently become parcels like any other. Whether they should be
  filtered out is an open scope question, not a mapping detail — the first real
  orders force it.

### Postcode = a second factor, not a lookup key

- **`full` (code + postcode) is the only route polled.** The postcode-free
  `partial` route returns no `OrderData`, and `OrderData.Activities` is the only
  source of history and timestamps. A status-only degraded mode would mean
  specifying a payload nobody has seen — the exact thing being avoided here.
- **The hub asks the postcode once** and each parcel stores its own
  (`{tracking_code, postal_code}`), so a delivery to another address works
  without a second entry. `single_config_entry` stays: the postcode is per
  parcel, so a second hub would buy nothing.
- **Adding a parcel in the options flow costs one request**, on purpose: a wrong
  postcode is otherwise invisible until the parcel never moves. The
  `track_parcel` action deliberately does *not* — an automation reacting to a
  mail must not lose a code the carrier has not registered yet.
- **`partial` is not implemented.** It would separate "unknown order number"
  from "wrong postcode" in the config flow, but that truth table is read off
  route semantics and no real order has exercised it. `api.py` carries the note
  and `const.TRACKING_API_PARTIAL_URL` is ready.
- **Never implement `full/ordernumber/{token}`** — a server-side AES decrypt.
  That is how e-mailed links authorize themselves; it cannot be constructed and
  there is no key to ship.
- **`POSTCODE_RE` accepts NL (4 digits + 2 letters) and BE (4 digits, no
  letters) shapes** — Dynalogic is legally "Dynalogic BeNeLux B.V." and
  delivers in both countries, not NL-only as earlier revisions assumed. The
  API itself does not care about country; this is still just our own
  typo guard, so a bare 4-digit BE code and a 4+2 NL code both pass.

### Other integration decisions

- **Timestamps carry no offset and are read as Europe/Amsterdam — confirmed,
  and nothing contradicts it.** The captured order's delivery activity is stamped
  13:34 and the recipient put the real delivery at about 13:30; UTC would have
  made it 15:34. 0.9.x recorded one apparent counter-example — *"Afspraak gepland
  voor **vandaag**"* stamped 23:33 the day *before* the window it announces —
  and explained it away as a sloppy template. The unredacted payload shows the
  activity says *"voor **dinsdag 4 augustus**"*: it names the day and is exactly
  right. The "vandaag" was introduced by date-substituting free text while
  redacting. `_CARRIER_TZ` is built once at import — never per timestamp, and
  never in the event loop.
- **`delivered_at` is the newest activity's timestamp**, because no
  delivered-at field exists. Inferred, and the capture did not contradict it.
- **One integration covers eight brands.** The tracking routes take no brand
  parameter. Do not build brand variants and do not derive the host from a
  brand — target `api.dynagroup.nl` directly.
- **Diagnostics redact whole blocks** (`Addressee`, `ContactInformation`,
  `TransportConditions`), not leaves: the leaves we do not know the names of are
  exactly the ones a per-leaf list would miss. **`async_redact_data` matches
  keys case-sensitively**, so every carrier PascalCase spelling needs listing
  next to our snake_case one — the capture arrived with `barcode` redacted while
  `OrderData.OrderLines[].Barcode` and `CustomerOrderNumber` went out in the
  clear, which is exactly the failure mode. Adding a key is cheap; test it.
- **Rate limiting is unknown** (a few dozen probes, nothing observed), which is
  why the interval stays user-visible and the default gentle. If reports of
  throttling arrive, this is a `--interval fixed` carrier.

## Options and reloads

The options flow is one sectioned form (`data_entry_flow.section`); changes apply
without a restart. Two models, **do not mix them**:
- **Account-less carriers** (the default) apply changes live: an update listener
  retunes `coordinator.update_interval` and calls `async_request_refresh()`, so
  added/removed parcel sensors appear immediately.
- **Account-based carriers** call `async_schedule_reload` on submit and register
  **no** update listener. Combining a listener with a reload-on-update flow is
  deprecated, an error in HA 2026.12+.

The user-tunable poll interval is a deliberate HACS divergence (see
CONVENTIONS.md); a carrier that throttles is generated with a fixed cadence and no
polling option at all.

## Module layout

| File | Carrier-specific? |
|---|---|
| `api.py` (HTTP client, error types) | **yes** |
| `const.py` (domain, URLs, `ParcelStatus`, option keys) | partly (URLs) |
| `parcels.py` (status map, `normalize_parcel`, history, sort, filters — pure, no I/O) | partly (`_STATUS_MAP`, `normalize_parcel`) |
| `coordinator.py` (fetch, cache, event firing) | mostly not |
| `config_flow.py` | partly (code validation) |
| `sensor.py` / `button.py` / `calendar.py` / `device_trigger.py` | no |
| `diagnostics.py` | partly (`TO_REDACT`) |
| `services.py` (`track_parcel` / `untrack_parcel`, account-less only) | no |

`parcels.py` is deliberately free of I/O and HA objects so the per-carrier part
stays unit-testable without Home Assistant. Config: `ConfigEntry.runtime_data`
(typed, no `hass.data`), `PARALLEL_UPDATES = 0`, coordinator takes
`config_entry=entry`. `aiohttp.ClientError` is caught **per parcel** in the gather
loop (one bad parcel doesn't fail the poll) but **not** around the whole update
(the coordinator wraps that). Entities: `has_entity_name` + `translation_key`,
`icons.json`, translated units, `_attr_attribution`, `_unrecorded_attributes` on
anything with a parcel list or `raw`. Over-redact diagnostics — they get pasted
into public issues.

## Running tests

```
python -m pytest tests/ --cov=custom_components.dynalogic
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; the API reference lives in this carrier's directory under the private
`carrier-research/api/`, never in this repo.
