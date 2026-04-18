# TrailGoods Commerce & Logistics API Static Audit

## 1. Verdict
- Overall conclusion: **Partial Pass**

## 2. Scope and Static Verification Boundary
- Reviewed: repository structure, README/config/manifests, Docker/static startup scripts, FastAPI entry points, route registration, dependencies, models, services, migrations, middleware, worker/jobs, backup/integrity scripts, and the test suite. Evidence examples: `README.md:1`, `docker-compose.yml:1`, `src/trailgoods/main.py:15`, `src/trailgoods/api/v1/router.py:10`, `tests/conftest.py:47`.
- Not reviewed: real runtime behavior, container startup, database connectivity, network reachability, Docker orchestration, filesystem permissions, performance under load, and actual backup/worker execution.
- Intentionally not executed: project startup, Docker, tests, external services, and any manual runtime verification, per audit boundary.
- Manual verification required: actual offline runtime behavior after startup, worker scheduling/execution, backup creation and restoreability, integrity/manifest job execution, p95 latency under 50 concurrent users, and any claim that depends on a live PostgreSQL or container environment.

## 3. Repository / Requirement Mapping Summary
- Prompt core goal: single-machine FastAPI + SQLAlchemy/PostgreSQL backend for identity/auth, verification, catalog, assets/share links, reviews/moderation, and multi-warehouse inventory with RBAC, auditability, local-disk assets, offline operation, and nightly backup/integrity jobs.
- Main implementation areas mapped: auth/RBAC/session services and endpoints (`src/trailgoods/api/v1/endpoints/auth.py:53`, `src/trailgoods/services/auth.py:45`), verification (`src/trailgoods/api/v1/endpoints/verification.py:63`, `src/trailgoods/services/verification.py:54`), catalog (`src/trailgoods/api/v1/endpoints/catalog.py:219`, `src/trailgoods/services/catalog.py:96`), assets (`src/trailgoods/api/v1/endpoints/assets.py:64`, `src/trailgoods/services/assets.py:50`), reviews/reports/appeals (`src/trailgoods/api/v1/endpoints/reviews.py:86`, `src/trailgoods/services/reviews.py:53`), inventory/orders (`src/trailgoods/api/v1/endpoints/inventory.py:108`, `src/trailgoods/services/inventory.py:28`), jobs/backups/integrity (`src/trailgoods/worker.py:130`, `scripts/backup.py:12`, `scripts/integrity.py:25`), and tests (`tests/api/v1/test_auth.py:11`, `tests/api/v1/test_security.py:95`, `tests/api/v1/test_inventory.py:162`).

## 4. Section-by-section Review

### 1. Hard Gates

#### 1.1 Documentation and static verifiability
- Conclusion: **Partial Pass**
- Rationale: The repository has clear startup/test instructions and the documented entry points are statically consistent with Docker, Alembic, seed, and worker scripts. Offline-first runtime behavior is not disproven by the delivered build process, but it also cannot be fully confirmed statically without execution.
- Evidence: `README.md:5`, `README.md:29`, `Dockerfile:5`, `docker-compose.yml:16`, `docker/api-entrypoint.sh:34`, `docker/worker-entrypoint.sh:37`, `docker/test-entrypoint.sh:35`
- Manual verification note: Real container startup and worker bootstrapping still require manual/runtime verification.

#### 1.2 Whether the delivered project materially deviates from the Prompt
- Conclusion: **Pass**
- Rationale: The implementation remains centered on the prompt’s business domains and single-machine service shape. The prior audit incorrectly treated offline-first runtime as an air-gapped build requirement; that was too strong based on the prompt and has been removed.
- Evidence: `README.md:1`, `README.md:5`, `src/trailgoods/api/v1/router.py:10`, `src/trailgoods/services/auth.py:45`, `src/trailgoods/services/inventory.py:28`

### 2. Delivery Completeness

#### 2.1 Core explicit requirements coverage
- Conclusion: **Partial Pass**
- Rationale: Most core domains are implemented: auth/session/logout/lockout, identity binding, verification cases and expiry, catalog/items/SPU/SKU/pricing, assets/share links, reviews/reports/appeals, inventory, stocktakes, and reorder alerts. Gaps remain around privileged identity-binding read behavior and uniform privileged-action audit coverage.
- Evidence: `src/trailgoods/api/v1/endpoints/auth.py:53`, `src/trailgoods/api/v1/endpoints/verification.py:63`, `src/trailgoods/api/v1/endpoints/catalog.py:219`, `src/trailgoods/api/v1/endpoints/assets.py:64`, `src/trailgoods/api/v1/endpoints/reviews.py:241`, `src/trailgoods/api/v1/endpoints/inventory.py:429`, `src/trailgoods/worker.py:130`
- Manual verification note: Backup/integrity execution and performance targets cannot be confirmed statically.

