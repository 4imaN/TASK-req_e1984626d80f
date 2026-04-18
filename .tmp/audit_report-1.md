# TrailGoods Static Delivery Acceptance and Architecture Audit

## 1. Verdict
- Overall conclusion: **Partial Pass**

## 2. Scope and Static Verification Boundary
- Reviewed: `README.md`, `pyproject.toml`, FastAPI entry points, middleware, dependency/authorization helpers, catalog/assets/verification/inventory services, selected API endpoints, and the static test suite under `tests/api/v1/`.
- Not reviewed: runtime behavior against a live database, Docker/container execution, filesystem side effects, worker scheduling under real time, upload/download behavior on disk, backup/restore execution, or performance under load.
- Intentionally not executed: project startup, Docker, tests, migrations, worker, backup script, and any external service.
- Manual verification required for: deployment startup, live upload/download integrity, background job execution timing, backup/restore correctness, and p95 latency/concurrency claims.

## 3. Repository / Requirement Mapping Summary
- Prompt goal reviewed against code: an offline-first, single-machine FastAPI backend for identity, verification, catalog, digital assets, governance, and multi-warehouse inventory.
- Main implementation areas mapped: `src/trailgoods/api/v1/endpoints/*`, `src/trailgoods/services/*`, `src/trailgoods/models/*`, `src/trailgoods/middleware/*`, `scripts/backup.py`, and `tests/api/v1/*`.
- Recheck result: earlier blocker findings around `LIVE_PET` publication, admin upload ownership, enterprise verification submission, and backup DSN parsing are now fixed statically. Remaining gaps are narrower and fit a `Partial Pass`, not a `Fail`.

## 4. Section-by-section Review

### 1. Hard Gates
- **1.1 Documentation and static verifiability**
  - Conclusion: **Pass**
  - Rationale: startup, test, and configuration instructions are present, and the documented FastAPI entry point is statically consistent with the code layout.
  - Evidence: `README.md:5`, `README.md:29`, `README.md:62`, `src/trailgoods/main.py:15`, `pyproject.toml:1`
- **1.2 Material deviation from the Prompt**
  - Conclusion: **Partial Pass**
  - Rationale: the implementation is centered on the prompt and now supports the previously blocked `LIVE_PET` flow, but catalog read models still do not fully reflect valid SKU-priced products/live-pet structures.
  - Evidence: `src/trailgoods/services/catalog.py:329`, `src/trailgoods/services/catalog.py:563`, `src/trailgoods/services/catalog.py:782`, `src/trailgoods/services/catalog.py:916`

### 2. Delivery Completeness
- **2.1 Core prompt requirement coverage**
  - Conclusion: **Partial Pass**
  - Rationale: major functional areas exist and several previously missing paths are now implemented, but some prompt-critical behavior is still only partial in read/traceability surfaces.
  - Evidence: `src/trailgoods/services/assets.py:232`, `src/trailgoods/services/verification.py:212`, `src/trailgoods/services/verification.py:555`, `src/trailgoods/services/catalog.py:886`
- **2.2 Basic end-to-end deliverable rather than fragment/demo**
  - Conclusion: **Pass**
  - Rationale: the repository contains a real project structure with API routers, services, models, middleware, scripts, and a broad pytest suite.
  - Evidence: `README.md:1`, `src/trailgoods/main.py:15`, `tests/conftest.py:47`, `pyproject.toml:1`

### 3. Engineering and Architecture Quality
- **3.1 Structure and module decomposition**
  - Conclusion: **Pass**
  - Rationale: responsibilities are separated across endpoints, service layer, models, and middleware rather than collapsed into a single file.
  - Evidence: `src/trailgoods/main.py:15`, `src/trailgoods/api/deps.py:12`, `src/trailgoods/services/catalog.py:443`, `src/trailgoods/services/verification.py:186`
- **3.2 Maintainability and extensibility**
  - Conclusion: **Partial Pass**
  - Rationale: the codebase is maintainable overall, but read-model inconsistencies and incomplete verification revision snapshots show some cross-layer drift between business rules and retrieval/audit surfaces.
  - Evidence: `src/trailgoods/services/catalog.py:563`, `src/trailgoods/services/catalog.py:782`, `src/trailgoods/services/verification.py:555`, `src/trailgoods/models/verification.py:35`

