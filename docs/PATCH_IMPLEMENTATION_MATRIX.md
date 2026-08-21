# Patch implementation matrix

Updated: 2026-08-20 · version 1.10.8

The community, offers, demand, concierge, partner, and preference capabilities
now live inside the existing GateWay visual shell and shared navigation. The
public product remains GateWay until the founder supplies the official Patch
brand assets; no interim logo or replacement visual identity is in use.

This is the release truth. A capability is **Live** only when it has a durable
server workflow, an operator surface, tests, and a customer/partner entrypoint.

| Capability | State | Operational truth |
|---|---|---|
| Restaurant and courier order intake | Live | Server-priced, idempotent intake; cash checkout can operate now. Unknown or preview kitchens are rejected before record creation. |
| Merchant ticket acceptance/readiness | Live | Token-scoped kitchen screen and menu controls. |
| Dispatch and driver lifecycle | Live | Assignment, pickup, live location, proof, delivery, exception and close flows. |
| Customer tracking/support/history | Live | Capability-scoped tracking, support intake and local device history. |
| PostgreSQL durability | Live/transition | Owned domains are authoritative in PostgreSQL. Every successful legacy Airtable mutation is durably queued and applied to `ops_*`; conversion failures remain visible and retryable. Reads still use Airtable until the repository switch passes shadow-read drills. |
| Patch Today feed | Live | Reviewed/published items, sources, areas and device topic follows. No unreviewed scraping is published. |
| Bring It to Patch | Live | Deduplicated nominations, one device vote, visible counts/status and operator queue. |
| Offers and wallet | Live | Partners and operators can publish, pause and expire server-enforced offers; customers can save them; redemption and points records are single-use. |
| Delivery loyalty | Live | A linked Patch device receives 100 points once when its order is delivered. |
| Catering and recurring lunch | Live intake | Structured request and operator confirmation workflow; no charge before confirmation. |
| Custom and partner-created delivery | Live intake | Structured pickup/drop-off workflow enters Command Center. |
| Partner application/review | Live | Durable application, review statuses and approval into paused onboarding account. |
| Partner catalog/hours/menu control | Live | Existing kitchen portal controls menu availability, specials, hours and posts. |
| Customer/partner community posts | Live text | Consent-gated neighbor notes and recognition enter moderation; approved posts publish to the reviewed feed. Photo uploads remain out of scope until media moderation is staffed. |
| Accessibility/personalization | Live | Durable palette, text size, contrast, motion, density, channel and quiet-hour preferences. |
| Context delivery intelligence | Live weather / partial traffic | Official NWS point alerts are cached and translated into checkout/feed delivery-impact guidance with stale-safe fallback. Service radius, hours, prep time and driver heads-up rules are live. Live traffic still needs an authoritative provider. |
| Customer accounts/RBAC | Partial | Device identities and scoped operator/merchant/driver capabilities are live; verified multi-role customer accounts require an OTP provider. |
| Founder/team command authentication | Live | Clean `/board` sign-in sends the founder or individually revocable team credential in a no-store request header. Compatibility links immediately scrub the bearer key from the address bar. |
| Demo/training data isolation | Live | Demo tickets remain available for lifecycle drills and are visibly labeled, but are excluded from KPIs, revenue, tips, earnings, statements, exports, merchant insights and public impact. |
| Active queue hygiene | Live | Launch readiness blocks on abandoned received/confirmed/assigned/in-transit/failed tickets while preserving legitimate future scheduled work and training demos. |
| Stripe Connect/card payments | External gate | Money controls exist; activation requires Stripe business onboarding, credentials and approved allocation/refund rules. Cash is the live payment method. |
| SMS notifications | External gate | Notification adapter and copy exist; activation requires Twilio credentials and messaging registration. Phone support is 865-964-3843, 9–9 daily. |
| Square catalog/order integration | External gate | Canonical menu/order models exist; a live Square seller authorization is required. Manual menu/order fallback is live. |
| Swarm/multi-kitchen routing | Roadmap | Not represented as live. Requires routing economics, batching safety and driver trials. |

## Release gates

Every release must pass the full automated suite, mobile visual inspection,
console-error inspection, production health/version checks, and a cash delivery
drill. Stripe, SMS or marketplace integrations may not be labeled live until
their external credentials, reconciliation and failure drills pass.
