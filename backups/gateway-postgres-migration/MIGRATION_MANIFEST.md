# Patch production migration manifest — 2026-08-20

This directory contains private production SQLite snapshots and is not a
publication surface. Database files remain excluded from Git.

## Authoritative catalog snapshot

`nucleus_events-2026-08-20-v1.9.41.db`

- Release: Patch v1.9.41
- Git commit: `960c68df85b46f32b7f6bdd7951c3d4350481224`
- Railway deployment: `0da5474c-f266-40ff-8031-49981ad1180a`
- Size: 647,168 bytes
- SHA-256: `cd2b1a8c7a60416b513c618dd20e7281baf86c18537cb4de4b154ff3e40b8f61`
- Integrity: `ok`
- Counts: 10 partners, 400 menu items, 153 option groups, 765 option
  choices, 3 driver profiles, 2 promo codes, 2 events

## Recovered append-only history fragments

- `nucleus_events-2026-08-20-v1.9.40.db`
  - SHA-256: `918c9b1f0754757bb80d412d90f8183e6e71938af07d5be37657c3dd9dbcea89`
  - 2 events
- `nucleus_events-2026-08-20-v1.9.38.db`
  - SHA-256: `5cc8b350dc288e9815df5d40c9eae9ffbc8158028527d294858cc5f699ff57b2`
  - 3 events

Generated menu and option IDs differ across ephemeral deployments. Never
import the v1.9.38 or v1.9.40 snapshots as complete catalogs after importing
v1.9.41. Merge only their event tables.

## Rehearsed import sequence

From `services/events`, with `DATABASE_URL` pointing to the empty target:

```text
python -m app.migrate_sqlite_to_postgres --source ../../backups/gateway-postgres-migration/nucleus_events-2026-08-20-v1.9.41.db --apply
python -m app.migrate_sqlite_to_postgres --source ../../backups/gateway-postgres-migration/nucleus_events-2026-08-20-v1.9.40.db --merge-events
python -m app.migrate_sqlite_to_postgres --source ../../backups/gateway-postgres-migration/nucleus_events-2026-08-20-v1.9.38.db --merge-events
```

Verified disposable-target result:

- 10 partners
- 400 menu items
- 153 option groups
- 765 option choices
- 3 driver profiles
- 2 promo codes
- 7 owned events
- SQLite integrity check: `ok`

After this sequence, run the Airtable dry-run and apply migration. Cut over the
application only when both owned-table and Airtable reconciliation reports are
clean, then create and restore-check a PostgreSQL backup before accepting a
real order.

## Production execution evidence

The production target was imported during the controlled 2026-08-20
maintenance window. The canonical catalog import and both event-only merges
reconciled successfully, producing 10 partners, 400 menu items, 153 option
groups, 765 option choices, 3 driver profiles, 2 promo codes, and 7 owned
events.

The Airtable operational mirror then reconciled exactly:

- 14 orders
- 2 drivers
- 22 events
- 0 customers
- 0 deliveries
- no relationship orphans
- verified migration run `d8d62a3d-3a2f-42ff-9326-12e3a198b06c`

Three duplicate historical human order IDs were retained as distinct source
records, as required by the source-record primary-key strategy.

## PostgreSQL recovery artifact

`patch-2026-08-20-prelaunch.dump`

- Format: PostgreSQL custom archive
- Size: 100,282 bytes
- SHA-256: `2423fe7391637e00d72eec6e4b65a00a42630ae6715b065288a9c1fd03849921`
- Archive entries: 119
- Restore test: successful in an isolated `patch_restore_check` database
- Restored counts: 10 partners, 400 menu items, 7 owned events, 14 operational
  orders, 2 operational drivers, 22 operational events, 1 verified migration
  run
- Restore-check database: removed after verification

The database archives and rotated-access evidence are intentionally excluded
from Git because they contain private production data or bearer credentials.