#### 2.2 End-to-end deliverable vs partial/demo
- Conclusion: **Pass**
- Rationale: The repository is a multi-module application with migrations, Docker packaging, seed/bootstrap scripts, background job support, and a broad test suite. It is not a single-file or illustrative stub.
- Evidence: `README.md:1`, `src/trailgoods/api/v1/router.py:10`, `alembic/versions/0001_slice1_auth_rbac_sessions_audit.py:1`, `docker-compose.yml:1`, `tests/conftest.py:47`

### 3. Engineering and Architecture Quality

#### 3.1 Structure and module decomposition
- Conclusion: **Pass**
- Rationale: The code is reasonably decomposed by domain into API, services, models, middleware, core config/database, scripts, and tests. Responsibilities are broadly understandable and not collapsed into a single module.
- Evidence: `src/trailgoods/api/v1/endpoints/auth.py:42`, `src/trailgoods/services/auth.py:45`, `src/trailgoods/models/auth.py:21`, `src/trailgoods/services/inventory.py:28`, `src/trailgoods/worker.py:17`

#### 3.2 Maintainability and extensibility
- Conclusion: **Partial Pass**
- Rationale: The service-layer decomposition and migrations support extension, but authorization and audit concerns are not enforced uniformly. Some permission-protected routes rely on ad hoc checks rather than a consistently applied policy boundary.
- Evidence: `src/trailgoods/api/v1/endpoints/auth.py:210`, `src/trailgoods/api/v1/endpoints/assets.py:97`, `src/trailgoods/api/v1/endpoints/inventory.py:715`, `src/trailgoods/services/audit.py:9`

### 4. Engineering Details and Professionalism

#### 4.1 Error handling, logging, validation, API design
- Conclusion: **Partial Pass**
- Rationale: Input validation and response handling are generally present, request correlation IDs exist, and request logs are structured JSON. However, privileged-action audit logging is incomplete, worker logs are not structured, and share-link passwords are accepted through query parameters.
- Evidence: `src/trailgoods/schemas/auth.py:13`, `src/trailgoods/middleware/request_id.py:11`, `src/trailgoods/middleware/logging.py:14`, `src/trailgoods/api/v1/endpoints/assets.py:354`, `src/trailgoods/api/v1/endpoints/assets.py:392`
- Manual verification note: Production observability quality and log aggregation behavior require runtime verification.

#### 4.2 Real product/service vs demo
- Conclusion: **Pass**
- Rationale: The repository includes migrations, role/permission seeding, worker jobs, integrity/backup scripts, and comprehensive API slices. It is shaped like a real backend service rather than a teaching demo.
- Evidence: `alembic/versions/0004_slice4_inventory_orders.py:1`, `scripts/seed.py:11`, `scripts/bootstrap_jobs.py:12`, `src/trailgoods/worker.py:130`

### 5. Prompt Understanding and Requirement Fit

#### 5.1 Business goal, usage scenario, implicit constraints
- Conclusion: **Partial Pass**
- Rationale: Domain understanding is generally good and the repository materially implements the requested business domains. The remaining shortcomings are important but narrower: the prompt’s “mandatory audit logging for all privileged actions” is not satisfied consistently across permission-gated operations, and some fine-grained authorization behavior remains incomplete.
- Evidence: `src/trailgoods/api/v1/endpoints/assets.py:97`, `src/trailgoods/services/assets.py:121`, `src/trailgoods/api/v1/endpoints/inventory.py:715`, `src/trailgoods/api/v1/endpoints/auth.py:210`
- Manual verification note: Runtime backup/performance constraints also remain unproven statically.

### 6. Aesthetics

#### 6.1 Frontend-only / full-stack visual review
- Conclusion: **Not Applicable**
- Rationale: This repository is a backend API service with no frontend UI delivered in scope.
- Evidence: `README.md:3`, `src/trailgoods/main.py:15`

## 5. Issues / Suggestions (Severity-Rated)

### High

