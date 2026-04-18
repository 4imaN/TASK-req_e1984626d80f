# TrailGoods API Specification

Base URL: `/api/v1`

All responses use the envelope:
```json
{
  "data": <payload>,
  "meta": { "request_id": "<uuid>", "pagination": null | { "total", "limit", "offset" } },
  "error": null | { "code": "<string>", "message": "<string>", "details": {} }
}
```

Correlation: send `X-Request-ID` header to trace requests. If omitted, one is generated and echoed back.

Idempotency: endpoints that accept `Idempotency-Key` header will return cached results on replay.

Authentication: `Authorization: Bearer <token>` from login response.

---

## Authentication & Identity

### POST /auth/register
Create a new user account.

| Field | Type | Rules |
|---|---|---|
| username | string | 3-50 chars, `^[a-zA-Z0-9_.-]+$`, case-insensitive unique |
| password | string | min 12 chars, at least 1 digit, at least 1 symbol |
| email | string? | optional, unique |

Returns: `201` with user data.

### POST /auth/login
Authenticate and receive a session token.

| Field | Type |
|---|---|
| username | string |
| password | string |

Returns: `200` with `{ token, session, user }`.

Lockout: 5 failed logins in 15 minutes triggers forced logout of all sessions and 15-minute challenge lock.

### POST /auth/logout
Revoke current session. Requires auth.

### POST /auth/logout-all
Revoke all sessions for the current user. Requires auth.

### POST /auth/password-rotate
Change password. Revokes all existing sessions. Rejects reuse of last 5 passwords.

| Field | Type |
|---|---|
| current_password | string |
| new_password | string |

### GET /sessions/me
List all sessions for the current user. Permission: `session.read_own`.

### DELETE /sessions/{session_id}
Revoke a specific session. Permission: `session.revoke_own`. Owner only.

### POST /identity-bindings
Bind a staff/student ID. Permission: `identity_binding.create`.

| Field | Type | Rules |
|---|---|---|
| binding_type | string | `STAFF_ID` or `STUDENT_ID` |
| institution_code | string | `^[A-Z0-9_-]{2,32}$` |
| external_id | string | 1-100 chars, encrypted at rest |

Replaces previous active binding for same institution+type.

### GET /identity-bindings
List current user's bindings. Permission: `identity_binding.read_own`. External IDs are masked (last 4 chars visible).

---

## Verification

### POST /verification-cases
Create a verification case. Permission: `verification.create`. One active case per (user, profile_type).

| Field | Type |
|---|---|
| profile_type | `PERSONAL` or `ENTERPRISE` |

### PATCH /verification-cases/{case_id}
Update case fields. Permission: `verification.submit`. Only in DRAFT or NEEDS_INFO status.

PERSONAL requires: legal_name, dob (MM/DD/YYYY, age >= 18), government_id_number (alphanumeric 5-20), government_id_image_asset_id (image MIME only).

ENTERPRISE requires: enterprise_legal_name (1-300 chars), responsible_person_legal_name, responsible_person_dob, responsible_person_id_number, responsible_person_id_image_asset_id. Optional: enterprise_registration_number, enterprise_registration_asset_id.

Sensitive fields are encrypted with AES-256-GCM. Optimistic locking via `row_version`. Creates a revision snapshot on every update.

### POST /verification-cases/{case_id}/submit
Submit for review. Validates all required fields, asset fingerprints (SHA-256 dedup check), DOB consistency, image MIME types.

### GET /verification-cases/{case_id}
Read case. Permission: `verification.read_own`. Masked for regular users, unmasked for Reviewer/Admin with `verification.sensitive.read`. Sensitive reads are audit logged.

### GET /verification-cases/{case_id}/status
Status-only read. Permission: `verification.read_own`.

### POST /verification-cases/{case_id}/withdraw
Withdraw case. Permission: `verification.withdraw`.

### POST /verification-cases/{case_id}/renew
Renew expired case. Permission: `verification.renew`.

### POST /verification-cases/{case_id}/decision
Reviewer/Admin decision. Permission: `verification.review`.