### 4. Engineering Details and Professionalism
- **4.1 Error handling, logging, validation, API design**
  - Conclusion: **Partial Pass**
  - Rationale: request logging, auth guards, and validation are present, but one privileged audit path still drops actor attribution and catalog price reads are not aligned with valid SKU pricing.
  - Evidence: `src/trailgoods/middleware/logging.py:13`, `src/trailgoods/services/audit.py:9`, `src/trailgoods/services/catalog.py:523`, `src/trailgoods/services/catalog.py:782`
- **4.2 Product/service realism vs demo quality**
  - Conclusion: **Pass**
  - Rationale: the backend shape resembles a real service, with migrations, seed/bootstrap paths, request middleware, and domain-specific test coverage.
  - Evidence: `README.md:52`, `src/trailgoods/main.py:17`, `tests/conftest.py:51`, `tests/api/v1/test_regressions.py:16`

### 5. Prompt Understanding and Requirement Fit
- **5.1 Business goal, usage scenario, implicit constraints**
  - Conclusion: **Partial Pass**
  - Rationale: the business goal is broadly implemented and the earlier severe workflow gaps were corrected, but retrieval/traceability still falls short in a few prompt-relevant places.
  - Evidence: `src/trailgoods/services/catalog.py:329`, `src/trailgoods/services/assets.py:232`, `src/trailgoods/services/verification.py:212`, `src/trailgoods/services/verification.py:555`

### 6. Aesthetics
- **6.1 Frontend visual quality**
  - Conclusion: **Not Applicable**
  - Rationale: this repository is backend-only.
  - Evidence: `src/trailgoods/main.py:15`

## 5. Issues / Suggestions (Severity-Rated)

### High
- **Severity: High**
  - Title: Catalog read paths ignore valid SKU-level pricing
  - Conclusion: **Fail**
  - Evidence: `src/trailgoods/services/catalog.py:563`, `src/trailgoods/services/catalog.py:571`, `src/trailgoods/services/catalog.py:782`, `src/trailgoods/services/catalog.py:792`, `src/trailgoods/services/catalog.py:886`, `tests/api/v1/test_coverage.py:97`, `tests/api/v1/test_coverage.py:212`
  - Impact: a product can satisfy publish rules with valid default SKU pricing, but catalog list/detail pricing and price sorting still only read item-targeted prices. This creates prompt-level inconsistency in public commerce behavior.
  - Minimum actionable fix: resolve effective active default USD pricing from both item and SKU targets in catalog list/detail queries and add assertions for returned price/order, not just HTTP `200`.

### Medium
- **Severity: Medium**
  - Title: Price-book entry audit logs still miss actor attribution
  - Conclusion: **Fail**
  - Evidence: `src/trailgoods/api/v1/endpoints/catalog.py:791`, `src/trailgoods/services/catalog.py:453`, `src/trailgoods/services/catalog.py:523`, `src/trailgoods/services/audit.py:16`
  - Impact: `catalog.price.create` is privileged behavior, but the persisted audit row can still be unattributed even though the endpoint supplies an actor.
  - Minimum actionable fix: pass `actor_user_id=actor_user_id` into the `write_audit(...)` call in `create_price_book_entry` and add a regression test that checks the resulting audit row.

- **Severity: Medium**
  - Title: `LIVE_PET` detail responses still omit SPU/SKU structure
  - Conclusion: **Partial Fail**
  - Evidence: `src/trailgoods/services/catalog.py:329`, `src/trailgoods/services/catalog.py:916`, `tests/api/v1/test_regressions.py:17`
  - Impact: `LIVE_PET` items can now be created and published, but their detail response still hides the SPU/SKU data the backend now uses for that flow.
  - Minimum actionable fix: include `LIVE_PET` in the SPU/SKU detail branch or define and document a different serialized detail shape for live pets.

- **Severity: Medium**
  - Title: Verification revision snapshots are still incomplete
  - Conclusion: **Partial Fail**
  - Evidence: `src/trailgoods/models/verification.py:35`, `src/trailgoods/models/verification.py:40`, `src/trailgoods/services/verification.py:555`, `tests/api/v1/test_regressions.py:129`
  - Impact: revision rows now exist on update, but snapshots still omit enterprise registration and responsible-person fields, weakening the prompt’s traceability requirement.
  - Minimum actionable fix: expand `_build_snapshot(...)` to include every mutable verification field that can affect reviewer decisions.