#### 1. Mandatory audit logging is not enforced uniformly for privileged actions
- Severity: **High**
- Conclusion: **Fail**
- Evidence: `src/trailgoods/api/v1/endpoints/assets.py:97`, `src/trailgoods/services/assets.py:121`, `src/trailgoods/api/v1/endpoints/assets.py:196`, `src/trailgoods/api/v1/endpoints/auth.py:263`, `src/trailgoods/api/v1/endpoints/inventory.py:715`, `src/trailgoods/services/audit.py:9`
- Impact: The prompt requires audit logging for all privileged actions, but several permission-protected operations do not write audit records, including upload-part handling, asset reads, identity-binding reads, and reservation listing. This leaves privileged access and resource mutations partially untraceable.
- Minimum actionable fix: Apply a uniform audit policy to every permission-gated endpoint/service, including actor, action, resource, request ID, and outcome.

### Medium

#### 2. Identity-binding creation bypasses the permission model
- Severity: **Medium**
- Conclusion: **Partial Fail**
- Evidence: `src/trailgoods/api/v1/endpoints/auth.py:210`, `src/trailgoods/api/v1/endpoints/auth.py:215`, `src/trailgoods/api/v1/endpoints/auth.py:265`, `scripts/seed.py:26`, `scripts/seed.py:99`
- Impact: The create route uses only `get_current_user_and_session`, while the read route correctly requires `identity_binding.read_own`. This weakens the fine-grained RBAC model promised by the prompt because any authenticated role can create bindings regardless of whether it has `identity_binding.create`.
- Minimum actionable fix: Change the create route dependency to `require_permission("identity_binding.create")` and add a regression test for a role lacking that permission.

#### 3. Share-link passwords are accepted in query parameters
- Severity: **Medium**
- Conclusion: **Partial Fail**
- Evidence: `src/trailgoods/api/v1/endpoints/assets.py:355`, `src/trailgoods/api/v1/endpoints/assets.py:396`
- Impact: Query-string passwords are easier to leak through browser history, access logs, proxy logs, and copied URLs. This is avoidable exposure for a feature explicitly tied to asset privacy.
- Minimum actionable fix: Accept share-link passwords via header or POST body, and keep download endpoints free of secret-bearing query parameters.

#### 4. Sensitive identity-binding values are always masked; there is no explicit privileged read path
- Severity: **Medium**
- Conclusion: **Partial Fail**
- Evidence: `src/trailgoods/api/v1/endpoints/auth.py:238`, `src/trailgoods/api/v1/endpoints/auth.py:242`, `src/trailgoods/api/v1/endpoints/auth.py:263`, `src/trailgoods/api/v1/router.py:11`
- Impact: The prompt requires sensitive ID fields to be masked except for Reviewer/Admin with explicit permission. Verification cases implement that pattern, but identity bindings always return masked values and no privileged binding-read endpoint exists, so the requirement is only partially implemented.
- Minimum actionable fix: Add an explicit permissioned binding-read path for Reviewer/Admin, decrypt `external_id_encrypted` only for authorized callers, and audit those reads.

#### 5. Performance target has no static evidence
- Severity: **Medium**
- Conclusion: **Cannot Confirm Statistically**
- Evidence: `README.md:1`, `tests/api/v1`, `src/trailgoods/middleware/logging.py:14`
- Impact: The prompt requires p95 < 300 ms under 50 concurrent users, but the repository provides no benchmark artifacts, load-test configuration, or performance evidence. Severe latency defects could remain undetected while the static test suite still passes.
- Minimum actionable fix: Add reproducible load-test assets and checked-in benchmark evidence tied to the documented deployment profile.

### Low

#### 6. Worker/job logging is not consistently structured
- Severity: **Low**
- Conclusion: **Partial Fail**
- Evidence: `src/trailgoods/middleware/logging.py:25`, `src/trailgoods/worker.py:63`, `src/trailgoods/worker.py:66`, `scripts/bootstrap_jobs.py:51`
- Impact: Request logs are structured JSON, but worker/job logs and bootstrap output are plain text. Troubleshooting cross-cutting background-job behavior will be less consistent than API request tracing.
- Minimum actionable fix: Emit worker/bootstrap logs as structured JSON with job type, job ID, status, and timestamps.

## 6. Security Review Summary

