# TrailGoods Commerce & Logistics API - Clarification Questions and Safe Defaults


## 1. What does "offline-first" mean for TrailGoods?
**Problem:** The prompt says the system must be offline-first and run on a single machine, but it does not explicitly list which external dependencies are forbidden.
**My Understanding:** The product must run entirely from the repository using only local services and local network access.
**Solution:** Keep authentication, queueing, file storage, search/filtering, moderation dictionaries, backups, integrity checks, and analytics fully local. Do not depend on cloud storage, hosted search, remote queues, SaaS auth, or third-party scanning services.

## 2. What login identifiers are accepted?
**Problem:** The prompt requires register and login, but it does not define whether users log in with username, email, or both.
**My Understanding:** Username is the authoritative login identifier in v1, while email can exist as optional profile data.
**Solution:** Require unique usernames and authenticate by username only in v1. Permit optional unique email for future recovery or notifications, but do not make it part of the login contract yet.

## 3. Are usernames case-sensitive?
**Problem:** The prompt says usernames must be unique, but it does not define case behavior.
**My Understanding:** Usernames should be case-insensitive for uniqueness and lookup.
**Solution:** Normalize usernames to lowercase for uniqueness and authentication while optionally preserving a display casing field if needed later.

## 4. What exactly happens after 5 failed logins in 15 minutes?
**Problem:** The prompt requires forced logout across all sessions after repeated failed logins, but it does not define whether the account is locked, challenged, or only logged out.
**My Understanding:** Active sessions must be revoked immediately and the account should be temporarily challenged rather than permanently locked.
**Solution:** After the 5th failed login inside a rolling 15-minute window, revoke all active sessions, set account status to `CHALLENGE_REQUIRED`, and reject fresh session issuance for 15 minutes unless a privileged override occurs.

## 5. What does password rotation do to existing sessions and password history?
**Problem:** The prompt requires password rotation but does not define session invalidation or password reuse policy.
**My Understanding:** Rotation should be security-hardening, not cosmetic.
**Solution:** Revoke all sessions after password change and reject reuse of the last 5 password hashes.

## 6. Is self-service password reset in scope?
**Problem:** The prompt requires authentication APIs but does not mention email, OTP, or recovery flows.
**My Understanding:** Self-service reset is outside v1 because the system is offline and local-only.
**Solution:** Support authenticated password rotation and Admin-forced password reset only. Do not add email reset links or OTP flows.

## 7. How are staff and student IDs modeled per institution?
**Problem:** The prompt requires binding staff and student IDs with uniqueness per institution, but it does not define whether institutions are a registry or free-form codes.
**My Understanding:** Institution identity can start as a normalized code rather than a full managed institution directory.
**Solution:** Store `institution_code` as a normalized string and enforce uniqueness on `(institution_code, binding_type, external_id)`.

## 8. Can one user hold multiple bindings?
**Problem:** The prompt allows staff and student ID binding but does not define whether a user may bind both types, multiple institutions, or replacement records.
**My Understanding:** A user may have multiple bindings over time, but only one active binding per institution and binding type.
**Solution:** Make bindings append-only historical records. Allow multiple institutions and both binding types, but enforce one active binding per `(user_id, institution_code, binding_type)` and revoke old bindings on replacement.

## 9. What exactly is required for enterprise verification?
**Problem:** The prompt says enterprise verification must include legal name, DOB, and government ID image, which sounds like a natural-person requirement even though the profile type is enterprise.
**My Understanding:** Enterprise verification still needs an accountable human identity in addition to enterprise data.
**Solution:** Require both enterprise legal-name fields and a `responsible_person` block containing legal name, DOB, government ID number, and government ID image.

## 10. Is government ID number required in addition to the image upload?
**Problem:** The prompt explicitly requires encryption at rest for ID numbers and DOB, but only lists the ID image as a required upload field.
**My Understanding:** The system should capture the ID number as structured sensitive data, not image-only evidence.
**Solution:** Require encrypted `government_id_number` for personal verification and for the enterprise responsible person.

