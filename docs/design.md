# TrailGoods Architecture & Design

## System Overview

TrailGoods is an offline-first marketplace backend for outdoor trips, gear, and live-pet listings. It runs entirely on a single Docker host with no external service dependencies.

```
                    +-------------------+
                    |    Client / UI    |
                    +--------+----------+
                             |
                             | HTTP (port 8000)
                             v
+-----------------------------------------------------------+
|                     Docker Compose                         |
|                                                           |
|  +-------------+   +-----------+   +------------------+  |
|  |   api       |   |  worker   |   |   postgres       |  |
|  | (FastAPI)   |-->| (job      |-->| (PostgreSQL 16)  |  |
|  |             |   |  runner)  |   |                  |  |
|  +------+------+   +-----+-----+   +------------------+  |
|         |                 |                                |
|         |   +-------------+-------------+                 |
|         +-->|  /data/assets (local disk)|                 |
|             |  /data/backups            |                 |
|             |  /data/previews           |                 |
|             +---------------------------+                 |
+-----------------------------------------------------------+
```

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Framework | FastAPI + Pydantic v2 |
| ORM | SQLAlchemy 2.x (async) |
| Database | PostgreSQL 16 |
| Migrations | Alembic |
| Password hashing | Argon2id |
| Encryption | AES-256-GCM (cryptography library) |
| Image processing | Pillow |
| Job queue | PostgreSQL-backed (no Redis/Celery) |
| File storage | Local disk |
| Deployment | Docker Compose |

## Domain Architecture

### Five Core Domains

```
+------------------+     +------------------+     +------------------+
|   Identity &     |     |   Catalog &      |     |   Inventory &    |
|   Auth           |     |   Pricing        |     |   Orders         |
|                  |     |                  |     |                  |
| - Users          |     | - Items          |     | - Warehouses     |
| - Sessions       |     | - SPUs / SKUs    |     | - Balances       |
| - Roles/Perms    |     | - Categories     |     | - Lots           |
| - Identity Binds |     | - Tags           |     | - Movements      |
| - Login Attempts |     | - Price Books    |     | - Inbound/Outbound|
|                  |     | - Attributes     |     | - Orders         |
+------------------+     | - Media          |     | - Reservations   |
                          +------------------+     | - Stocktakes     |
                                                   +------------------+

+------------------+     +------------------+
|   Verification   |     |   Governance     |
|                  |     |                  |
| - Cases          |     | - Reviews        |
| - Revisions      |     | - Reports        |
| - Events         |     | - Appeals        |
| - Encrypted PII  |     | - Mod Events     |
|                  |     | - Sensitive Words |
+------------------+     +------------------+

                    +------------------+
                    |   Cross-Cutting  |
                    |                  |
                    | - Audit Logs     |
                    | - Assets/Blobs   |
                    | - Share Links    |
                    | - Jobs           |
                    | - Idempotency    |
                    +------------------+
```

## Database Schema (52 tables)

### Identity & Access
- `users` - principal record, Argon2id password hash, challenge lock state
- `roles` - Guest, RegisteredUser, Instructor, Reviewer, Admin
- `permissions` - 86 fine-grained permission codes
- `user_roles` - M2M assignment
- `role_permissions` - M2M grants
- `sessions` - server-side session store, idle timeout 30min
- `login_attempts` - rolling window tracking for lockout
- `password_history` - last 5 hashes for reuse prevention
- `identity_bindings` - staff/student ID bindings, encrypted at rest

### Verification
- `verification_cases` - PERSONAL/ENTERPRISE profiles, encrypted PII fields
- `verification_case_revisions` - append-only snapshot on every update
- `verification_case_events` - status transition audit trail

### Catalog
- `categories` - hierarchical, unique slug
- `tags` - classification labels
- `items` - PRODUCT/SERVICE/LIVE_PET, row_version for optimistic locking
- `item_tags` - M2M
- `item_attributes` - scoped (ITEM/SPU/SKU) with scope_ref_id
- `spus` - product grouping, unique code
- `skus` - sellable units, unique code within SPU
- `item_media` - asset attachments with scope
- `price_books` - named price books, one default allowed
- `price_book_entries` - USD cents, no date overlap

### Assets
- `asset_blobs` - deduplicated by SHA-256, metadata_json, thumbnail_path
- `assets` - logical records with owner, kind, purpose, watermark policy
- `upload_sessions` - resumable upload state
- `upload_parts` - chunk tracking, unique (session, part_number)
- `share_links` - expiring, download-counted, optional password
- `share_link_access_logs` - retained 180 days

### Inventory
- `warehouses` - unique code
- `inventory_balances` - on_hand, reserved, sellable with CHECK constraints
- `inventory_lots` - lot-level tracking, FEFO/FIFO allocation
- `inventory_movements` - immutable ledger
- `inbound_docs` / `inbound_doc_lines` - immutable after posting
- `outbound_docs` / `outbound_doc_lines` - immutable after posting
- `stocktakes` / `stocktake_lines` - variance with reason codes
- `reservations` - order-linked, idempotency-keyed
- `reorder_alerts` - deduplicated within 24h

### Orders
- `orders` - minimal internal model for reservation/deduction/rollback
- `order_lines` - server-validated, authoritative pricing

