# Test Coverage Audit

## Project Type Detection
- Declared in README top: `backend` (`README.md:3`).
- Inference check: repository contains FastAPI backend only (`src/trailgoods/...`), no frontend codebase detected.

## Backend Endpoint Inventory
- Total unique endpoints (`METHOD + fully resolved PATH`): **86**
- Source evidence: `src/trailgoods/api/v1/endpoints/*.py` route decorators, each router uses prefix `/api/v1`.

### Endpoint List
```text
delete /api/v1/admin/sensitive-words/{*}
delete /api/v1/assets/{*}
delete /api/v1/items/{*}/attributes/{*}
delete /api/v1/items/{*}/tags/{*}
delete /api/v1/sessions/{*}
delete /api/v1/share-links/{*}
get /api/v1/admin/audit-logs
get /api/v1/admin/identity-bindings/{*}
get /api/v1/admin/reorder-alerts
get /api/v1/admin/sensitive-words
get /api/v1/appeals
get /api/v1/assets/{*}
get /api/v1/catalog/items
get /api/v1/categories
get /api/v1/identity-bindings
get /api/v1/inventory/balances
get /api/v1/items/{*}
get /api/v1/items/{*}/attributes
get /api/v1/items/{*}/reviews
get /api/v1/reports
get /api/v1/reservations
get /api/v1/sessions/me
get /api/v1/share-links/{*}
get /api/v1/share-links/{*}/download
get /api/v1/tags
get /api/v1/verification-cases
get /api/v1/verification-cases/{*}
get /api/v1/verification-cases/{*}/status
get /api/v1/warehouses
patch /api/v1/items/{*}
patch /api/v1/reviews/{*}
patch /api/v1/skus/{*}
patch /api/v1/verification-cases/{*}
post /api/v1/admin/clear-challenge
post /api/v1/admin/force-logout
post /api/v1/admin/roles/assign
post /api/v1/admin/sensitive-words
post /api/v1/appeals
post /api/v1/appeals/{*}/decision
post /api/v1/assets/uploads
post /api/v1/assets/uploads/batch-complete
post /api/v1/assets/uploads/{*}/complete
post /api/v1/assets/{*}/share-links
post /api/v1/auth/login
post /api/v1/auth/logout
post /api/v1/auth/logout-all
post /api/v1/auth/password-rotate
post /api/v1/auth/register
post /api/v1/categories
post /api/v1/identity-bindings
post /api/v1/inbound-docs
post /api/v1/inbound-docs/{*}/lines
post /api/v1/inbound-docs/{*}/post
post /api/v1/items
post /api/v1/items/{*}/attributes
post /api/v1/items/{*}/media
post /api/v1/items/{*}/publish
post /api/v1/items/{*}/reviews
post /api/v1/items/{*}/tags/{*}
post /api/v1/items/{*}/unpublish
post /api/v1/orders
post /api/v1/orders/{*}/cancel
post /api/v1/orders/{*}/deduct
post /api/v1/orders/{*}/reserve
post /api/v1/outbound-docs
post /api/v1/outbound-docs/{*}/lines
post /api/v1/outbound-docs/{*}/post
post /api/v1/price-books
post /api/v1/price-books/{*}/entries
post /api/v1/reports
post /api/v1/reports/{*}/close
post /api/v1/reports/{*}/triage
post /api/v1/reviews/{*}/moderate
post /api/v1/spus
post /api/v1/spus/{*}/skus
post /api/v1/stocktakes
post /api/v1/stocktakes/{*}/lines
post /api/v1/stocktakes/{*}/post
post /api/v1/tags
post /api/v1/verification-cases
post /api/v1/verification-cases/{*}/decision
post /api/v1/verification-cases/{*}/renew
post /api/v1/verification-cases/{*}/submit
post /api/v1/verification-cases/{*}/withdraw
post /api/v1/warehouses
put /api/v1/assets/uploads/{*}/parts/{*}
```

