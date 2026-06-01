# Restore DB API

Async **FastAPI** service with three responsibilities:

1. **Take a full backup** of the main PostgreSQL database on demand (via API call)
2. **Restore deleted records** from a backup database back into main — in FK-dependency order
3. **Delete a backup** — drops the backup database and removes the dump file from disk

---

## Project structure

```
db-restore-api/
├── .venv/                               virtual environment (not committed)
├── src/
│   ├── commen/
│   │   ├── backup/
│   │   │   └── schema/                  Pydantic schemas for backup requests/responses
│   │   ├── restore/
│   │   │   └── schema/                  Pydantic schemas for restore requests/responses
│   │   └── utils/                       shared utilities
│   ├── models/                          SQLAlchemy ORM models (BackupLog, RevertLog)
│   └── module/
│       ├── backup/                      backup business logic service
│       ├── restore/                     restore business logic service
│       └── gateway/
│           ├── backup/                  POST /backup/create  POST /backup/delete/{id}
│           ├── restore/                 POST /restore/ordered  POST /restore/detect-missing
│           └── health/                  GET /health
├── .env                                 environment variables (not committed)
├── .env.example                         environment variable template
├── .gitignore
├── requirements.txt
├── run.py                               uvicorn entrypoint
└── README.md
```

---

## Requirements

### Python

Python **3.11** or **3.12**

### System packages

`pg_dump` and `pg_restore` must be installed on the machine running this app:

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y postgresql-client

# verify
pg_dump --version
pg_restore --version
```

### PostgreSQL databases

Three PostgreSQL databases are needed:

| Database | Purpose |
|----------|---------|
| **Main DB** | Live LMS production database (read + write) |
| **Backup DB host** | PostgreSQL server where backup DBs are created — one new DB per backup named `backup_db_YYYYMMDD_HHMMSS` |
| **Meta DB** | Stores `BackupLog` and `RevertLog` audit records — can share the same server as Main |

---

## Installation

```bash
# 1. create virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate         # Windows

# 2. install dependencies
pip install -r requirements.txt

# 3. copy and fill in env file
cp .env.example .env
```

---

## Database setup

### 1. Create the Meta database

```sql
CREATE DATABASE restore_meta;
GRANT ALL PRIVILEGES ON DATABASE restore_meta TO meta_user;
```

Tables are created automatically on first startup — no migration needed.

### 2. Allow the backup user to create databases

```sql
-- run on the backup PostgreSQL server
ALTER USER meta_user CREATEDB;
```

### 3. Create the dump directory

```bash
sudo mkdir -p /backups
sudo chown $USER:$USER /backups
```

---


## 🗄️ Database Migrations (Alembic)

Database migrations are managed by Alembic. Always run these commands from the `src` directory.

```bash
cd src
```
- **Run all pending migrations:**
  ```bash
  alembic upgrade head
  ```
- **Create a new baseline revision:**
  ```bash
  alembic revision -m "baseline_revision"
  ```
- **Revert the last migration:**
  ```bash
  alembic downgrade -1
  ```
- **Auto-generate a new migration (after modifying models):**
  ```bash
  alembic revision --autogenerate -m "Added account table"
  ```
  *⚠️ **Note:** Remember to import your new entities/models into `database/run_migrations.py` and `database/migrations/env.py` before auto-generating migrations.*

---
### Production

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### As a systemd service (recommended)

Create `/etc/systemd/system/db-restore.service`:

```ini
[Unit]
Description=Restore DB API
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/db-restore-api
EnvironmentFile=/opt/db-restore-api/.env
ExecStart=/opt/db-restore-api/.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable db-restore
sudo systemctl start db-restore
sudo systemctl status db-restore
```

---

## Nightly scheduled backup

### Option A — Crontab

```bash
crontab -e
```

Add this line:

```cron
0 0 * * * curl -s -X POST http://localhost:8000/backup/create \
  -H "Content-Type: application/json" \
  -d '{"notes": "nightly auto backup", "created_by": "cron"}' \
  >> /var/log/db_backup.log 2>&1
```

### Option B — Systemd Timer (recommended for production)

Create `/etc/systemd/system/db-backup.service`:

```ini
[Unit]
Description=Nightly Backup
After=network.target

[Service]
Type=oneshot
User=ubuntu
ExecStart=curl -s -X POST http://localhost:8000/backup/create \
  -H "Content-Type: application/json" \
  -d "{\"notes\": \"nightly auto backup\", \"created_by\": \"systemd\"}"
StandardOutput=append:/var/log/lms_backup.log
StandardError=append:/var/log/lms_backup.log
```

Create `/etc/systemd/system/db-backup.timer`:

```ini
[Unit]
Description=Run LMS backup every night at 00:00
Requires=lms-backup.service

