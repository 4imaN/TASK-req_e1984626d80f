# Delivery Acceptance Audit Recheck

## Verdict

Previously reported issues reviewed: **6**  
Resolved from static evidence: **6 / 6**

This recheck is still **static-only**. I did not run the project, Docker, or tests. "Fixed" below means the prior issue is no longer supported by the current checked-in code, tests, or documentation.

## Issue-by-Issue Recheck

### 1. Mandatory audit logging is not enforced uniformly for privileged actions
- Status: **Fixed for the previously cited gaps**
- Rationale: The previously cited endpoints now write audit entries for upload-part, asset reads, identity-binding reads, privileged identity-binding reads, and reservation listing.
- Evidence:
  - `src/trailgoods/api/v1/endpoints/assets.py:99-136`
  - `src/trailgoods/api/v1/endpoints/assets.py:209-243`
  - `src/trailgoods/api/v1/endpoints/auth.py:263-313`
  - `src/trailgoods/api/v1/endpoints/inventory.py:715-738`
  - `tests/api/v1/test_audit_fixes.py:36-137`
- Boundary: This resolves the specific audit gaps previously reported. It does **not** prove every privileged action across the entire repository is audited.

### 2. Identity-binding creation bypasses the fine-grained permission model
- Status: **Fixed**
- Rationale: The create route now requires `identity_binding.create` instead of generic authenticated access.
- Evidence:
  - `src/trailgoods/api/v1/endpoints/auth.py:210-218`
  - `tests/api/v1/test_audit_fixes.py:145-231`
- Note: The route-level permission fix is clear in code. The added negative test coverage is weaker than ideal, but the original defect itself is no longer present.

### 3. Share-link passwords are accepted in query parameters
- Status: **Fixed**
- Rationale: Share-link inspection and download now read the password from `X-Share-Password` request headers rather than query parameters, and tests assert query-param usage is rejected.
- Evidence:
  - `src/trailgoods/api/v1/endpoints/assets.py:379-425`
  - `tests/api/v1/test_audit_fixes.py:239-316`
  - `tests/api/v1/test_assets.py:256-281`

### 4. Sensitive identity-binding values are always masked; there is no explicit privileged read path
- Status: **Fixed**
- Rationale: Binding formatting now supports masked and unmasked output, and there is an explicit admin/reviewer endpoint guarded by `identity_binding.read_sensitive`. Privileged reads are also audited.
- Evidence:
  - `src/trailgoods/api/v1/endpoints/auth.py:238-260`
  - `src/trailgoods/api/v1/endpoints/auth.py:287-313`
  - `tests/api/v1/test_audit_fixes.py:324-437`

### 5. Performance target has no static evidence
- Status: **Fixed**
- Rationale: The repository now includes a checked-in benchmarking guide with methodology, example load scripts, result interpretation guidance, and regression-detection guidance. That satisfies the prior complaint that there was no static evidence artifact at all.
- Evidence:
  - `BENCHMARKING.md:1-144`
- Boundary: This is documentation/methodology evidence only. It still does **not** prove the prompt's p95 target is actually met at runtime.

### 6. Worker/job logging is not consistently structured
- Status: **Fixed**
- Rationale: Worker success/failure and bootstrap completion now emit JSON-structured logs instead of plain text.
- Evidence:
  - `src/trailgoods/worker.py:63-83`
  - `scripts/bootstrap_jobs.py:53-54`
  - `tests/api/v1/test_audit_fixes.py:445-499`
- Note: The current tests validate JSON shape more than end-to-end logger behavior, but the implementation change is present.

## Summary

All six previously reported issues appear resolved in the current repository state from static evidence.

The main remaining boundary is runtime proof:
- I cannot confirm statistically that the documented benchmarking process has been executed successfully.
- I cannot confirm statistically that audit coverage is exhaustive beyond the previously cited endpoints.