## API Test Mapping Table
- Coverage criterion applied: exact `METHOD + PATH` request seen in tests, through `httpx.AsyncClient` against bootstrapped app (`tests/conftest.py:47-107`).
- Test transport: ASGI transport in-process (`ASGITransport(app=app)`), real routing/middleware/handlers executed.

### Mapping (`endpoint | covered | evidence`)
```text
delete /api/v1/admin/sensitive-words/{*}|yes|tests/api/v1/test_endpoint_coverage.py:274:        delete_resp = await client.delete(
delete /api/v1/assets/{*}|yes|tests/api/v1/test_assets.py:209:        resp = await client.delete(
delete /api/v1/items/{*}/attributes/{*}|yes|tests/api/v1/test_regressions.py:234:        del_r = await client.delete(
delete /api/v1/items/{*}/tags/{*}|yes|tests/api/v1/test_additions.py:50:        del_resp = await client.delete(
delete /api/v1/sessions/{*}|yes|tests/api/v1/test_auth.py:234:        resp = await client.delete(
delete /api/v1/share-links/{*}|yes|tests/api/v1/test_endpoint_coverage.py:127:        disable_resp = await client.delete(
get /api/v1/admin/audit-logs|yes|tests/api/v1/test_audit_fixes.py:19:    resp = await client.get(
get /api/v1/admin/identity-bindings/{*}|yes|tests/api/v1/test_audit_fixes.py:369:        resp = await client.get(
get /api/v1/admin/reorder-alerts|yes|tests/api/v1/test_inventory.py:367:        resp = await client.get("/api/v1/admin/reorder-alerts", headers=auth_header(admin_token))
get /api/v1/admin/sensitive-words|yes|tests/api/v1/test_endpoint_coverage.py:306:        list_resp = await client.get(
get /api/v1/appeals|yes|tests/api/v1/test_endpoint_coverage.py:381:        list_resp = await client.get("/api/v1/appeals", headers=auth_header(reviewer_token))
get /api/v1/assets/{*}|yes|tests/api/v1/test_audit_fixes.py:84:        resp = await client.get(
get /api/v1/catalog/items|yes|tests/api/v1/test_coverage.py:209:        r = await client.get("/api/v1/catalog/items", params={"sort_by": "title_asc"})
get /api/v1/categories|yes|tests/api/v1/test_catalog.py:94:        resp = await client.get("/api/v1/categories")
get /api/v1/identity-bindings|yes|tests/api/v1/test_audit_fixes.py:114:        resp = await client.get(
get /api/v1/inventory/balances|yes|tests/api/v1/test_inventory.py:130:        bal_resp = await client.get("/api/v1/inventory/balances", headers=auth_header(admin_token), params={
get /api/v1/items/{*}|yes|tests/api/v1/test_security.py:287:        resp = await client.get(
get /api/v1/items/{*}/attributes|yes|tests/api/v1/test_regressions.py:230:        list_r = await client.get(f"/api/v1/items/{item['id']}/attributes", headers=auth_header(admin_token))
get /api/v1/items/{*}/reviews|yes|tests/api/v1/test_reviews.py:125:        resp = await client.get(f"/api/v1/items/{item['id']}/reviews")
get /api/v1/reports|yes|tests/api/v1/test_coverage.py:1277:        resp = await client.get("/api/v1/reports", headers=auth_header(reviewer_token))
get /api/v1/reservations|yes|tests/api/v1/test_audit_fixes.py:129:        resp = await client.get(
get /api/v1/sessions/me|yes|tests/api/v1/test_auth.py:131:        resp2 = await client.get(
get /api/v1/share-links/{*}|yes|tests/api/v1/test_audit_fixes.py:256:        resp_no = await client.get(f"/api/v1/share-links/{token}")
get /api/v1/share-links/{*}/download|yes|tests/api/v1/test_audit_fixes.py:308:        resp_no = await client.get(f"/api/v1/share-links/{token}/download")
get /api/v1/tags|yes|tests/api/v1/test_catalog.py:112:        resp = await client.get("/api/v1/tags")
get /api/v1/verification-cases|yes|tests/api/v1/test_endpoint_coverage.py:412:        list_resp = await client.get(
get /api/v1/verification-cases/{*}|yes|tests/api/v1/test_verification.py:249:        resp = await client.get(
get /api/v1/verification-cases/{*}/status|yes|tests/api/v1/test_verification.py:296:        resp = await client.get(
get /api/v1/warehouses|yes|tests/api/v1/test_inventory.py:109:        resp = await client.get("/api/v1/warehouses", headers=auth_header(admin_token))
patch /api/v1/items/{*}|yes|tests/api/v1/test_catalog.py:203:        resp2 = await client.patch(f"/api/v1/items/{item['id']}", headers=auth_header(admin_token), json={
patch /api/v1/reviews/{*}|yes|tests/api/v1/test_reviews.py:147:        edit_resp = await client.patch(
patch /api/v1/skus/{*}|yes|tests/api/v1/test_coverage.py:173:        r = await client.patch(f"/api/v1/skus/{sku['id']}", headers=auth_header(admin_token), json={
patch /api/v1/verification-cases/{*}|yes|tests/api/v1/test_verification.py:29:    resp = await client.patch(
post /api/v1/admin/clear-challenge|yes|tests/api/v1/test_endpoint_coverage.py:82:        clear_resp = await client.post(
post /api/v1/admin/force-logout|yes|tests/api/v1/test_auth.py:449:        resp = await client.post(
post /api/v1/admin/roles/assign|yes|tests/api/v1/test_audit_fixes.py:172:        await client.post(
post /api/v1/admin/sensitive-words|yes|tests/api/v1/test_reviews.py:53:        sw_resp = await client.post(
post /api/v1/appeals|yes|tests/api/v1/test_security.py:569:        resp = await client.post(
post /api/v1/appeals/{*}/decision|yes|tests/api/v1/test_reviews.py:311:        decide_resp = await client.post(
post /api/v1/assets/uploads|yes|tests/api/v1/test_audit_fixes.py:49:        resp = await client.post("/api/v1/assets/uploads", headers=auth_header(token), json={
post /api/v1/assets/uploads/batch-complete|yes|tests/api/v1/test_assets.py:154:        resp = await client.post("/api/v1/assets/uploads/batch-complete", headers=headers, json={
post /api/v1/assets/uploads/{*}/complete|yes|tests/api/v1/test_assets.py:111:        resp4 = await client.post(
post /api/v1/assets/{*}/share-links|yes|tests/api/v1/test_audit_fixes.py:247:        resp = await client.post(
post /api/v1/auth/login|yes|tests/conftest.py:145:    resp = await client.post("/api/v1/auth/login", json={
post /api/v1/auth/logout|yes|tests/api/v1/test_auth.py:125:        resp = await client.post(
post /api/v1/auth/logout-all|yes|tests/api/v1/test_auth.py:142:        resp = await client.post(
post /api/v1/auth/password-rotate|yes|tests/api/v1/test_auth.py:166:        resp = await client.post(
post /api/v1/auth/register|yes|tests/conftest.py:136:    resp = await client.post("/api/v1/auth/register", json={
post /api/v1/categories|yes|tests/api/v1/test_additions.py:21:        cat_resp = await client.post("/api/v1/categories", headers=auth_header(admin_token), json={
post /api/v1/identity-bindings|yes|tests/api/v1/test_audit_fixes.py:103:        await client.post(
post /api/v1/inbound-docs|yes|tests/api/v1/test_security.py:71:    doc_resp = await client.post("/api/v1/inbound-docs", headers=auth_header(admin_token), json={
post /api/v1/inbound-docs/{*}/lines|yes|tests/api/v1/test_security.py:75:    await client.post(f"/api/v1/inbound-docs/{doc['id']}/lines", headers=auth_header(admin_token), json={
post /api/v1/inbound-docs/{*}/post|yes|tests/api/v1/test_security.py:78:    await client.post(f"/api/v1/inbound-docs/{doc['id']}/post", headers=auth_header(admin_token))
post /api/v1/items|yes|tests/api/v1/test_security.py:28:    item_resp = await client.post("/api/v1/items", headers=auth_header(admin_token), json={
post /api/v1/items/{*}/attributes|yes|tests/api/v1/test_regressions.py:221:        attr_r = await client.post(
post /api/v1/items/{*}/media|yes|tests/api/v1/test_reviews.py:30:    await client.post(f"/api/v1/items/{item['id']}/media", headers=auth_header(admin_token), json={
post /api/v1/items/{*}/publish|yes|tests/api/v1/test_security.py:69:    await client.post(f"/api/v1/items/{item['id']}/publish", headers=auth_header(admin_token))
post /api/v1/items/{*}/reviews|yes|tests/api/v1/test_security.py:485:        resp = await client.post(
post /api/v1/items/{*}/tags/{*}|yes|tests/api/v1/test_additions.py:37:        add_resp = await client.post(
post /api/v1/items/{*}/unpublish|yes|tests/api/v1/test_catalog.py:322:        resp = await client.post(
post /api/v1/orders|yes|tests/api/v1/test_security.py:84:    resp = await client.post("/api/v1/orders", headers=auth_header(token), json={
post /api/v1/orders/{*}/cancel|yes|tests/api/v1/test_inventory.py:298:        cancel_resp = await client.post(
post /api/v1/orders/{*}/deduct|yes|tests/api/v1/test_security.py:133:        resp = await client.post(
post /api/v1/orders/{*}/reserve|yes|tests/api/v1/test_security.py:110:        resp = await client.post(
post /api/v1/outbound-docs|yes|tests/api/v1/test_coverage_boost.py:291:        resp = await client.post("/api/v1/outbound-docs", headers=auth_header(admin_token), json={
post /api/v1/outbound-docs/{*}/lines|yes|tests/api/v1/test_coverage.py:323:        line_r = await client.post(f"/api/v1/outbound-docs/{ob['id']}/lines", headers=auth_header(admin_token), json={
post /api/v1/outbound-docs/{*}/post|yes|tests/api/v1/test_coverage.py:328:        post_r = await client.post(f"/api/v1/outbound-docs/{ob['id']}/post", headers=auth_header(admin_token))
post /api/v1/price-books|yes|tests/api/v1/test_security.py:48:    pb_resp = await client.post("/api/v1/price-books", headers=auth_header(admin_token), json={
post /api/v1/price-books/{*}/entries|yes|tests/api/v1/test_reviews.py:39:    await client.post(f"/api/v1/price-books/{pb['id']}/entries", headers=auth_header(admin_token), json={
post /api/v1/reports|yes|tests/api/v1/test_reviews.py:245:        report_resp = await client.post(
post /api/v1/reports/{*}/close|yes|tests/api/v1/test_coverage_boost.py:413:        close_resp = await client.post(
post /api/v1/reports/{*}/triage|yes|tests/api/v1/test_reviews.py:261:        triage_resp = await client.post(
post /api/v1/reviews/{*}/moderate|yes|tests/api/v1/test_reviews.py:198:        suppress_resp = await client.post(
post /api/v1/spus|yes|tests/api/v1/test_inventory.py:33:    spu_resp = await client.post("/api/v1/spus", headers=auth_header(admin_token), json={
post /api/v1/spus/{*}/skus|yes|tests/api/v1/test_security.py:43:    sku_resp = await client.post(f"/api/v1/spus/{spu['id']}/skus", headers=auth_header(admin_token), json={
post /api/v1/stocktakes|yes|tests/api/v1/test_inventory.py:322:        st_resp = await client.post("/api/v1/stocktakes", headers=auth_header(admin_token), json={
post /api/v1/stocktakes/{*}/lines|yes|tests/api/v1/test_inventory.py:328:        line_resp = await client.post(f"/api/v1/stocktakes/{st['id']}/lines", headers=auth_header(admin_token), json={
post /api/v1/stocktakes/{*}/post|yes|tests/api/v1/test_inventory.py:337:        post_resp = await client.post(f"/api/v1/stocktakes/{st['id']}/post", headers=auth_header(admin_token))
post /api/v1/tags|yes|tests/api/v1/test_additions.py:26:        tag_resp = await client.post("/api/v1/tags", headers=auth_header(admin_token), json={
post /api/v1/verification-cases|yes|tests/api/v1/test_verification.py:17:    resp = await client.post(
post /api/v1/verification-cases/{*}/decision|yes|tests/api/v1/test_verification.py:168:        resp = await client.post(
post /api/v1/verification-cases/{*}/renew|yes|tests/api/v1/test_coverage.py:623:        r = await client.post(
post /api/v1/verification-cases/{*}/submit|yes|tests/api/v1/test_verification.py:43:    resp2 = await client.post(
post /api/v1/verification-cases/{*}/withdraw|yes|tests/api/v1/test_verification.py:284:        resp = await client.post(
post /api/v1/warehouses|yes|tests/api/v1/test_security.py:16:    wh_resp = await client.post("/api/v1/warehouses", headers=auth_header(admin_token), json={
put /api/v1/assets/uploads/{*}/parts/{*}|yes|tests/api/v1/test_audit_fixes.py:61:        resp2 = await client.put(
```