- Authentication entry points: **Pass**
  - Evidence: `src/trailgoods/api/v1/endpoints/auth.py:53`, `src/trailgoods/services/auth.py:173`, `src/trailgoods/services/auth.py:263`
  - Reasoning: Register/login/logout/password rotation/session auth are implemented with password validation, token hashing, idle timeout, failed-login lockout, and forced session revocation.

- Route-level authorization: **Partial Pass**
  - Evidence: `src/trailgoods/api/deps.py:54`, `src/trailgoods/api/v1/endpoints/catalog.py:137`, `src/trailgoods/api/v1/endpoints/reviews.py:206`, `src/trailgoods/api/v1/endpoints/auth.py:210`
  - Reasoning: Most protected routes use `require_permission` or explicit ownership checks, but identity-binding creation bypasses the permission model.

- Object-level authorization: **Pass**
  - Evidence: `src/trailgoods/api/v1/endpoints/assets.py:211`, `src/trailgoods/api/v1/endpoints/catalog.py:407`, `src/trailgoods/services/inventory.py:636`, `src/trailgoods/services/reviews.py:133`, `src/trailgoods/services/verification.py:140`
  - Reasoning: Asset, item, order, review, and verification attachment ownership checks are present and the static tests exercise several of them.

- Function-level authorization: **Partial Pass**
  - Evidence: `src/trailgoods/api/deps.py:54`, `src/trailgoods/api/deps.py:77`, `src/trailgoods/api/v1/endpoints/verification.py:184`, `src/trailgoods/api/v1/endpoints/auth.py:210`
  - Reasoning: Permission and role helpers exist and are widely used, but not all sensitive operations are consistently wrapped with the correct permission guard.

- Tenant / user data isolation: **Pass**
  - Evidence: `src/trailgoods/services/inventory.py:636`, `src/trailgoods/services/reviews.py:446`, `src/trailgoods/api/v1/endpoints/assets.py:211`, `tests/api/v1/test_security.py:97`, `tests/api/v1/test_security.py:547`
  - Reasoning: Order ownership, appeal ownership, and asset ownership checks are implemented and covered by tests.

- Admin / internal / debug protection: **Partial Pass**
  - Evidence: `src/trailgoods/api/v1/endpoints/auth.py:276`, `src/trailgoods/api/v1/endpoints/auth.py:344`, `src/trailgoods/api/v1/endpoints/reviews.py:481`, `tests/api/v1/test_auth.py:419`, `tests/api/v1/test_auth.py:462`
  - Reasoning: Admin/internal routes are permission-gated and tested, but the repository does not show a single uniform policy wrapper and some non-admin privileged routes still miss audit controls.

## 7. Tests and Logging Review

- Unit tests: **Partial Pass**
  - Evidence: `tests/api/v1/test_coverage.py:1263`
  - Reasoning: There are a few direct/helper-level tests, but the suite is mostly API/integration-oriented rather than a broad unit-test layer.

- API / integration tests: **Pass**
  - Evidence: `tests/conftest.py:47`, `tests/api/v1/test_auth.py:11`, `tests/api/v1/test_security.py:95`, `tests/api/v1/test_inventory.py:162`, `tests/api/v1/test_reviews.py:236`, `tests/api/v1/test_verification.py:1`
  - Reasoning: The repository has extensive HTTP-level coverage across auth, security, inventory, verification, reviews, assets, and catalog behavior.

- Logging categories / observability: **Partial Pass**
  - Evidence: `src/trailgoods/middleware/logging.py:14`, `src/trailgoods/middleware/request_id.py:13`, `src/trailgoods/services/audit.py:23`, `src/trailgoods/worker.py:63`
  - Reasoning: Request correlation IDs and request/audit logs exist, but worker logs are plain text and audit coverage is incomplete.

- Sensitive-data leakage risk in logs / responses: **Partial Pass**
  - Evidence: `src/trailgoods/middleware/logging.py:25`, `src/trailgoods/services/reviews.py:15`, `src/trailgoods/services/verification.py:581`, `src/trailgoods/api/v1/endpoints/assets.py:358`, `src/trailgoods/api/v1/endpoints/assets.py:396`
  - Reasoning: Request logs avoid bodies and query strings, reviews strip basic email/phone PII, and verification responses mask sensitive fields by default. Risk remains because share-link passwords are accepted as query parameters and privileged audit coverage is incomplete.

## 8. Test Coverage Assessment (Static Audit)