- **Severity: Medium**
  - Title: Reorder alert deduplication is still time-window based rather than state-based
  - Conclusion: **Partial Fail**
  - Evidence: `src/trailgoods/services/inventory.py:1121`, `src/trailgoods/services/inventory.py:1127`, `src/trailgoods/services/inventory.py:1132`
  - Impact: while improved, the current logic can still generate repeated alerts for the same unresolved low-stock state after the 24-hour cutoff.
  - Minimum actionable fix: track active alert state per `(warehouse_id, sku_id, threshold)` and upsert/close alerts by condition, not by recent creation time alone.

## 6. Security Review Summary
- **Authentication entry points**
  - Conclusion: **Pass**
  - Evidence: `src/trailgoods/api/deps.py:12`, `src/trailgoods/api/deps.py:54`
  - Reasoning: bearer-session authentication and permission gating are statically present at the dependency layer.
- **Route-level authorization**
  - Conclusion: **Pass**
  - Evidence: `src/trailgoods/api/deps.py:54`, `src/trailgoods/api/v1/endpoints/catalog.py:783`
  - Reasoning: protected routes use dependency-based permission checks, including price-book entry creation.
- **Object-level authorization**
  - Conclusion: **Partial Pass**
  - Evidence: `src/trailgoods/services/catalog.py:469`, `src/trailgoods/services/catalog.py:481`, `src/trailgoods/services/assets.py:232`
  - Reasoning: ownership checks are broadly present and the admin upload ownership issue is fixed, but read-side data exposure for valid SKU-priced resources is still inconsistent.
- **Function-level authorization**
  - Conclusion: **Partial Pass**
  - Evidence: `src/trailgoods/api/v1/endpoints/verification.py:194`, `src/trailgoods/api/deps.py:64`
  - Reasoning: authorization is enforced centrally, but admin privilege still bypasses explicit permission checks in some sensitive-read paths.
- **Tenant / user data isolation**
  - Conclusion: **Pass**
  - Evidence: `src/trailgoods/services/assets.py:232`, `tests/api/v1/test_regressions.py:65`
  - Reasoning: the reviewed ownership regression around admin upload completion is now fixed and covered.
- **Admin / internal / debug protection**
  - Conclusion: **Partial Pass**
  - Evidence: `src/trailgoods/api/v1/endpoints/verification.py:192`, `src/trailgoods/api/deps.py:64`
  - Reasoning: no obvious unprotected debug endpoints were found, but admin access still short-circuits some explicit-permission semantics.

## 7. Tests and Logging Review
- **Unit tests**
  - Conclusion: **Partial Pass**
  - Evidence: `pyproject.toml:1`, `tests/api/v1/test_regressions.py:129`
  - Rationale: some tests inspect underlying persistence behavior directly, but the suite is still mostly API/integration-style.
- **API / integration tests**
  - Conclusion: **Pass**
  - Evidence: `tests/conftest.py:47`, `tests/api/v1/test_regressions.py:17`
  - Rationale: the repository contains broad API-level coverage and now includes targeted regression tests for several earlier defects.
- **Logging categories / observability**
  - Conclusion: **Pass**
  - Evidence: `src/trailgoods/main.py:17`, `src/trailgoods/middleware/logging.py:13`, `src/trailgoods/services/audit.py:9`
  - Rationale: request logging and structured audit logging both exist statically.
- **Sensitive-data leakage risk in logs / responses**
  - Conclusion: **Partial Pass**
  - Evidence: `src/trailgoods/api/v1/endpoints/verification.py:194`, `src/trailgoods/middleware/logging.py:23`
  - Rationale: request logs do not appear to emit payload bodies, but sensitive verification reads still depend partly on admin-role shortcut logic.

## 8. Test Coverage Assessment (Static Audit)

