# Patch Money Control

**Status:** Foundation implemented; live charging disabled pending Stripe account configuration and launch approval.

## Non-negotiables

1. Patch never trusts a browser for a price, discount, tax, fee, tip, or payout amount.
2. Every external payment attempt has an idempotency key, so a refresh or retry cannot create a second charge.
3. Every provider webhook is stored once before it changes a money state.
4. Every financial event is represented by balanced integer-cent ledger entries. An unbalanced entry is rejected.
5. The Patch ledger is the operating record; Stripe is the payment processor and settlement source. Reconciliation compares them daily.
6. Tips, sales tax, partner proceeds, Patch revenue, processor costs, refunds, disputes, and payouts are separate allocations—never one vague "net" number.

## Current state

- Cash at delivery is the only active customer payment method.
- No Stripe API key, webhook secret, or Connect account is configured in Railway.
- The code now contains the owned database tables and tested primitives for payment attempts, ledger entries, and one-time webhook receipts.
- Card payments remain disabled until the full Stripe Connect flow and operational reconciliation are proven in a non-production test mode.

## Launch sequence

1. Create/confirm the Patch Stripe platform account and business profile.
2. Select a Connect onboarding model; use Stripe-hosted or embedded onboarding so Patch never handles partner banking identity documents.
3. Configure limited, encrypted Railway secrets: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, publishable key, and environment mode. Never place these in Git, Make, or client-side code.
4. Create a Stripe test-mode partner account and test orders covering charge, cancellation, partial refund, full refund, tip, payout, failed card, repeated browser submit, and repeated webhook delivery.
5. Set the business rules for service fee, delivery fee, sales tax, tip ownership, discount funding, refund authority, dispute reserve, and payout schedule.
6. Build the server-side PaymentIntent endpoint and signed webhook endpoint; enable card selection only after the test suite and reconciliation report pass.
7. Complete Tennessee marketplace/tax review, Stripe production activation, and first-partner controlled launch.

## Required allocation on every card order

| Allocation | Owner / purpose |
|---|---|
| Goods subtotal | Partner payable |
| Sales tax | Tax payable until remitted |
| Delivery fee | Patch policy allocation (courier, Patch, or split) |
| Service fee | Patch revenue |
| Tip | Courier payable, unless customer is told otherwise |
| Processor fee | Patch or assigned party, explicitly recorded |
| Discount | Recorded against the party funding it |
| Refund/dispute | Reverses the original allocations and retains provider references |

## Make boundary

Make may receive a red/yellow exception notification or daily digest. It must not calculate allocations, decide payment state, accept a payment, or be the only record of a refund/payout.