### 8.1 Test Overview
- Unit/API tests exist under `tests/api/v1` and use `pytest` + `pytest-asyncio` + `httpx` ASGI transport. Evidence: `pyproject.toml:1`, `tests/conftest.py:4`, `tests/conftest.py:124`
- Test entry points are documented for Docker execution in README and configured through `tool.pytest.ini_options`. Evidence: `README.md:29`, `README.md:41`, `pyproject.toml:1`
- Test setup rebuilds the schema via Alembic and seeds roles/permissions before each client fixture. Evidence: `tests/conftest.py:51`, `tests/conftest.py:63`, `tests/conftest.py:71`

### 8.2 Coverage Mapping Table

| Requirement / Risk Point | Mapped Test Case(s) | Key Assertion / Fixture / Mock | Coverage Assessment | Gap | Minimum Test Addition |
|---|---|---|---|---|---|
| Password rules, registration, login | `tests/api/v1/test_auth.py:13`, `tests/api/v1/test_auth.py:59`, `tests/api/v1/test_auth.py:92` | 201/422/401 assertions on register/login outcomes at `tests/api/v1/test_auth.py:18`, `tests/api/v1/test_auth.py:64`, `tests/api/v1/test_auth.py:110` | sufficient | None material | Add one explicit email-duplicate test if desired |
| Idle timeout and 5-failure forced logout | `tests/api/v1/test_auth.py:260`, `tests/api/v1/test_auth.py:289` | Lockout invalidates session at `tests/api/v1/test_auth.py:280`; idle timeout mocked at `tests/api/v1/test_auth.py:297` | basically covered | No direct DB assertion that all active sessions were revoked by lockout | Add a multi-session lockout test asserting every prior session becomes unusable |
| Identity binding create/list/rebind | `tests/api/v1/test_auth.py:309`, `tests/api/v1/test_auth.py:330`, `tests/api/v1/test_auth.py:351` | Masked external ID asserted at `tests/api/v1/test_auth.py:327`; rebind revocation at `tests/api/v1/test_auth.py:381` | basically covered | No test that a role lacking `identity_binding.create` is rejected | Add a negative RBAC test for binding creation |
| Verification create/update/submit/decision/masking | `tests/api/v1/test_verification.py:18`, `tests/api/v1/test_verification.py:169`, `tests/api/v1/test_regressions.py:563`, `tests/api/v1/test_regressions.py:596` | Reviewer 403/decision checks at `tests/api/v1/test_verification.py:220`; sensitive masking/unmasking at `tests/api/v1/test_regressions.py:587`, `tests/api/v1/test_regressions.py:619` | sufficient | Expiry worker flow itself is not exercised end-to-end | Add a job-handler-level expiry test covering status transition to `EXPIRED` |
| Catalog visibility, ownership, SKU/live-pet detail | `tests/api/v1/test_security.py:269`, `tests/api/v1/test_coverage.py:252`, `tests/api/v1/test_regressions.py:372` | Draft visibility assertions at `tests/api/v1/test_security.py:287`, `tests/api/v1/test_coverage.py:267`; LIVE_PET detail assertions at `tests/api/v1/test_regressions.py:409` | sufficient | No test of attribute CRUD authorization boundaries | Add owner/non-owner attribute mutation tests |
| Order creation, reservation, deduction, rollback | `tests/api/v1/test_inventory.py:163`, `tests/api/v1/test_inventory.py:217`, `tests/api/v1/test_inventory.py:276`, `tests/api/v1/test_coverage.py:502` | Sellable/reserved/on-hand assertions at `tests/api/v1/test_inventory.py:198`, `tests/api/v1/test_inventory.py:213`, `tests/api/v1/test_inventory.py:309` | sufficient | No concurrency/idempotency collision test beyond sequential repeats | Add parallel reservation/deduction contention tests |
| Object-level order and asset isolation | `tests/api/v1/test_security.py:97`, `tests/api/v1/test_security.py:179`, `tests/api/v1/test_security.py:209`, `tests/api/v1/test_security.py:315` | 403 assertions at `tests/api/v1/test_security.py:114`, `tests/api/v1/test_security.py:192`, `tests/api/v1/test_security.py:234`, `tests/api/v1/test_security.py:347` | sufficient | None material | Add reservation listing isolation test if exposing that endpoint broadly later |
| Review/report/appeal governance | `tests/api/v1/test_reviews.py:238`, `tests/api/v1/test_reviews.py:278`, `tests/api/v1/test_security.py:547` | Report SLA field asserted at `tests/api/v1/test_reviews.py:257`; appeal ownership 403 at `tests/api/v1/test_security.py:569` | basically covered | No test for 14-day appeal expiry boundary or report triage breach worker | Add appeal-window expiry and report-SLA worker tests |
| Assets, share links, password/max-download behavior | `tests/api/v1/test_assets.py:230`, `tests/api/v1/test_assets.py:262`, `tests/api/v1/test_assets.py:283`, `tests/api/v1/test_security.py:177` | Share-link password and download-limit assertions at `tests/api/v1/test_assets.py:268`, `tests/api/v1/test_assets.py:292`; ownership 403 at `tests/api/v1/test_security.py:187` | basically covered | No test asserts passwords are not exposed via URL or logs; no audit-coverage tests for upload-part/read | Add tests around audit records for asset operations and avoid query-param password transport |
| Audit/request correlation | `tests/api/v1/test_auth.py:451`, `tests/api/v1/test_auth.py:475`, `tests/api/v1/test_regressions.py:243`, `tests/api/v1/test_regressions.py:344` | Request-ID echo at `tests/api/v1/test_auth.py:485`; audit actor assertions at `tests/api/v1/test_regressions.py:251`, `tests/api/v1/test_regressions.py:361` | insufficient | Tests cover only selected audit paths, not all privileged routes; missing coverage aligns with uncovered implementation gap | Add an audit-completeness matrix for every permission-gated endpoint/service |
| Offline runtime behavior, backups, performance | No meaningful test coverage | Backup/integrity code exists at `scripts/backup.py:12`, `scripts/integrity.py:25` | missing / cannot confirm | No static test evidence for offline runtime operation after startup, backup success, restoreability, or latency target | Add reproducible runtime verification artifacts and benchmark evidence |

