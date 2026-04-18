# TrailGoods Issue Recheck

## Verdict

All previously tracked problems from `trailgoods_static_audit_2026-04-17.md` are resolved based on static inspection.

- Overall issue-remediation verdict: **Pass**
- Issue status: **Fixed**
- Remaining tracked defects: **None**
- Runtime verification status: **Not executed; manual verification still required for runtime behavior**

## Scope
- Reviewed source and tests referenced by `.tmp/trailgoods_static_audit_2026-04-17.md`.
- Static analysis only.
- Not executed: app startup, Docker, tests, worker, migrations.

## Recheck Results

### 1. Catalog read paths ignore valid SKU-level pricing
- Status: **Addressed**
- Previous evidence: `.tmp/trailgoods_static_audit_2026-04-17.md:75`
- Current evidence:
  - `src/trailgoods/services/catalog.py:783`
  - `src/trailgoods/services/catalog.py:799`
  - `src/trailgoods/services/catalog.py:817`
  - `src/trailgoods/services/catalog.py:916`
  - `src/trailgoods/services/catalog.py:920`
  - `tests/api/v1/test_regressions.py:281`
  - `tests/api/v1/test_regressions.py:284`
  - `tests/api/v1/test_regressions.py:305`
- Reasoning: catalog list now unions item-targeted and SKU-targeted default prices before sorting/serialization, and detail reads include both item and SKU price entries. Targeted regressions now assert SKU-priced list/detail values and sort order.

### 2. `catalog.price.create` audit logs miss actor attribution
- Status: **Addressed**
- Previous evidence: `.tmp/trailgoods_static_audit_2026-04-17.md:83`
- Current evidence:
  - `src/trailgoods/services/catalog.py:453`
  - `src/trailgoods/services/catalog.py:523`
  - `src/trailgoods/services/catalog.py:526`
  - `tests/api/v1/test_regressions.py:331`
  - `tests/api/v1/test_regressions.py:356`
- Reasoning: the service now passes `actor_user_id` into `write_audit(...)`, and a dedicated regression verifies a `catalog.price.create` audit row contains actor attribution.

### 3. `LIVE_PET` detail responses omit SPU/SKU structure
- Status: **Addressed**
- Previous evidence: `.tmp/trailgoods_static_audit_2026-04-17.md:90`
- Current evidence:
  - `src/trailgoods/services/catalog.py:956`
  - `src/trailgoods/services/catalog.py:966`
  - `tests/api/v1/test_regressions.py:362`
  - `tests/api/v1/test_regressions.py:405`
- Reasoning: item detail serialization now includes SPU/SKU data for both `PRODUCT` and `LIVE_PET`, and there is a published live-pet detail regression covering the response shape.

### 4. Verification revision snapshots are incomplete
- Status: **Addressed**
- Previous evidence: `.tmp/trailgoods_static_audit_2026-04-17.md:97`
- Current evidence:
  - `src/trailgoods/services/verification.py:554`
  - `src/trailgoods/services/verification.py:562`
  - `src/trailgoods/services/verification.py:565`
  - `src/trailgoods/services/verification.py:567`
  - `tests/api/v1/test_regressions.py:416`
  - `tests/api/v1/test_regressions.py:461`
- Reasoning: `_build_snapshot(...)` now includes enterprise registration and responsible-person fields, and a regression asserts those fields exist in stored `snapshot_json`.

### 5. Reorder alert deduplication is still time-window based rather than state-based
- Status: **Addressed**
- Previous evidence: `.tmp/trailgoods_static_audit_2026-04-17.md:104`
- Current evidence:
  - `src/trailgoods/services/inventory.py:1126`
  - `src/trailgoods/services/inventory.py:1137`
  - `src/trailgoods/services/inventory.py:1142`
  - `src/trailgoods/services/inventory.py:1155`
  - `tests/api/v1/test_regressions.py:481`
  - `tests/api/v1/test_regressions.py:528`
- Reasoning: reorder dedup now keys on unresolved active alerts via `resolved_at is NULL`, and the service resolves active alerts when stock recovers. A repeated-scan regression now verifies no duplicate active alert is created.

### 6. Admin sensitive verification reads bypass explicit-permission semantics
- Status: **Addressed**
- Previous evidence: `.tmp/trailgoods_static_audit_2026-04-17.md:125`
- Current evidence:
  - `src/trailgoods/api/v1/endpoints/verification.py:190`
  - `src/trailgoods/api/v1/endpoints/verification.py:194`
  - `scripts/seed.py:137`
  - `scripts/seed.py:138`
  - `tests/api/v1/test_regressions.py:550`
  - `tests/api/v1/test_regressions.py:577`
- Reasoning: sensitive verification output is now gated by the explicit `verification.sensitive.read` permission, not by admin role alone. Seed data grants that permission explicitly to `Admin`, and regressions verify admin-with-permission sees sensitive data while regular users remain masked.

### 7. Missing targeted regression tests for SKU-price read/sort correctness
- Status: **Addressed**
- Previous evidence: `.tmp/trailgoods_static_audit_2026-04-17.md:169`
- Current evidence:
  - `tests/api/v1/test_regressions.py:281`
  - `tests/api/v1/test_regressions.py:284`
  - `tests/api/v1/test_regressions.py:305`
  - `tests/api/v1/test_regressions.py:317`
- Reasoning: there are now explicit regressions for list price visibility, detail price visibility, ascending sort, and descending sort for SKU-priced products.

### 8. Missing targeted regression tests for `catalog.price.create` audit attribution
- Status: **Addressed**
- Previous evidence: `.tmp/trailgoods_static_audit_2026-04-17.md:171`
- Current evidence:
  - `tests/api/v1/test_regressions.py:331`
  - `tests/api/v1/test_regressions.py:334`
  - `tests/api/v1/test_regressions.py:356`
- Reasoning: a focused regression now exercises the price-book entry creation path and asserts the resulting audit log includes actor attribution.

### 9. Missing targeted regression tests for verification snapshot completeness
- Status: **Addressed**
- Previous evidence: `.tmp/trailgoods_static_audit_2026-04-17.md:167`
- Current evidence:
  - `tests/api/v1/test_regressions.py:416`
  - `tests/api/v1/test_regressions.py:461`
  - `tests/api/v1/test_regressions.py:467`
  - `tests/api/v1/test_regressions.py:475`
- Reasoning: the test now inspects the stored revision snapshot and asserts presence of enterprise and responsible-person fields, not just revision count.

### 10. Missing targeted regression tests for repeated reorder-alert generation
- Status: **Addressed**
- Previous evidence: `.tmp/trailgoods_static_audit_2026-04-17.md:173`
- Current evidence:
  - `tests/api/v1/test_regressions.py:481`
  - `tests/api/v1/test_regressions.py:484`
  - `tests/api/v1/test_regressions.py:528`
  - `tests/api/v1/test_regressions.py:543`
- Reasoning: a dedicated repeated-scan regression now verifies the second scan creates no new alert and that only one active alert remains.

## Summary
- Fixed in current code and tests: all previously enumerated unresolved issues from `.tmp/trailgoods_static_audit_2026-04-17.md`.
- Residual boundary: this recheck is static-only. Runtime behavior, deployment startup, and integration behavior still require manual verification.