[Timer]
OnCalendar=*-*-* 00:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable lms-backup.timer
sudo systemctl start lms-backup.timer
sudo systemctl list-timers --all | grep lms
```

> `Persistent=true` means if the server was off at midnight, the backup runs immediately on next boot.

---

## API reference

Interactive docs at `http://localhost:8000/docs` after starting.

---

### `GET /health`

Check that all DB connections are alive.

**Response**
```json
{
  "status": "healthy",
  "databases": {
    "main_db": "ok",
    "meta_db": "ok"
  }
}
```

---

### `POST /backup/create`

Take a full backup of the main database.

**Steps performed internally:**

| Step | Action |
|------|--------|
| 1 | Generate name: `backup_db_YYYYMMDD_HHMMSS` |
| 2 | `CREATE DATABASE backup_db_...` on backup host |
| 3 | `pg_dump` main DB → saves to `BACKUP_DUMP_DIR` |
| 4 | `pg_restore` dump → loads into new backup DB |
| 5 | Save `BackupLog` to meta DB |

**Request body** (all fields optional)
```json
{
  "notes": "before deploy v2.4",
  "created_by": "admin"
}
```

**Response**
```json
{
  "id": 1,
  "db_name": "backup_db_20260528_000000",
  "dump_file": "/backups/backup_db_20260528_000000.dump",
  "size_mb": 142.5,
  "status": "completed",
  "error_message": null,
  "notes": "before deploy v2.4",
  "created_by": "admin",
  "created_at": "2026-05-28T00:00:00Z",
  "completed_at": "2026-05-28T00:01:05Z"
}
```

---

### `POST /backup/delete/dump/file//{id}`

Full delete of a backup in three steps:

| Step | Action | Controlled by |
|------|--------|---------------|
| 1 | `DROP DATABASE backup_db_...` on backup host | `drop_db`     |
| 2 | Delete `.dump` file from disk | `delete_dump` |


**Response**
```json
{
  "backup_id": 1,
  "db_name": "backup_db_20260528_000000",
  "dump_file": "/backups/backup_db_20260528_000000.dump",
  "db_dropped": true,
  "log_deleted": true,
  "errors": [],
  "success": true
}
```

HTTP **200** = all steps succeeded
HTTP **207** = partial success — check `errors` list

---

### `GET /backups/`

List all `BackupLog` entries, newest first.

**Response**
```json
[
  {
    "id": 1,
    "filename": "backup_db_20260528_000000.dump",
    "local_path": "/backups/backup_db_20260528_000000.dump",
    "size_mb": 142.5,
    "storage": "local",
    "status": "completed",
    "error_message": null,
    "notes": "nightly auto backup",
    "backup_db_name": "backup_db_20260528_000000",
    "created_by": "cron",
    "created_at": "2026-05-28T00:00:00Z",
    "completed_at": "2026-05-28T00:01:05Z"
  }
]
```

---

### `GET /backups/{id}`

Get a single `BackupLog` entry by ID.

**Response**
```json
{
  "id": 1,
  "filename": "backup_db_20260528_000000.dump",
  "local_path": "/backups/backup_db_20260528_000000.dump",
  "size_mb": 142.5,
  "storage": "local",
  "status": "completed",
  "error_message": null,
  "notes": "nightly auto backup",
  "backup_db_name": "backup_db_20260528_000000",
  "created_by": "cron",
  "created_at": "2026-05-28T00:00:00Z",
  "completed_at": "2026-05-28T00:01:05Z"
}
```

---

### `GET /backups/{id}/download`

Download the `.dump` file for a backup directly from the server disk.

The file is served with its original filename (e.g. `backup_db_20260528_000000.dump`)
and `Content-Type: application/octet-stream`.

**Response** — binary file stream

Returns **404** if:
- `BackupLog` not found
- `local_path` not recorded
- File missing from disk

---

### `DELETE /backups/{id}`

Soft delete — removes only the `BackupLog` and its `RevertLog` records from the meta DB. Does **not** drop the backup database or delete the dump file.

Use `POST /backup/delete/{id}` for a full delete.

**Response**
```json
{
  "detail": "BackupLog #1 deleted."
}
```

---

### `GET /backups/{id}/revert-logs`

List all restore audit entries for a specific backup.

**Response**
```json
[
  {
    "id": 1,
    "backup_log_id": 1,
    "table_name": "account_user",
    "object_id": 10,
    "reverted_by": "admin",
    "reverted_at": "2026-05-28T10:30:00Z",
    "success": true,
    "error_message": null,
    "notes": "restoring deleted user"
  }
]
```

---

### `GET /backups/revert-logs/all`

List every restore audit entry across all backups.

**Response** — same structure as above, all entries combined.

---

### `POST /restore/detect-missing`