| Field | Type |
|---|---|
| decision | `UNDER_REVIEW`, `NEEDS_INFO`, `APPROVED`, `REJECTED` |
| comment | string? |

Approval sets expires_at = now + 12 months and updates user's verified_until field.

### GET /verification-cases
List cases (reviewer queue). Permission: `verification.review`. Filters: `status`, `profile_type`. Paginated.

---

## Catalog

### GET /categories
List all categories. Public, no auth.

### POST /categories
Create category. Permission: `catalog.item.manage_all`.

### GET /tags
List all tags. Public, no auth.

### POST /tags
Create tag. Permission: `catalog.item.manage_all`.

### POST /items
Create item. Permission depends on type:
- `SERVICE`: requires `catalog.item.create_service`
- `PRODUCT`: requires `catalog.item.create_product`
- `LIVE_PET`: requires `catalog.item.create_live_pet`

| Field | Type | Rules |
|---|---|---|
| item_type | string | `PRODUCT`, `SERVICE`, `LIVE_PET` |
| title | string | 1-200 chars |
| description | string | max 20,000 chars |
| category_id | UUID | must exist |

### GET /catalog/items
Public catalog list. No auth for published items. Filters: `status`, `item_type`, `category_id`, `tag_slug`, `search`. Sort: `newest`, `title_asc`, `price_asc`, `price_desc`. Paginated (max 100).

### GET /items/{item_id}
Item detail. Published items are public. Draft/unpublished visible only to owner or Admin.

### PATCH /items/{item_id}
Update item. Permission: `catalog.item.update_own`. Owner or Admin. Optimistic locking via `row_version`.

### POST /items/{item_id}/publish
Publish item. Permission: `catalog.item.publish_own`. Requires: title, description, category, at least one active image media (verified MIME), at least one active USD price in default price book. PRODUCT requires sellable SKU. LIVE_PET requires exactly one SKU.

### POST /items/{item_id}/unpublish
Unpublish. Permission: `catalog.item.publish_own`.

### POST /items/{item_id}/tags/{tag_id}
Add tag. Permission: `catalog.item.update_own`.

### DELETE /items/{item_id}/tags/{tag_id}
Remove tag. Permission: `catalog.item.update_own`.

### POST /items/{item_id}/media
Attach media asset. Permission: `asset.create`. Validates asset ownership, active status, non-verification purpose, image MIME for publish eligibility.

### POST /items/{item_id}/attributes
Create spec attribute. Permission: `catalog.item.update_own`.

| Field | Type | Rules |
|---|---|---|
| scope | string | `ITEM`, `SPU`, `SKU` |
| scope_ref_id | UUID? | required for SPU/SKU scopes, must belong to item |
| key | string | 1-100 chars |
| value_text | string? | |
| value_number | float? | |
| value_json | string? | |

### GET /items/{item_id}/attributes
List attributes. Permission: `catalog.item.read`. Non-owner non-admin can only see published item attributes.

### DELETE /items/{item_id}/attributes/{attribute_id}
Delete attribute. Permission: `catalog.item.update_own`.

### POST /spus
Create SPU. Permission: `catalog.spu.create`. Only for PRODUCT or LIVE_PET items.

### POST /spus/{spu_id}/skus
Create SKU. Permission: `catalog.sku.create`. Code unique within SPU (1-64 chars).

### PATCH /skus/{sku_id}
Update SKU. Permission: `catalog.sku.update`. Owner or Admin.

### POST /price-books
Create price book. Permission: `catalog.price.create`. Only one active default allowed.

### POST /price-books/{price_book_id}/entries
Create price entry. Permission: `catalog.price.create`. Validates target exists, owner authorization, amount_cents > 0, no date overlap. USD only.

---

## Assets & Sharing

### POST /assets/uploads
Create upload session. Permission: `asset.create`.

