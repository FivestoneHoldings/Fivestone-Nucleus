# GateWay controlled-launch status — 2026-08-21

This is the evidence-backed handoff for the first real GateWay delivery. It is
not a roadmap and contains no credentials or customer data.

## Decision

**GO for one controlled cash-on-delivery order.**

**NO-GO for card payments or promised automatic SMS.** Stripe Connect and
Twilio remain intentionally disabled until provider onboarding, credentials,
reconciliation, and failure drills are complete.

## Verified production evidence

| Check | Result |
|---|---|
| Production release | `v1.10.10` · commit `fa3b8d0` |
| Automated verification | 754 tests passed on 2026-08-20 |
| Database | Railway PostgreSQL · up · durable |
| Restore/backup gate | Verified within the required seven-day window |
| Founder launch gate | Ready to take real orders · zero blockers |
| Active delivery queue | Clear; no stale received/confirmed/assigned/in-transit/failed tickets |
| Production errors after final deploy | 0 HTTP 5xx in the observed process metrics |
| Customer checkout | Server-priced, idempotent, cash-capable |
| Real kitchen catalog | Five real local kitchens with address, story, menu, pricing, and kitchen access |
| Preview kitchens | Five visibly labeled, read-only samples; server rejects order creation |
| Drivers | Two active driver records with newly rotated private day links |
| Driver shift workflow | On/off-shift control and live day/tip summary visible in Driver Hub |
| Merchant workflow | Quiet/active queue, accept, prep estimate, ready, pause, menu, hours, offers, posts |
| Command access | Clean `/board` session; secret absent from URL/history/referrer |
| Capability privacy | Command, driver, kitchen, proof, tracking and intake responses are no-store/no-index |
| Escalation | HQ phone and 9 AM–9 PM daily hours configured |

Five abandoned pre-launch assignments were cancelled with an explicit
`Pre-launch cleanup` reason. They were not deleted; the append-only audit log
retains all five cancellations. Both driver day links were rotated afterward,
and the old links are invalid.

## Known nonblocking launch gaps

- Both drivers still need a customer-facing profile: a face/avatar and vehicle
  make/model; vehicle color is strongly recommended. This does not block a
  controlled delivery, but should be completed before broad customer traffic.
- Automatic texts are unavailable. Dispatch must call/text manually from the
  configured HQ number during the cash pilot.
- Card payment is unavailable. Select **Pay at the door** and reconcile cash in
  Command after delivery.
- Restaurant-owned hero/menu photography has not been supplied. The live UI
  uses branded logos and designed monogram fallbacks; it does not borrow
  unlicensed food photography.

## Tomorrow: one-order operating sequence

1. Founder opens `/board`, runs **Launch readiness**, and confirms it is green.
2. Driver opens the newly rotated private Driver Hub link on the phone being
   used, completes **My profile**, and taps **OFF SHIFT — tap to start**.
3. Merchant opens its current private kitchen link, confirms menu/hours, and
   leaves ordering unpaused.
4. Customer chooses one of the five real kitchens, makes a small real cart,
   selects **Pay at the door**, and submits once.
5. Merchant accepts with a realistic prep estimate and marks the ticket ready.
6. Founder confirms/assigns the ticket in Command.
7. Driver verifies pickup and drop-off, taps **Picked Up**, navigates, captures
   proof, collects the displayed cash amount, and taps **Delivered**.
8. Founder opens the order timeline, verifies proof/status/cash, and closes it.
9. Confirm customer tracking says delivered and the event timeline contains
   received, accepted/confirmed, assigned, picked up, proof, delivered, closed.
10. Export the day CSV and retain the order ID and exception notes as launch evidence.

Stop and switch to phone/manual dispatch if any amount differs, a ticket does
not appear within one minute, a duplicate appears, a wrong driver sees it, or
PostgreSQL/Airtable becomes unavailable. Never delete a failed live ticket;
cancel or fail it with a reason and preserve the timeline.

## Inputs that still require the founder or driver

- Malcolm-Martin: chosen avatar/photo, vehicle make/model, vehicle color.
- Kyle Barrett: chosen avatar/photo, vehicle make/model, vehicle color.
- Which real kitchen, delivery address, and driver will be used for the first
  controlled order.
- Confirm the merchant and driver have received their current private links
  through a private channel; never paste those links into chat or screenshots.

The durable procedure remains in `docs/PATCH_LAUNCH_RUNBOOK.md`.