**Read-only.** Scans the backup DB and returns all records missing from the main DB
including full row data for preview. Safe to call at any time.

**Request body**
```json
{
  "tables": [
    "vouchers_voucher",
    "account_user",
    "vouchers_studentvoucher"
  ],
  "backup_db_name": "backup_db_20260528_000000"
}
```

`backup_db_name` is optional — omit to use the default backup DB from `.env`.

**Response**
```json
{
  "backup_db_used": "backup_db_20260528_000000",
  "backup_log_id": null,
  "total_missing": 2,
  "missing": [
    {
      "table": "account_user",
      "object_id": 10,
      "data": {
        "id": 10,
        "username": "john",
        "email": "john@example.com",
        "is_active": true
      }
    },
    {
      "table": "vouchers_studentvoucher",
      "object_id": 201,
      "data": {
        "id": 201,
        "voucher_id": 55,
        "student_id": 10,
        "owner_id": 3
      }
    }
  ]
}
```

---

### `POST /restore/ordered`

Restores missing records into the main DB in the order you specify.

**Request body**
```json
{
  "tables": [
    "courseSalePackage_voucher",
    "account_user",
    "account_student",
    "courseSalePackage_studentvoucher"
  ],
  "backup_db_name": "backup_db_20260528_000000",
  "backup_log_id": null,
  "notes": "restoring accidentally deleted user #10",
  "dry_run": false
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `tables` | yes | Ordered table names — FK parents before children |
| `backup_db_name` | no | Backup DB to restore from. Omit = default from `.env` |
| `backup_log_id` | no | Use a specific BackupLog's snapshots if available |
| `notes` | no | Saved to every `RevertLog` audit entry |
| `dry_run` | no | `true` = detect only, write nothing |

**Response**
```json
{
  "backup_db_used": "backup_db_20260528_000000",
  "backup_log_id": null,
  "dry_run": false,
  "total_missing": 3,
  "total_restored": 3,
  "total_failed": 0,
  "tables_processed": [
    {
      "table": "vouchers_voucher",
      "missing_ids": [55],
      "restored_ids": [55],
      "failed_ids": [],
      "errors": {}
    },
    {
      "table": "account_user",
      "missing_ids": [10],
      "restored_ids": [10],
      "failed_ids": [],
      "errors": {}
    },
    {
      "table": "vouchers_studentvoucher",
      "missing_ids": [201],
      "restored_ids": [201],
      "failed_ids": [],
      "errors": {}
    }
  ]
}
```

HTTP **200** = all restored successfully
HTTP **207** = partial success — check `failed_ids` and `errors` per table

---

## FK ordering rule

Always list FK **parent tables before child tables**.

```
WRONG:  ["vouchers_studentvoucher", "vouchers_voucher"]
                   ↑ child before parent → FK constraint error

CORRECT: ["vouchers_voucher", "account_user", "vouchers_studentvoucher"]
                 ↑ parents first              ↑ child last
```

Example with the full `StudentVoucher` dependency chain:

```json
"tables": [
  "vouchers_voucher",                  ← FK parent 1
  "account_user",                      ← FK parent 2
  "account_student",                   ← FK parent 3
  "management_schoolbookstudent",      ← FK parent 4
  "vouchers_studentvoucher"            ← child (has all 4 FKs above)
]
```

---

## Typical workflows

### Nightly backup (manual trigger)

```bash
curl -X POST http://localhost:8000/backup/create \
  -H "Content-Type: application/json" \
  -d '{"notes": "nightly backup", "created_by": "cron"}'
```

### Restore a deleted user and related records

```bash
# Step 1 — preview (safe, read-only)
curl -X POST http://localhost:8000/restore/detect-missing \
  -H "Content-Type: application/json" \
  -d '{
    "tables": ["account_user", "account_student", "vouchers_studentvoucher"],
    "backup_db_name": "backup_db_20260528_000000"
  }'

# Step 2 — restore
curl -X POST http://localhost:8000/restore/ordered \
  -H "Content-Type: application/json" \
  -d '{
    "tables": [
      "vouchers_voucher",
      "account_user",
      "account_student",
      "management_schoolbookstudent",
      "vouchers_studentvoucher"
    ],
    "backup_db_name": "backup_db_20260528_000000",
    "notes": "restoring deleted user #10"
  }'

# Step 3 — check audit trail
curl http://localhost:8000/backups/revert-logs/all
```

### Download a backup dump file

```bash
curl -OJ http://localhost:8000/backups/1/download
```

### Full delete of a backup

```bash
curl -X POST http://localhost:8000/backup/delete/1 \
  -H "Content-Type: application/json" 
```

### Find the right backup DB name

```bash
# list all backups, newest first — use db_name in restore requests
curl http://localhost:8000/backups/
```