| Field | Type | Rules |
|---|---|---|
| filename | string | 1-255 chars |
| mime_type | string | Allowed: image/jpeg, image/png, image/webp (<=10MB), video/mp4, video/webm (<=500MB), application/pdf, text/plain, text/csv (<=50MB) |
| total_size | int | positive |
| total_parts | int | >= 1 |
| kind | string | IMAGE, VIDEO, ATTACHMENT, VERIFICATION_ID, THUMBNAIL. Kind-MIME constraint enforced. |
| purpose | string | CATALOG, VERIFICATION, REVIEW_ATTACHMENT, GENERAL |

### PUT /assets/uploads/{upload_id}/parts/{part_no}
Upload part. Permission: `asset.create`. Owner-bound. Cumulative size enforced against MIME limit. Part number unique per session (DB constraint).

### POST /assets/uploads/{upload_id}/complete
Finalize upload. Permission: `asset.create`. Assembles parts, computes SHA-256, deduplicates blobs, validates content signature (magic bytes), extracts metadata (dimensions for images), generates thumbnail for images. Owner-bound.

### POST /assets/uploads/batch-complete
Batch finalize. Permission: `asset.create`. Per-file success/failure.

### GET /assets/{asset_id}
Get asset metadata. Permission: `asset.read_own`. Owner or Admin.

### DELETE /assets/{asset_id}
Soft-delete asset. Permission: `asset.delete_own`. Blocks deletion if referenced by active verification cases or published items.

### POST /assets/{asset_id}/share-links
Create share link. Permission: `share_link.create`. Owner or Admin.

| Field | Type | Rules |
|---|---|---|
| password | string? | min 8 chars if present, stored hashed |
| expires_in_days | int | >= 1, default 7 |
| max_downloads | int | >= 1, default 20 |

Verification-purpose assets cannot be shared.

### DELETE /share-links/{share_link_id}
Disable share link. Permission: `share_link.delete_own`. Owner or Admin.

### GET /share-links/{token}
Validate share link metadata. Public. Password via `X-Share-Password` header. Does NOT consume download quota.

### GET /share-links/{token}/download
Download asset binary. Public. Consumes download quota. Returns `StreamingResponse` with correct Content-Type and Content-Disposition.

---

## Inventory & Warehousing

### POST /warehouses
Create warehouse. Permission: `warehouse.create`. Code must be unique.

### GET /warehouses
List warehouses. Permission: `warehouse.read`.

### POST /inbound-docs
Create inbound document. Permission: `inventory.inbound.create`. Source types: PURCHASE, RETURN, TRANSFER_IN, ROLLBACK, MANUAL_ADJUSTMENT.

### POST /inbound-docs/{doc_id}/lines
Add line. Permission: `inventory.inbound.create`. Quantity must be positive. SKU must exist. Immutable after posting.

### POST /inbound-docs/{doc_id}/post
Post inbound. Permission: `inventory.inbound.post`. Increments on_hand_qty, recalculates sellable_qty, creates INBOUND movements, optionally creates inventory lots.

### POST /outbound-docs
Create outbound document. Permission: `inventory.outbound.create`. Source types: SALE, TRANSFER_OUT, DAMAGE, WRITE_OFF, ORDER_DEDUCTION.

### POST /outbound-docs/{doc_id}/lines
Add line. Permission: `inventory.outbound.create`. Quantity must be positive.

### POST /outbound-docs/{doc_id}/post
Post outbound. Permission: `inventory.outbound.post`. Decrements on_hand_qty with sellable_qty guard (prevents going below reserved). Lot allocation via FEFO/FIFO. SELECT FOR UPDATE on balances.

### GET /inventory/balances
List balances. Permission: `inventory.read`. Filters: warehouse_id, sku_id. Paginated.

### POST /stocktakes
Create stocktake. Permission: `inventory.stocktake.create`.

### POST /stocktakes/{stocktake_id}/lines
Add count line. Permission: `inventory.stocktake.create`. Variance reason required when counted != expected. OTHER requires note.

### POST /stocktakes/{stocktake_id}/post
Post stocktake. Permission: `inventory.stocktake.post`. Creates ADJUSTMENT_POSITIVE or ADJUSTMENT_NEGATIVE movements. Sellable_qty guard.

