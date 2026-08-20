# Patch Product Blueprint

**Status:** Living plan · 2026-08-14

## Product promise

Patch is a local commerce and community operating system: a beautiful market where customers, businesses, vendors, and couriers discover one another, transact, build loyalty, and solve delivery needs. Delivery is the connective tissue, not the entire product.

## Product principles

1. Make local commerce feel like an interactive farmers market and coupon book, not a directory or an endless menu list.
2. Every important action should create value for the customer, partner, courier, and Patch.
3. Customer service is always one obvious action away through the persistent **Patch Help** control.
4. Money, order state, permissions, and communications are auditable and idempotent.
5. Accessibility, reduced motion, readable contrast, keyboard navigation, screen-reader structure, text sizing, and personalization are core product capabilities.
6. New integrations plug into a stable Patch model; outside platforms do not define the product.

## Phase A — Commerce Integrity and Partner OS

### Data and reliability

- Complete the Airtable and SQLite migration to PostgreSQL with staging, backups, reconciliation, dual-write, and feature-flagged cutover.
- Establish immutable order and money ledgers, webhook inbox/outbox tables, idempotency keys, audit trails, daily reconciliation, and exception alerts.
- Add role-based accounts for customer, approved household dependent/caregiver, business buyer, partner staff, courier, dispatcher, and administrator.

### Partner onboarding

- Self-service application, identity and banking onboarding, business verification, agreement acceptance, service-area setup, hours, catalog/menu import, photos, policies, and preview.
- Patch review queue with approve, request changes, suspend, and publish controls.
- Lightweight profile/landing page for partners that already have a website, plus full storefront tools for partners that need a digital home.
- A guided launch checklist and persistent support channel make joining feel simple and low-risk.

### Integration layer

- A canonical Patch catalog, inventory, price, order, fulfillment, customer, tax, and refund model.
- Adapters for Square first, followed by other POS systems based on partner demand.
- Each adapter handles authorization, catalog mapping, webhooks, retries, health status, and reconciliation.
- CSV/email/manual fallbacks support businesses whose systems have no usable API.

### Payments and money integrity

- Stripe Connect for partner onboarding, payment acceptance, transfers, refunds, disputes, and payouts.
- Separate the customer charge from allocation rules so an order can pay a merchant, courier, and Patch correctly.
- Store all amounts as integer cents. The server calculates subtotal, discounts, taxable amounts, taxes, delivery fee, service fee, tip, processor cost, transfers, refunds, and payout state.
- Never use Make as the financial ledger. Make may send an exception notification after the application's reconciliation engine records a mismatch.
- Support card and wallet payments first; add invoicing or ACH for approved business accounts where it reduces cost and fits the risk model.
- Define who funds every coupon and refund. Tips remain separately attributable to the courier.
- Before launch, obtain Tennessee marketplace-facilitator, sales-tax, delivery-fee, tipping, contractor, and business-license review from qualified professionals.

### Real operating cases

- Catering request builder: guest count, budget, date/time, dietary needs, delivery/setup, quote, approval, payment, and fulfillment.
- Recurring business lunch: roster, authorized buyers, cost center, per-person budget, schedule, invoice/receipt package, and reorder.
- Partner-created delivery: a florist such as Petal Pushers submits an already-sold order for Patch fulfillment.
- Vendor-to-vendor order: one business buys from another and schedules Patch pickup/delivery.
- Order exceptions: substitution, delay, unavailable item, weather/event impact, refund, redelivery, and support escalation.

## Phase B — Community Intelligence and Living Market

### Local feed

- A reviewed source registry for official Knoxville-area news, events, weather, traffic, university activity, partner updates, and Patch editorial content.
- Prefer official APIs, RSS/Atom feeds, calendars, licensed feeds, and partner submissions. Store a short attributed summary and link to the source instead of republishing articles.
- Deduplicate, tag by category and geography, score relevance, and require moderation for ambiguous or promotional material.
- Let users follow places, categories, neighborhoods, and partners.

