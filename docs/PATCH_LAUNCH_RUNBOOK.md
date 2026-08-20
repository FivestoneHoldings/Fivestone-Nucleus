# Patch controlled-launch runbook

This runbook is the operational gate for the first real GateWay delivery.
It deliberately excludes roadmap features. A launch is successful when one
cash-on-delivery order completes safely through customer, kitchen, dispatch,
driver, tracking, proof, closeout, and the append-only event record.

## Production identity

- Repository: `FivestoneHoldings/Fivestone-Nucleus`
- Production branch: `main`
- Railway project: `GateWay Dispatch`
- Application service: `Fivestone-Nucleus`
- Database service: `Postgres-RITE`
- Production URL: `https://fivestone-nucleus-production.up.railway.app`
- Health endpoint: `/healthz`
- Founder surface: `/board/{individual-or-founder-key}`
- Merchant surface: `/kitchen/{merchant-token}`
- Driver surface: `/driver/{driver-token}`

Record the release commit, Patch version, deployment ID, and deployment time
in the launch evidence before every live drill. `/healthz` must return HTTP 200,
`ok: true`, the expected version, and `db: up`.

## Required configuration

The app refuses or degrades honestly when these are absent:

| Variable | Required for first cash delivery | Purpose |
|---|---:|---|
| `DATABASE_URL` | yes | Railway PostgreSQL connection |
| `AIRTABLE_PAT` | yes | Current canonical order/dispatch store |
| `ADMIN_KEY` | yes | Founder break-glass access |
| `OPS_DIGEST_KEY` | yes | Aggregate daily operations digest |
| `GATEWAY_HQ_PHONE` | yes | Human escalation for drivers |
| `GATEWAY_HQ_HOURS` | recommended | Honest dispatch availability |
| `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM` | recommended | Automatic customer SMS |
| `STRIPE_SECRET_KEY` | no | Card payments; remain off for cash pilot |
| `CUSTOMER_PROFILES_ENABLED` | no | Keep off until phone ownership is verified |

Never put a secret in source, chat, issue text, a screenshot, or a query string.

## Before the first order

1. Confirm Railway shows one healthy production application and one healthy
   PostgreSQL service.
2. Confirm a recoverable database backup exists. If Railway managed backups are
   unavailable, create and verify an encrypted manual `pg_dump` before live data.
3. Rotate every legacy driver and merchant bearer link. Deliver each replacement
   only to its owner. Old links must return 404.
4. Create one named dispatcher board key. Keep `ADMIN_KEY` founder-only.
5. Configure the HQ phone and hours. Test the driver call/text buttons.
6. Open the chosen merchant's go-live check. Resolve every blocking item:
   menu, prices, pickup address, accepting-orders state.
7. Confirm at least one active driver appears in Command and can open the Driver
   Hub on the phone that will be used.
8. Confirm `/api/diag` reports Airtable and founder access configured. Stripe may
   remain false for the controlled cash pilot.
9. Run the automated test suite and retain its pass count with the release SHA.

## Live delivery drill

Use a real reachable address, a real operator phone, a small order, and cash at
the door. Do not use a real card until Stripe and reconciliation are separately
approved and verified.

1. Customer opens the merchant storefront, creates the cart, confirms the
   displayed total, selects pay at door, and submits once.
2. Capture the new `ORD-…` identifier. A retry of the same checkout must return
   that same order, not create another.
3. Merchant receives the ticket, accepts it with a realistic prep estimate, and
   marks it ready.
4. Dispatcher confirms the order if needed and assigns an active driver.
5. Driver sees only their own assignment, verifies pickup/dropoff details, and
   marks picked up.
6. Customer tracking changes to in transit. Driver escalation contact is visible.
7. Driver captures proof for that exact assigned order and marks delivered.
8. Customer tracking changes to delivered and exposes the receipt/proof flow.
9. Dispatcher reviews the timeline, confirms cash collection, and closes the order.
10. Verify the append-only timeline contains received, accepted/confirmed,
    assigned, picked up, proof captured, delivered, and closed events with actors.

## Stop conditions

Pause the drill and use phone/manual dispatch if any of these occur:

- order submission returns an error or no order ID;
- merchant ticket does not appear within one minute;
- the order appears twice;
- a driver can see or mutate another driver's order;
- assignment, pickup, delivery, or proof targets the wrong order;
- tracking exposes another customer's information;
- database or Airtable is unavailable;
- the operator cannot reach the driver/customer by phone;
- the displayed total differs between checkout, driver cash due, and closeout.

Do not delete a failed order or event. Mark it failed/cancelled with a reason,
open a support/incident record, and preserve the timeline.

## Recovery

- Driver decline/failure: mark failed with reason, requeue, then assign another
  active driver.
- Kitchen cannot fulfill: cancel with a reason and contact the customer.
- Duplicate suspicion: stop one order before assignment; compare tracking ID,
  idempotency fingerprint, time, address, cart, and event history.
- Connectivity loss: operate by phone, record each transition when service
  returns, and do not invent timestamps.
- Database incident: stop new orders, preserve Airtable state, restore into a
  separate environment, reconcile counts, then reopen intake.

## Launch evidence

Retain: release SHA/version, Railway deployment ID/time, test result, backup
timestamp/restore check, variable-name inventory (never values), rotated-access
roster, go-live checks, drill order ID, lifecycle timeline, totals, exceptions,
and the explicit go/no-go decision.
