# TrailGoods Commerce & Logistics API

**Project type: backend**

Offline-first, single-host FastAPI backend for identity, catalog, digital assets, content governance, and multi-warehouse inventory.

## Start

```bash
docker-compose up
```

That command:
1. Builds the API, worker, and PostgreSQL images
2. Auto-generates the encryption master key on first run
3. Waits for PostgreSQL, runs Alembic migrations, seeds roles/permissions
4. Bootstraps recurring background jobs
5. Starts the API at **http://localhost:8000**
6. Starts the background worker

## Demo Credentials

These accounts are auto-seeded on first startup and ready to use immediately:

| Username | Password | Roles |
|---|---|---|
| `admin` | `AdminP@ssw0rd1!` | Admin, RegisteredUser |
| `reviewer` | `ReviewP@ssw0rd1!` | Reviewer, RegisteredUser |
| `instructor` | `InstructorP@ss1!` | Instructor, RegisteredUser |

You can also register new users via `POST /api/v1/auth/register`.

## Verify It Works

After `docker-compose up`, run these commands to confirm the API is working:

**Login as admin:**
```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"AdminP@ssw0rd1!"}' | python3 -m json.tool
```

**Login as reviewer:**
```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"reviewer","password":"ReviewP@ssw0rd1!"}' | python3 -m json.tool
```

**Login as instructor:**
```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"instructor","password":"InstructorP@ss1!"}' | python3 -m json.tool
```

**Browse the public catalog:**
```bash
curl -s http://localhost:8000/api/v1/catalog/items | python3 -m json.tool
```

**Open Swagger UI in a browser:**
```
http://localhost:8000/docs
```

## Run Tests

```bash
./run_tests.sh
```

This runs `docker compose --profile test run --rm --build test`, which starts an ephemeral test PostgreSQL (tmpfs-backed), runs the full pytest suite with coverage, and exits.

To run a specific test file:

```bash
./run_tests.sh tests/api/v1/test_auth.py -v
```

## Stop

```bash
docker-compose down              # stop
docker-compose down -v           # stop and wipe all data
```

## Service Layout

| Service | Purpose |
|---|---|
| `postgres` | Primary PostgreSQL 16 |
| `api` | FastAPI application (auto-migrates, auto-seeds, auto-bootstraps jobs) |
| `worker` | Durable background job runner |
| `postgres-test` | Ephemeral PG for tests (profile: `test`) |
| `test` | pytest runner (profile: `test`) |

## Configuration

Defaults in `docker-compose.yml` are for **local development only**. Before production, override:
- `SECRET_KEY` — cryptographically random 64+ char hex string
- `POSTGRES_PASSWORD` — change from default `trailgoods`
- `DATABASE_URL` / `DATABASE_URL_SYNC` — match production credentials
- `ENCRYPTION_MASTER_KEY_FILE` — replace auto-generated key with a managed secret

See `.env.example` for all variables.

## Recurring Jobs

On startup the bootstrap script seeds recurring jobs. The worker self-reschedules them.

| Job | Interval |
|---|---|
| `verification_expiry_scan` | 1h |
| `share_link_expiry_scan` | 10m |
| `reorder_alert_scan` | 30m |
| `report_triage_sla_scan` | 30m |
| `appeal_due_scan` | 30m |
| `share_link_access_log_retention` | 24h |
| `asset_integrity_check` | 24h |
| `critical_table_manifest_checksum` | 24h |
| `nightly_backup` | 24h |
| `asset_preview_generation` | 5m |