## API Test Classification
1. True No-Mock HTTP
- Files: `tests/api/v1/test_auth.py`, `test_assets.py`, `test_catalog.py`, `test_inventory.py`, `test_reviews.py`, `test_verification.py`, `test_security.py`, `test_endpoint_coverage.py`, `test_coverage.py`, `test_coverage_boost.py`, `test_regressions.py`, `test_additions.py`, `test_audit_fixes.py`.
- Evidence of real app bootstrap + HTTP layer: `tests/conftest.py` builds app via `create_app()`, uses `AsyncClient(transport=ASGITransport(app=app))`.
- No route/service/controller mocking detected.

2. HTTP with Mocking
- **None found** (static search found no `jest.mock`, `vi.mock`, `sinon.stub`, `monkeypatch`, `unittest.mock`, dependency override usage in test paths).

3. Non-HTTP (unit/integration without HTTP)
- Present in `tests/api/v1/test_audit_fixes.py`:
  - route dependency inspection via `app.routes` in `test_binding_requires_permission_not_just_auth`
  - JSON-shape-only worker log tests in `TestStructuredWorkerLogging`.

## Mock Detection Rules Result
- `WHAT mocked`: none detected.
- `WHERE`: none detected under `tests/` and `src/trailgoods/` for mock/stub/override patterns.