### Governance
- `reviews` - 1-5 rating, PII-stripped body_public, revision history
- `review_revisions` - append-only
- `review_moderation_events` - first-class domain history
- `reports` - polymorphic target, 48h triage SLA
- `report_events` - triage/close audit trail
- `appeals` - 14-day filing window, reviewer-controlled lifecycle
- `appeal_events` - decision audit trail
- `sensitive_word_terms` - versioned dictionary

### Operations
- `audit_logs` - append-only, request correlation, actor role snapshot
- `jobs` - durable queue, exponential backoff, recurring self-reschedule
- `idempotency_keys` - request deduplication

## Key Design Decisions

### Authentication
- Username-only login (no email auth in v1)
- Server-side sessions in PostgreSQL (not JWTs)
- Argon2id for password hashing
- Session idle timeout enforced on every request
- Lockout after 5 failures in 15-minute rolling window

### Authorization (RBAC)
- 5 roles: Guest, RegisteredUser, Instructor, Reviewer, Admin
- 86 fine-grained permissions seeded at startup
- Admin has all permissions explicitly (not just a bypass)
- Permission check via `require_permission(...)` FastAPI dependency
- Object-level ownership checks in service layer

### Encryption
- AES-256-GCM for sensitive fields (DOB, ID numbers, legal names)
- Key versioning for rotation support
- Master key loaded from file or environment variable
- Identity binding external_ids stored as SHA-256 hash + encrypted value

### Inventory Concurrency
- `SELECT FOR UPDATE` on inventory_balances for all mutations
- sellable_qty = on_hand_qty - reserved_qty (enforced on every write)
- Outbound posting checks sellable_qty won't go negative (reserved stock protection)
- Lot allocation: FEFO (first expiry first out), then FIFO
- Lot allocation must fully cover or fail (no partial allocation)
- Idempotency keys persisted in database for deduction replay safety

### Order Lifecycle
```
CREATED --> RESERVED --> DEDUCTED --> COMPLETED
    |           |           |
    +-----------+-----------+---> CANCELED
```
- Reservation: checks sellable_qty, increments reserved_qty
- Deduction: consumes reservations, decrements on_hand and reserved
- Cancel within 30 min: auto-releases reservations, creates ROLLBACK inbound docs, restores lot quantities
- Cancel after 30 min: requires manual adjustment

### Verification Lifecycle
```
DRAFT --> SUBMITTED --> UNDER_REVIEW --> APPROVED --> EXPIRED
  |         ^  |           |               |
  |         |  v           v               +---> SUBMITTED (renewal)
  +---------|--+----> NEEDS_INFO
  |         |
  +-------->+---------> WITHDRAWN
```
- Encrypted field storage with per-field masking
- Revision created on every update (not just submit)
- Asset fingerprint dedup on submit
- Approval sets user.verified_until, expiry clears it

### Content Governance
- Reviews: sensitive-word filter + PII redaction (email/phone)
- Reports: 48h triage SLA tracked (worker flags breaches, doesn't auto-triage)
- Appeals: 14-day filing window from actual decision (not creation). Worker flags overdue, doesn't auto-close.
- ReviewModerationEvent provides first-class domain history

### File Handling
- Local disk storage under configurable root
- SHA-256 deduplication at blob level
- Kind-to-MIME constraint (IMAGE requires image/*, etc.)
- Content signature verification (magic bytes) on upload completion
- Metadata extraction (dimensions, format) for images
- Thumbnail generation via Pillow
- Resumable multipart upload with cumulative size enforcement
- Upload part uniqueness enforced by DB constraint

### Background Jobs
- PostgreSQL-backed job table (no external broker)
- Worker polls for due jobs with configurable interval
- Exponential backoff: 1m, 5m, 15m, 60m, 180m
- Stale RUNNING jobs recovered after 30 minutes
- Recurring jobs self-reschedule on success via payload metadata
- 10 recurring job types bootstrapped on API startup

### Audit Trail
- Append-only audit_logs table
- Request correlation ID on every entry
- Actor user ID and role snapshot on privileged actions
- Covers: auth events, RBAC changes, verification decisions, inventory postings, order operations, moderation actions, sensitive data reads, backup/integrity outcomes
- Privileged list/read endpoints also audit logged

## Migration Strategy

13 Alembic migrations (0001-0013) applied in sequence:
1. Auth, RBAC, sessions, audit
2. Assets, verification, share links, jobs
3. Catalog, pricing, items
4. Inventory, orders
5. Reviews, moderation
6. Missing indexes
7. Identity binding encryption
8. Reorder alert dedup
9. Review moderation events
10. Item attribute scope_ref
11. Legacy encryption backfill
12. Upload part uniqueness
13. CHECK constraints

## Testing Strategy

- 303 tests, 90%+ coverage
- All tests run through Alembic migrations (not metadata.create_all)
- No dependency overrides (real get_db, real engine)
- No datetime mocks (DB state manipulation instead)
- Real PostgreSQL, real local disk, real encryption
- Docker-based test runner via `./run_tests.sh`
- Content uses real JPEG bytes (Pillow-generated) for signature verification

## Deployment

Single command: `docker-compose up`

The API entrypoint automatically:
1. Generates encryption key if missing
2. Waits for PostgreSQL
3. Runs Alembic migrations
4. Seeds roles, permissions, and demo users
5. Bootstraps recurring jobs
6. Starts uvicorn

Worker entrypoint waits for API health before starting.
