# Automatic parcel tracking from e-mail (IMAP → Dynalogic)

Companion guide for [`track_parcels_from_email.yaml`](track_parcels_from_email.yaml): watch your mailbox(es) for shipping e-mails, extract the Dynalogic tracking code, and register it with `dynalogic.track_parcel` — fully automatic, no extra custom component required.

Dynalogic is a **code-based** carrier: it has no account inbox, so every parcel must be registered by its order number before the integration can follow it. This recipe automates exactly that step.

**How it works, in one line:** the core [IMAP integration](https://www.home-assistant.io/integrations/imap/) fires an `imap_content` event for every new e-mail (including the body); the automation extracts the order number — a cheap regex first, an optional AI fallback for everything else — and calls `dynalogic.track_parcel`.

```
new e-mail ──imap_content──▶ automation ──▶ regex match? ──▶ dynalogic.track_parcel
                                     │
                                     └──▶ no match, but looks like a shipping mail
                                          ──▶ ai_task.generate_data (optional)
                                              ──▶ tracking code
```

## Prerequisites

- This integration, with the `dynalogic.track_parcel` action available (fields `tracking_code` and the optional `postal_code`).
- The core **IMAP** integration (ships with Home Assistant, no HACS needed).
- *(Optional but recommended)* an **AI Task** entity (e.g. Anthropic/Claude, Google, OpenAI) for the fallback path. Without it, simply delete the `else:` block — the regex path works standalone.

## Step 1 — IMAP entries

Add **Settings → Devices & services → Add integration → IMAP** for every account you want to watch:

| Field | Value |
|---|---|
| Server | `imap.gmail.com` (Gmail) — mind the hostname, it is **not** `imap.google.com` |
| Port | `993` |
| Username | your address |
| Password | see the Gmail note below |
| Charset | `utf-8` |
| Folder | `INBOX` (or a label/subfolder — see below) |

Then open the entry's **Configure** (options) and set:

- **Message data to include in the event**: enable **text** (the automation needs the body!)
- **Max message size**: raise it to `30000` — carrier mails are long and the default cuts them off before the tracking code appears.
- *search*: `UnSeen UnDeleted` works, but **scoping it to the carrier's sender is recommended** — see [Scope & privacy](#scope--privacy) below. Keep *push* enabled (IMAP IDLE → events arrive within seconds).

**Multiple mailboxes / accounts:** each IMAP entry is one account × folder combination. Add the same account again with a different folder to watch labels (Gmail labels appear as IMAP folders). All entries fire the *same* `imap_content` event, so **one automation covers all of them**.

**Gmail note:** since May 2025 Google blocks plain-password IMAP logins ("less secure apps"). Use an **app password** instead (requires 2-step verification): <https://myaccount.google.com/apppasswords>.

## Scope & privacy

By default this recipe is broad. The core IMAP integration fires an
`imap_content` event — **including the full message body** — for *every* new
mail its *search* matches, and the automation reacts to **all** of those events.
With the default `search: UnSeen UnDeleted` that means every incoming e-mail
runs through the automation's templates, and — if you keep the AI fallback —
every mail passing the keyword gate has up to 6000 characters of its body sent
to your AI Task, **possibly a cloud model**.

None of that data leaves through *this* integration — it only exposes the
`track_parcel` action. The mailbox access and the event stream belong to Home
Assistant's **core IMAP integration**, using the username / app-password you
gave it — which grants full read access to your **entire** mailbox, not just
parcel mail. So it is worth narrowing what it ever sees.

Narrow it at the source (most effective first):

1. **Scope the IMAP `search` to the carrier's sender.** In the IMAP entry's
   options, e.g. `search: FROM "noreply@thecarrier.example" UNSEEN` (chain
   several with `OR`: `OR FROM "a@x" FROM "b@y" UNSEEN`). Only matching mail
   ever becomes an event, so the automation — and the AI — never see the rest.
2. **Or point the entry at a dedicated folder/label.** Add a server-side mail
   rule that files shipping notifications into e.g. a `Parcels` label, and set
   the IMAP entry's *Folder* to it. Same effect, and it survives sender changes
   better.
3. **Add a sender allowlist** as an extra automation `condition` — defense in
   depth if you keep a broad search.
4. **Drop the AI fallback** (delete the `else:` block) if you want *no* body
   text to leave Home Assistant; the regex path is fully local.

## Step 2 — the automation

Paste [`track_parcels_from_email.yaml`](track_parcels_from_email.yaml) and adapt the notify action, the keyword list and the AI entity to your setup.

### Order-number formats — the honest version

**Dynalogic publishes no order-number format.** There is no prefix, no fixed
length, and neither its website nor its app validates one. So unlike the other
carriers in this family, this recipe cannot recognise a Dynalogic code by
looking at it — a pattern loose enough to catch every real order number would
also catch every invoice and customer number in the mail.

It works in two stages instead:

1. **Is this a Dynalogic mail at all?** The mail has to mention one of the
   tracking hosts: `mydynalogic.eu`, `dynagroup.nl`, or a brand host
   (`track-en-trace.mediamarkt.nl`, `samsung.dynalogic.eu`, `mymenken.eu`,
   `dynasure.eu`, `mydynahealth.eu`, `dynalogic.machinereparatie.eu`). Dynalogic
   delivers for all of those, so a MediaMarkt or Samsung mail is a Dynalogic
   mail.
2. **Then take a labelled number** — one that follows *ordernummer*, *order
   number*, *zendingsnummer* or *tracking*. Add the label your own mails use.

Everything else is the AI fallback's job, and on this carrier it does more of
the work than it does elsewhere. If your mails have a recognisable pattern,
please share it in an issue — a real format would make this recipe much sharper.

### The postcode

`dynalogic.track_parcel` takes an optional `postal_code` and falls back to the
one you entered when setting the integration up, so the automation never needs
to know your address. Only add the field if the parcel goes somewhere else.

Note that a parcel added through the action is **not** verified against
Dynalogic (unlike one added through the Configure dialog): if the order number
is wrong, the parcel simply sits at `unknown`. That is deliberate — a mail often
arrives before the carrier has registered the order.

### Design notes

- **Brand gate first, then regex, then AI.** Because Dynalogic has no code format, the brand-host check is what keeps the regex from firing on unrelated mail. The AI fallback earns more of its keep here than on other carriers.
- **Duplicates are harmless:** calling `track_parcel` twice for the same code is a no-op, and the `initial` condition already suppresses re-triggers of the same message.
- **`mode: queued`** so a burst of mails (mailbox sync) is processed one by one instead of being dropped.

## Pitfalls we hit so you don't have to

1. **Jinja eats backslashes in string literals.** A template stored as `regex_findall('\bOrdernummer…')` silently becomes a **backspace character** (`\b` is a string escape), so the regex never matches — no error anywhere. That's why the patterns here are backslash-free: character classes such as `[0-9]` instead of `\d`, lookarounds instead of `\b`. Copy that style if you add a label.
2. **The `initial` event flag means the opposite of what you might expect.** In the IMAP integration `initial: true` = *first time this message is seen* (new mail); `false` = a duplicate trigger of the same message. So the condition must **require** `initial`, not exclude it.
3. **Raise the max message size.** With the default the body is truncated before the tracking code appears in most carrier mails. `30000` is plenty.
4. **Enable "text" in the event options.** Without it the event has headers only and there is nothing to extract.
5. **Gmail = app password.** Plain passwords stopped working on Google IMAP in May 2025; app passwords (with 2FA) are the supported route. And the host is `imap.gmail.com`.

## Testing without waiting for a real parcel

Fire a fake event and watch the automation trace (Settings → Automations → your automation → Traces):

```bash
curl -X POST -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" \
  http://YOUR_HA:8123/api/events/imap_content \
  -d '{"sender":"noreply@mydynalogic.eu","subject":"Your parcel is on its way",
       "text":"Ordernummer: 1234567890 — volg je zending op https://track.mydynalogic.eu/",
       "initial":true,"folder":"INBOX","username":"test"}'
```

Then `dynalogic.untrack_parcel` the test code afterwards. For a full end-to-end test, forward a real shipping mail to the watched mailbox — it must arrive **unread**.