## Coverage Summary
- Total endpoints: **86**
- Endpoints with HTTP tests: **86**
- Endpoints with true no-mock HTTP tests: **86**
- HTTP coverage: **100.00%**
- True API coverage: **100.00%**

## Unit Test Analysis

### Backend Unit Tests
- Backend-focused tests are present, but mostly API-level HTTP tests (not classic isolated unit tests).
- Additional non-HTTP checks exist in `tests/api/v1/test_audit_fixes.py` (route dependency and log JSON structure checks).

Modules covered via API execution paths:
- Controllers/endpoints: auth, assets, catalog, inventory, reviews, verification.
- Auth/permissions paths: role checks, reviewer/admin restrictions, session/token behavior.

Important backend modules not directly unit-tested (isolated):
- `src/trailgoods/services/auth.py`
- `src/trailgoods/services/assets.py`
- `src/trailgoods/services/catalog.py`
- `src/trailgoods/services/inventory.py`
- `src/trailgoods/services/reviews.py`
- `src/trailgoods/services/verification.py`
- `src/trailgoods/services/audit.py`
- `src/trailgoods/core/encryption.py`
- middleware units (`src/trailgoods/middleware/*.py`) as isolated unit targets

### Frontend Unit Tests (STRICT REQUIREMENT)
- Project type is `backend`, not `web`/`fullstack`.
- Frontend test files: **NONE**
- Frameworks/tools detected for frontend tests: **NONE**
- Frontend components/modules covered: **NONE**
- Important frontend components/modules not tested: **Not applicable (no frontend codebase detected)**