### 8.3 Security Coverage Audit
- Authentication: **Basically covered**
  - Evidence: `tests/api/v1/test_auth.py:92`, `tests/api/v1/test_auth.py:260`, `tests/api/v1/test_auth.py:289`
  - Reasoning: Login, lockout, logout, password rotation, and idle timeout are exercised. Multi-session forced-logout breadth is not exhaustively tested.

- Route authorization: **Basically covered**
  - Evidence: `tests/api/v1/test_auth.py:419`, `tests/api/v1/test_reviews.py:214`, `tests/api/v1/test_security.py:97`
  - Reasoning: Many 403 paths are tested, but the suite does not catch the missing permission guard on identity-binding creation.

- Object-level authorization: **Covered**
  - Evidence: `tests/api/v1/test_security.py:97`, `tests/api/v1/test_security.py:179`, `tests/api/v1/test_security.py:315`, `tests/api/v1/test_security.py:547`
  - Reasoning: Ownership boundaries for orders, assets, verification attachments, and appeals are meaningfully exercised.

- Tenant / data isolation: **Covered**
  - Evidence: `tests/api/v1/test_security.py:110`, `tests/api/v1/test_security.py:287`, `tests/api/v1/test_regressions.py:596`
  - Reasoning: Cross-user order misuse, draft item visibility, and masked verification reads are tested.

- Admin / internal protection: **Basically covered**
  - Evidence: `tests/api/v1/test_auth.py:451`, `tests/api/v1/test_auth.py:462`, `tests/api/v1/test_reviews.py:260`
  - Reasoning: Admin/reviewer-only endpoints are tested, but the suite does not verify all internal routes for audit completeness or least-privilege consistency.

### 8.4 Final Coverage Judgment
- **Partial Pass**
- Major risks covered: auth basics, lockout/idle timeout, core verification flow, object ownership on orders/assets, inventory reserve/deduct/cancel, review/report/appeal basics, request-ID echo, and selected audit attribution.
- Major uncovered risks: comprehensive privileged-action audit coverage, binding-create RBAC regression, backup/restore behavior, performance target evidence, offline runtime behavior after startup, and the privacy risk introduced by query-string share-link passwords. The current tests could still pass while those defects remain.

## 9. Final Notes
- The repository is substantial and broadly aligned to the business domain, but the acceptance outcome is driven by prompt-critical gaps rather than breadth of features.
- The strongest static defects are incomplete enforcement of mandatory privileged-action auditing and inconsistent fine-grained authorization around identity bindings.
- Runtime-sensitive claims not exercised here should remain treated as **Cannot Confirm Statistically** until verified manually.