### GET /reservations
List reservations. Permission: `reservation.read`. Non-admin scoped to own orders.

### GET /admin/reorder-alerts
List reorder alerts. Permission: `inventory.read`.

---

## Orders

### POST /orders
Create order. Permission: `order.create`. Idempotency key required.

Validates: item published, SKU belongs to item, SKU sellable, warehouse active. Derives authoritative pricing from default price book.

### POST /orders/{order_id}/reserve
Reserve stock. Permission: `order.create`. Header: `Idempotency-Key`. SELECT FOR UPDATE on balances. Order must be in CREATED status (prevents double reservation). Sets order to RESERVED.

### POST /orders/{order_id}/deduct
Deduct stock. Permission: `order.create`. Header: `Idempotency-Key`. Persisted via IdempotencyKey table. Creates per-warehouse outbound docs. Lot allocation via FEFO/FIFO. Sets order to DEDUCTED.

### POST /orders/{order_id}/cancel
Cancel order. Permission: `order.cancel_own`. Owner or Admin. Within 30 minutes: auto-releases reservations, reverses deductions with ROLLBACK inbound docs, restores lot quantities. After 30 minutes: requires manual adjustment.

---

## Reviews & Governance

### POST /items/{item_id}/reviews
Create review. Permission: `review.create`. Rating 1-5. Item must be published. One review per user per item. Body filtered through sensitive-word dictionary and PII redaction (email/phone patterns). Matched words trigger PENDING_REVIEW status.

### PATCH /reviews/{review_id}
Edit review. Permission: `review.edit_own`. Owner only. Creates append-only revision. Re-runs word filter.

### GET /items/{item_id}/reviews
List reviews. Public. Only PUBLISHED reviews. No user_id in response (PII-safe).

### POST /reviews/{review_id}/moderate
Moderate review. Permission: `review.moderate`. Actions: PUBLISHED, SUPPRESSED, REMOVED. Creates ReviewModerationEvent.

### POST /reports
Create report. Permission: `report.create`. Validates target exists. Sets triage_due_at = now + 48h.

| Field | Type |
|---|---|
| target_type | REVIEW, ITEM, ASSET, USER |
| target_id | UUID |
| reason_code | string |

### GET /reports
List reports (reviewer queue). Permission: `report.triage`. Filters: status, target_type. Paginated.

### POST /reports/{report_id}/triage
Triage report. Permission: `report.triage`. Actions: TRIAGED, DISMISSED.

### POST /reports/{report_id}/close
Close report. Permission: `report.close`. Requires triage first (TRIAGED, ACTIONED, or DISMISSED).

### POST /appeals
Create appeal. Permission: `appeal.create`. Appellant must own the report or review. Reports must be in appealable state (TRIAGED/ACTIONED/DISMISSED/CLOSED). Reviews must be in moderated state (SUPPRESSED/REMOVED). 14-day filing window from decision timestamp.

### GET /appeals
List appeals (reviewer queue). Permission: `appeal.decide`. Paginated.

### POST /appeals/{appeal_id}/decision
Decide appeal. Permission: `appeal.decide`.

---

## Administration

### POST /admin/roles/assign
Assign role. Permission: `rbac.assign`.

### POST /admin/force-logout
Force logout all sessions for a user. Permission: `admin.force_logout`.

### POST /admin/clear-challenge
Clear challenge lock on a user. Permission: `admin.clear_challenge`.

### GET /admin/audit-logs
List audit logs. Permission: `audit.read`. Paginated.

### POST /admin/sensitive-words
Create sensitive word term. Permission: `sensitive_word.manage`.

### GET /admin/sensitive-words
List sensitive word terms. Permission: `sensitive_word.manage`. Paginated.

### DELETE /admin/sensitive-words/{term_id}
Deactivate term. Permission: `sensitive_word.manage`.

### GET /admin/reorder-alerts
List reorder alerts. Permission: `inventory.read`. Paginated.