### 8.1 Test Overview
- Unit-style and API/integration-style tests both exist, with API coverage dominating.
- Frameworks: `pytest`, `pytest-asyncio`, `httpx.AsyncClient`, Alembic-backed DB setup.
- Test entry points: `pyproject.toml:1`, `tests/conftest.py:47`
- Documentation provides Docker-based test commands only.
- Evidence: `README.md:29`, `pyproject.toml:1`, `tests/conftest.py:35`

### 8.2 Coverage Mapping Table
| Requirement / Risk Point | Mapped Test Case(s) | Key Assertion / Fixture / Mock | Coverage Assessment | Gap | Minimum Test Addition |
|---|---|---|---|---|---|
| `LIVE_PET` create/publish lifecycle | `tests/api/v1/test_regressions.py:17` | publish returns `PUBLISHED` `tests/api/v1/test_regressions.py:59` | sufficient | No assertion on detail serialization | Add detail-read assertions for live-pet SPU/SKU visibility |
| Admin-completed upload ownership | `tests/api/v1/test_regressions.py:65` | final asset owner equals original uploader `tests/api/v1/test_regressions.py:91` | sufficient | No audit assertion for acting admin vs owner split | Add audit-row assertion for admin completion |
| Enterprise verification required fields | `tests/api/v1/test_regressions.py:96` | submit fails without registration number `tests/api/v1/test_regressions.py:121` | basically covered | No retrieval assertion for masked/unmasked enterprise fields | Add retrieval coverage for reviewer/admin/user views |
| Verification revision creation | `tests/api/v1/test_regressions.py:129` | revision count increases `tests/api/v1/test_regressions.py:158` | insufficient | Snapshot completeness is untested | Add assertions on `snapshot_json` contents |
| Catalog price sorting and pricing visibility | `tests/api/v1/test_coverage.py:212`, `tests/api/v1/test_coverage.py:218` | only checks `200` `tests/api/v1/test_coverage.py:215` | insufficient | No assertion that SKU-priced products get correct list/detail price or sort order | Add multi-item sort/value tests using SKU-targeted prices |
| Privileged audit attribution | `tests/api/v1/test_regressions.py:202` | category audit actor is non-null `tests/api/v1/test_regressions.py:211` | insufficient | No regression for `catalog.price.create` attribution | Add price-book entry audit assertion |
| Reorder alert deduplication | No dedicated test found in reviewed suite | N/A | missing | State-based repeat alert behavior is untested | Add repeated-scan regression test around unresolved low-stock conditions |

### 8.3 Security Coverage Audit
- **authentication**
  - Conclusion: **Basically covered**
  - Evidence: `tests/conftest.py:47`
  - Reasoning: the suite boots authenticated flows broadly, but this recheck did not remap the full auth matrix.
- **route authorization**
  - Conclusion: **Basically covered**
  - Evidence: `tests/api/v1/test_regressions.py:202`
  - Reasoning: privileged-route behavior is exercised, though not exhaustively for every route.
- **object-level authorization**
  - Conclusion: **Basically covered**
  - Evidence: `tests/api/v1/test_regressions.py:65`
  - Reasoning: the reviewed regression around ownership is covered, but catalog pricing/read-model mismatches could still hide defects.
- **tenant / data isolation**
  - Conclusion: **Basically covered**
  - Evidence: `tests/api/v1/test_regressions.py:91`
  - Reasoning: the strongest user-isolation regression reviewed here is now tested.
- **admin / internal protection**
  - Conclusion: **Insufficient**
  - Evidence: `src/trailgoods/api/v1/endpoints/verification.py:194`
  - Reasoning: the current recheck did not find targeted tests that lock down the admin sensitive-read shortcut semantics.

### 8.4 Final Coverage Judgment
- **Partial Pass**
- Major risks covered: `LIVE_PET` publish flow, admin upload ownership, enterprise verification submission requirements, and revision creation on update.
- Major uncovered risks: SKU-priced catalog read behavior, `catalog.price.create` audit attribution, verification snapshot completeness, and reorder-alert repeat behavior. Those gaps mean the current test suite could still pass while meaningful defects remain.

## 9. Final Notes
- The current static evidence supports `Partial Pass`.
- The strongest remaining defects are concentrated in catalog pricing read behavior, privileged audit attribution, and verification traceability completeness.
- Runtime behavior, deployment startup, and operational characteristics still require manual verification because they were not executed in this audit.