Mandatory verdict:
- **Frontend unit tests: MISSING**
- Critical gap trigger (`fullstack`/`web` + missing FE tests): **NOT APPLICABLE**

### Cross-Layer Observation
- No frontend layer detected; backend-only testing distribution is expected.

## API Observability Check
- Strong in most API tests: explicit endpoint, request payload/params, status assertions, and response body checks.
- Weak spots:
  - some helper/setup calls assert minimally or not at all in setup functions.
  - some regression/security tests emphasize status code over deep payload contract assertions.

## Test Quality & Sufficiency
- Success paths: strong across major domains.
- Failure/validation/authz paths: strong coverage (401/403/404/409/422 patterns frequently asserted).
- Edge cases: present (duplicate operations, invalid UUIDs, replay/idempotency-like checks, role boundaries).
- Integration boundaries: strong at API+DB+auth workflow level.
- Superficial/autogenerated signs: low.

`run_tests.sh` check:
- `docker compose --profile test run --rm --build test "$@"` (`run_tests.sh:6`)
- Verdict: **Docker-based (OK)**

## End-to-End Expectations
- Type is backend, so FE↔BE E2E is not required.

## Tests Check
- Static inspection only performed.
- No runtime execution performed.

## Test Coverage Score (0–100)
- **93/100**