## 11. How many active verification cases can exist at once?
**Problem:** The prompt requires immutable case IDs and resubmission-like behavior, but it does not define concurrency of open cases.
**My Understanding:** Multiple simultaneous active cases for the same user and profile type create approval ambiguity.
**Solution:** Allow only one active case per `(user_id, profile_type)` across `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, and `NEEDS_INFO`.

## 12. What happens when a verification case is rejected or needs more information?
**Problem:** The prompt requires manual decisioning but does not define whether rejected users resubmit through the same case, create a new case, or appeal.
**My Understanding:** The system should preserve traceability without mutating immutable case identity.
**Solution:** Keep the same immutable `case_id` for `NEEDS_INFO` revisions, allow one rejection appeal within 14 days, and require a brand-new case only after a final rejection is closed or the appeal is denied.

## 13. What happens at the 12-month verification expiry point?
**Problem:** The prompt says verification expires after 12 months but does not define grace periods or behavior during renewal.
**My Understanding:** Expiry should be deterministic with no silent grace period.
**Solution:** On the exact 12-month anniversary of approval, set status to `EXPIRED`. Access that depended on active verification remains blocked until renewal is approved.

## 14. Who can create which item types?
**Problem:** The prompt defines roles but does not say whether non-Admin actors can create `PRODUCT` or `LIVE_PET` items.
**My Understanding:** Instructor should author service content, while Admin retains full control across all item types.
**Solution:** Allow `Instructor` to create and manage only owned `SERVICE` items. Restrict `PRODUCT` and `LIVE_PET` creation to `Admin` in v1.

## 15. Are categories single-select or multi-select?
**Problem:** The prompt mentions categories and tags, but does not define category cardinality.
**My Understanding:** A single primary category plus tags is the safest v1 shape.
**Solution:** Give each item one primary category and many tags.

## 16. How should live-pet items map to SKU and stock?
**Problem:** The prompt requires the same item model to support live pets, but it does not define whether pets are one-off records or normal replenishable inventory.
**My Understanding:** Live pets are individually tracked sellable units.
**Solution:** Require exactly one SKU per live-pet item, cap total sellable quantity at 1, disallow replenishment after sale, and preserve full traceability for that unit.

## 17. What are the minimum publish prerequisites?
**Problem:** The prompt requires publish/unpublish but does not define what makes an item publishable.
**My Understanding:** Publishing should be blocked until the listing is actually sellable and reviewable.
**Solution:** Require at least one active USD price, at least one active media image for public display, valid item-type structure, and no unresolved validation errors before allowing publish.

## 18. How do price scopes and overlap rules work?
**Problem:** The prompt says pricing in USD is supported, but it does not define whether prices are item-level, SKU-level, or both, nor whether overlapping prices are allowed.
**My Understanding:** Products need SKU-level pricing; services and live pets can use item-level pricing.
**Solution:** Price `PRODUCT` at the SKU level, price `SERVICE` and `LIVE_PET` at the item level, and reject overlapping active price windows for the same priced target.

## 19. Is full trip or rental scheduling in scope for v1?
**Problem:** Service items include guided trips and rentals, but the prompt does not explicitly require a booking calendar or recurrence engine.
**My Understanding:** v1 needs service catalog modeling, not a complete scheduling subsystem.
**Solution:** Support service metadata, optional capacity, instructor ownership, and pricing. Defer recurring schedules, booking calendars, and availability search.

## 20. How do rentals interact with inventory?
**Problem:** The prompt includes rentals and inventory, but it does not say whether rental services must reserve stock.
**My Understanding:** Some rental offerings should optionally consume physical stock, while pure guided services should not.
**Solution:** Let a service item optionally reference one or more backing SKUs. When linked, reservation and deduction rules follow the standard inventory model.

## 21. Are reservations warehouse-specific, or can the system auto-pick stock?
**Problem:** The prompt requires multi-warehouse inventory but does not define allocation strategy.
**My Understanding:** Automatic warehouse selection adds hidden business logic that is not specified.
**Solution:** Make reservations warehouse-specific in v1. Warehouse selection must be explicit in the API request or resolved by a privileged internal service with a clear audit trail.

## 22. Do we need internal order records even though Orders were not named in the source model list?
**Problem:** The prompt requires order-linked reservation, deduction, idempotency, and cancellation rollback, but it does not explicitly include `Orders` and `OrderLines` in the mandatory model list.
**My Understanding:** Safe rollback and deduplication are not credible without an internal order anchor.
**Solution:** Add minimal internal `orders` and `order_lines` tables strictly to support stock reservation, deduction, status changes, and 30-minute rollback. Do not expand them into full payment or shipping domains.

## 23. What happens when an order is canceled after 30 minutes?
**Problem:** The prompt only says rollback must occur automatically when an order is canceled within 30 minutes.
**My Understanding:** Automatic reversal after 30 minutes is too risky without an explicit business rule.
**Solution:** Permit automatic rollback only inside the 30-minute window. After that, require a privileged manual inventory adjustment with audit logging.

## 24. How are inter-warehouse transfers handled?
**Problem:** The prompt requires multi-warehouse stock and outbound/inbound documents, but it does not explicitly mention transfer mechanics.
**My Understanding:** Transfers are a paired stock movement rather than a special third document family.
**Solution:** Model transfers as a linked outbound posting from the source warehouse and inbound posting into the destination warehouse, tied together with a shared transfer reference.

## 25. How do reorder thresholds work?
**Problem:** The prompt gives a default reorder threshold of 10 but does not define whether it is global or warehouse-specific.
**My Understanding:** Reorder risk is warehouse-local.
**Solution:** Store thresholds per `(warehouse_id, sku_id)` with fallback to a system default of 10.

## 26. How should asset deduplication work across users?
**Problem:** The prompt requires SHA-256 deduplication but does not define whether two different users can share the same physical blob.
**My Understanding:** Blob-level dedup is acceptable if logical ownership remains separate.
**Solution:** Deduplicate at the blob layer by hash, but keep separate logical `Asset` records with ownership, attachment, and ACL metadata per uploader.

## 27. Which MIME types are allowed, and can sensitive verification files ever be shared?
**Problem:** The prompt sets size limits and says MIME types are restricted, but it does not publish a default allowlist or the boundary for sensitive documents.
**My Understanding:** Verification assets must be stricter than ordinary listing media.
**Solution:** Default allowlist to images (`image/jpeg`, `image/png`, `image/webp`), videos (`video/mp4`, `video/webm`), and attachments (`application/pdf`, `text/plain`, `text/csv`). Never expose verification assets through public share links.

## 28. Is batch upload atomic?
**Problem:** The prompt supports batch uploads but does not say whether one failed file should fail the entire batch.
**My Understanding:** Per-file outcomes are safer and easier to recover.
**Solution:** Make batch upload non-atomic with per-file success or failure reporting.

## 29. Who is allowed to post reviews, and can reviews be edited?
**Problem:** The prompt requires ratings, tags, reports, and revision history, but it does not define review eligibility or edit behavior.
**My Understanding:** Reviews should require a real purchase or completion signal and preserve full revision history.
**Solution:** Allow reviews only from users with a completed internal order line or completed service record. Permit edits, but store append-only revisions and expose only the latest approved public revision.

## 30. What exactly counts as a "real API test" for this project?
**Problem:** The prompt is implementation-heavy but does not define whether tests may bypass the app with mocked services.
**My Understanding:** A real API test must exercise the actual FastAPI routes, auth, validation, persistence, and local filesystem behavior.
**Solution:** Require HTTP-level tests against the real app, a migrated PostgreSQL test database, and temporary local disk storage. Do not broadly mock repositories or business services on critical flows.

## 31. What test coverage target is required?
**Problem:** The prompt requires a serious backend, but it does not define a concrete minimum coverage bar.
**My Understanding:** The build should not be considered complete without a strong automated test floor.
**Solution:** Enforce backend line coverage of at least 90%, excluding migrations, generated files, and one-off scripts, with special emphasis on auth, verification, masking, inventory, and moderation paths.

## 32. What documentation is still required if design docs and api-spec output are out of scope?
**Problem:** The latest instruction removes doc-heavy deliverables, but the repository still needs enough static evidence for human review.
**My Understanding:** Only minimal operational docs are necessary.
**Solution:** Require a short `README.md` with setup, migrate, run, worker, backup, and test commands, plus `.env.example`. Do not require `api-spec.md`, design docs, architecture docs, or separate OpenAPI export bundles.