### Influence: Bring It to Patch

- Users vote for a desired business; verified accounts get one active vote per business.
- Public progress explains the process and threshold. Fraud/rate-limit checks protect the signal.
- At 100 qualified local votes, Patch creates a community-backed outreach package: verified count, service area, demand context, anonymized insights, and a polished letter.
- Initially, staff reviews and sends the letter. Automatic external sending comes only after the copy, consent, deliverability, and abuse controls have been proven.
- The candidate enters a partner-development pipeline and voters receive status updates.

### Interactive coupon book and loyalty

- Followable partner pages, time-bound offers, sponsored/partner-funded/ Patch-funded coupon rules, saved offers, gifting, and redemption controls.
- QR check-in can award points for eligible in-person purchases, with partner verification, receipt/POS confirmation where available, fraud limits, and clear expiration rules.
- Badge system inspired by collectible achievement patches: cuisine exploration, local supporter, catering host, dependable courier, community scout, seasonal achievements, and partner milestones.
- Badges reward constructive behavior and never become a disguised negative-rating system.

### Social and partner storytelling

- Customer posts for fulfilled experiences, with consent-aware photo uploads, tagging, moderation, reporting, and partner response/reuse permissions.
- Partner posts and follower notifications with frequency controls, quiet hours, opt-out, and content review safeguards.
- Positive courier recognition using specific compliments and reliability milestones; private operational coaching handles problems.

### Context-aware delivery intelligence

- Weather, road closures, UT games, festivals, races, and large events become normalized impact records with time, area, severity, confidence, expected delay, and recommended action.
- A compact weather/conditions control opens a delivery-aware briefing.
- Checkout and tracking use geofenced impact rules to adjust expectations, offer earlier ordering, and explain delays clearly.
- Alerts are useful and restrained: location relevance, urgency, quiet hours, channel preference, and accessibility are respected.

### A living visual system

- Seasonal and partner theme tokens change color, texture, illustration, badges, and motion without changing navigation or reducing accessibility.
- A Tennessee football-season theme can be an early takeover, subject to trademark/licensing review; use original Patch art and avoid implying university endorsement.
- User personalization includes approved colorful palettes, text size, contrast, reduced motion, density, and notification controls.

## Recommended build workflow

Keep one durable codebase. Preserve today's loved version as a tagged production release, then build on an `agent/patch-platform-foundation` branch and a separate Railway staging environment. Use feature flags for large areas such as Connect payments, the feed, rewards, and partner self-service.

A disconnected duplicate app is appropriate only for a disposable visual experiment. It creates permanent synchronization and security work if used as the primary strategy. Git can restore code, but database changes and user-generated data require separate backups and reversible migrations.

This file, the migration ADR, schemas, tests, and future decision records are the Codex handoff. They live with the software so a future build session can continue from verified facts instead of relying on chat memory.

## Integration reality

Patch can integrate with far more than Wix could, but not literally every platform. Integration is practical when the provider offers an API, webhooks, export/import, or a partner program and its commercial terms permit the use. Some systems require certification, fees, review, or a manual fallback. The adapter architecture contains those differences.

## Brand gate

`Patch` is a working product name, not yet a cleared trademark. A preliminary federal search is crowded. Do not commission a final identity, file app-store listings, or invest heavily in signage until a comprehensive federal/state/common-law/domain search and legal review are complete. A distinctive compound mark may be safer than the single word.

## Make automation policy

Use Make for cross-system coordination and human notification, not transactional truth.

Recommended scarce scenarios after the current account is audited:

1. **Partner and demand signal:** partner applications and 100-vote milestones create/update the internal pipeline and prepare a reviewed outreach package.
2. **Operations exceptions:** notify staff of recorded payment/order/support exceptions and deliver a daily reconciliation digest.

Core checkout, payment, order state, voting, and reconciliation remain in Patch/PostgreSQL.