## Score Rationale
- + Full endpoint HTTP coverage (86/86).
- + No mocking/stubbing detected in API-path tests.
- + Good auth/permission/validation/regression depth.
- - Limited isolated unit tests for service/middleware internals.
- - Some assertions are status-heavy vs full contract-depth in a subset of tests.

## Key Gaps
1. Lack of isolated unit tests for core service modules and middleware.
2. Some tests rely on high-level status assertions without deep schema/content assertions.

## Confidence & Assumptions
- Confidence: **High**.
- Assumptions:
  - In-process ASGI HTTP testing is treated as HTTP-layer route execution.
  - Endpoint matching used static request-call evidence in test files.

## Test Coverage Verdict
- **PASS (with medium-priority improvement areas)**

---

# README Audit

## README Location
- Found at required path: `README.md`.

## Hard Gate Evaluation

### Formatting
- PASS: clean markdown structure with clear sections and tables.

### Startup Instructions (Backend/Fullstack requires `docker-compose up`)
- PASS: includes exact `docker-compose up` (`README.md:10-13`).

### Access Method
- PASS: explicit API URL/port provided (`http://localhost:8000`) and docs URL (`/docs`).

### Verification Method
- PASS: concrete `curl` verification flows for admin/reviewer/instructor login and public catalog check.

### Environment Rules (no runtime installs/manual DB setup)
- PASS: no `npm install`, `pip install`, `apt-get`, or manual DB setup instructions in README.
- Docker-contained startup and test instructions are provided.

### Demo Credentials (auth exists)
- PASS: username + password + roles provided for seeded accounts.
- Role coverage note includes handling of Guest as unauthenticated role.

## Engineering Quality
- Tech stack clarity: good (FastAPI, PostgreSQL, worker, docker compose).
- Architecture/service clarity: good (service layout table, recurring jobs).
- Testing instructions: good (`./run_tests.sh` and scoped test-file run).
- Security/roles: good (credentials + role mapping + production override notes).
- Workflow clarity: good.
- Presentation quality: good.

## High Priority Issues
- None.

## Medium Priority Issues
1. Could add a concise endpoint capability matrix (domain -> key endpoints) to speed onboarding for API consumers.

## Low Priority Issues
1. Minor style inconsistency between `docker-compose` and `docker compose` command forms (both appear; operationally fine).

## Hard Gate Failures
- None.

## README Verdict
- **PASS**

---

## Final Combined Verdicts
1. Test Coverage Audit: **PASS (score 93/100)**
2. README Audit: **PASS**
