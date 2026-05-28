# LMS Backup Restore API

Async **FastAPI** service with two responsibilities:

1. **Take a full backup** of the main PostgreSQL database on demand (via API call)
2. **Restore deleted records** from a backup database back into main — in FK-dependency order

---

## Table of contents

- [Project structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Environment variables](#environment-variables)
- [Database setup](#database-setup)
- [Running the server](#running-the-server)
- [API reference](#api-reference)
- [FK ordering guide](#fk-ordering-guide)
- [Typical workflows](#typical-workflows)

---

## Project structure

```
lms_restore_api/
├── app/
│   ├── main.py                      # FastAPI app factory + lifespan
│   ├── core/
│   │   ├── config.py                # Settings loaded from .env
│   │   └── database.py              # Async engine factory (main / backup / meta)
│   ├── models/
│   │   ├── meta_models.py           # SQLAlchemy ORM: BackupLog, RevertLog
│   │   └── schemas.py               # Pydantic v2 request / response schemas
│   ├── services/
│   │   ├── backup_service.py        # pg_dump + pg_restore logic
│   │   └── restore_service.py       # Ordered restore logic (raw async SQL)
│   └── api/
│       ├── backup_create.py         # POST /backup/create
│       ├── backups.py               # GET/DELETE /backups/  audit trail
│       ├── restore.py               # POST /restore/ordered  /restore/detect-missing
│       └── health.py                # GET /health
├── run.py                           # uvicorn entrypoint
├── requirements.txt
└── .env.example
```

---

## Requirements

### Python

- Python **3.11** or **3.12**

### System packages

`pg_dump` and `pg_restore` must be available on the machine running this app:

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y postgresql-client

# Verify
pg_dump --version
pg_restore --version
```

### PostgreSQL databases

You need **three** PostgreSQL databases:

| Database | Purpose |
|----------|---------|
| **Main DB** | Your live LMS production database (read + write) |
| **Backup DB host** | PostgreSQL server where backup DBs are created (one per backup) |
| **Meta DB** | Stores `BackupLog` and `RevertLog` audit records for this app |

The Meta DB can be the same server as Main — just a different database name.

---

## Installation

```bash
# 1. Clone / copy the project
cd lms_restore_api

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and fill in the env file
cp .env.example .env
nano .env                          # or your preferred editor
```

---

## Environment variables

Copy `.env.example` to `.env` and fill in every value.

```env
# ─────────────────────────────────────────────────────────────────────────────
# MAIN DATABASE  (your live LMS production database)
# ─────────────────────────────────────────────────────────────────────────────
MAIN_DB_HOST=localhost
MAIN_DB_PORT=5432
MAIN_DB_NAME=lms_main
MAIN_DB_USER=lms_user
MAIN_DB_PASSWORD=your_main_password

# ─────────────────────────────────────────────────────────────────────────────
# BACKUP DATABASE HOST
# The host / credentials used when creating new backup databases.
# Each backup creates a new DB named  backup_db_YYYYMMDD_HHMMSS  on this host.
# DEFAULT_BACKUP_DB_NAME is only used as fallback when no backup_db_name
# is passed to the restore API.
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_BACKUP_DB_HOST=localhost
DEFAULT_BACKUP_DB_PORT=5432
DEFAULT_BACKUP_DB_NAME=lms_backup
DEFAULT_BACKUP_DB_USER=lms_user
DEFAULT_BACKUP_DB_PASSWORD=your_backup_password

# ─────────────────────────────────────────────────────────────────────────────
# META DATABASE  (stores BackupLog + RevertLog audit trail)
# Can be the same server as Main — just use a different DB name.
# ─────────────────────────────────────────────────────────────────────────────
META_DB_HOST=localhost
META_DB_PORT=5432
META_DB_NAME=lms_restore_meta
META_DB_USER=lms_user
META_DB_PASSWORD=your_meta_password

# ─────────────────────────────────────────────────────────────────────────────
# BACKUP DUMP DIRECTORY
# Absolute path where .dump files are saved during backup.
# Must be writable by the user running this app.
# ─────────────────────────────────────────────────────────────────────────────
BACKUP_DUMP_DIR=/backups

# ─────────────────────────────────────────────────────────────────────────────
# APP SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
APP_ENV=production          # development | production
LOG_LEVEL=INFO              # DEBUG | INFO | WARNING | ERROR
SECRET_KEY=change-me-in-production

# ─────────────────────────────────────────────────────────────────────────────
# AWS S3  (optional — only needed if you plan to upload dumps to S3)
# ─────────────────────────────────────────────────────────────────────────────
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_BACKUP_BUCKET_NAME=
AWS_S3_REGION_NAME=eu-west-1
```

---

## Database setup

### 1. Create the Meta database

```sql
-- Connect to PostgreSQL as a superuser and run:
CREATE DATABASE lms_restore_meta;
GRANT ALL PRIVILEGES ON DATABASE lms_restore_meta TO lms_user;
```

The app creates all required tables automatically on first startup — no migration needed.

### 2. Create the Backup database host / user

The backup user needs permission to **create databases** on the backup host:

```sql
-- On the backup PostgreSQL server:
ALTER USER lms_user CREATEDB;
```

### 3. Dump directory

```bash
sudo mkdir -p /backups
sudo chown $USER:$USER /backups
```

---

## Running the server

### Development (with auto-reload)

```bash
source .venv/bin/activate
APP_ENV=development python run.py
```

### Production

```bash
source .venv/bin/activate
python run.py
```

Or directly with uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### As a systemd service (recommended for production)

Create `/etc/systemd/system/lms-restore.service`:

```ini
[Unit]
Description=LMS Backup Restore API
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/lms_restore_api
EnvironmentFile=/opt/lms_restore_api/.env
ExecStart=/opt/lms_restore_api/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable lms-restore
sudo systemctl start lms-restore
sudo systemctl status lms-restore
```

---

## API reference

Interactive docs available at `http://localhost:8000/docs` after starting.

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

**What happens internally:**
1. Generates a name: `backup_db_20240526_143022`
2. Creates that database on the backup host
3. Runs `pg_dump` on main DB → saves `/backups/backup_db_20240526_143022.dump`
4. Runs `pg_restore` → loads the dump into the new backup DB
5. Saves a `BackupLog` record to the meta DB

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
  "db_name": "backup_db_20240526_143022",
  "dump_file": "/backups/backup_db_20240526_143022.dump",
  "size_mb": 142.5,
  "status": "completed",
  "error_message": null,
  "notes": "before deploy v2.4",
  "created_by": "admin",
  "created_at": "2024-05-26T14:30:22Z",
  "completed_at": "2024-05-26T14:31:05Z"
}
```

---

### `POST /restore/detect-missing`

**Read-only.** Scans the backup DB and returns all records that are missing from the main DB — including full row data for preview.

Safe to call in production at any time.

**Request body**
```json
{
  "tables": ["vouchers_voucher", "account_user", "vouchers_studentvoucher"],
  "backup_db_name": "backup_db_20240526_143022"
}
```

If `backup_db_name` is omitted, the default backup DB from `.env` is used.

**Response**
```json
{
  "backup_db_used": "backup_db_20240526_143022",
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

Restores missing records into the main DB **in the order you specify**.

**Request body**
```json
{
  "tables": [
    "vouchers_voucher",
    "account_user",
    "account_student",
    "management_schoolbookstudent",
    "vouchers_studentvoucher"
  ],
  "backup_db_name": "backup_db_20240526_143022",
  "notes": "restoring accidentally deleted user #10",
  "dry_run": false
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `tables` | yes | Ordered table names — FK parents before children |
| `backup_db_name` | no | Which backup DB to restore from. Omit = use default from `.env` |
| `backup_log_id` | no | Use a specific BackupLog's snapshots if available |
| `notes` | no | Saved to every RevertLog entry |
| `dry_run` | no | `true` = detect only, do not write anything |

**Response**
```json
{
  "backup_db_used": "backup_db_20240526_143022",
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

HTTP **200** = all records restored successfully  
HTTP **207** = partial success (some failed — check `failed_ids` and `errors`)

---

### `GET /backups/`

List all BackupLog entries, newest first.

---

### `GET /backups/{id}`

Get a single BackupLog entry by ID.

---

### `DELETE /backups/{id}`

Delete a BackupLog entry and its associated RevertLog records from the meta DB.  
This does **not** delete the actual `.dump` file or the backup database.

---

### `GET /backups/{id}/revert-logs`

List all restore audit entries for a specific backup.

---

### `GET /backups/revert-logs/all`

List every restore audit entry across all backups.

---

## FK ordering guide

Always list tables so that **FK parent tables come before their children**.

### Example — `StudentVoucher` model

```python
class StudentVoucher(models.Model):
    voucher              = ForeignKey(Voucher, ...)          # parent 1
    student              = ForeignKey(Student, ...)          # parent 2
    owner                = ForeignKey(User, ...)             # parent 3
    school_book_student  = ForeignKey(SchoolBookStudent, ...) # parent 4
```

Correct table order for the API:

```json
"tables": [
  "vouchers_voucher",                   // parent 1  ← first
  "account_user",                        // parent 3
  "account_student",                     // parent 2
  "management_schoolbookstudent",        // parent 4
  "vouchers_studentvoucher"              // child     ← last
]
```

---

## Typical workflows

### Workflow 1 — Regular nightly backup

```bash
curl -X POST http://localhost:8000/backup/create \
  -H "Content-Type: application/json" \
  -d '{"notes": "nightly backup", "created_by": "cron"}'
```

### Workflow 2 — Restore a deleted user and related records

**Step 1 — Preview (safe)**
```bash
curl -X POST http://localhost:8000/restore/detect-missing \
  -H "Content-Type: application/json" \
  -d '{
    "tables": ["account_user", "account_student", "vouchers_studentvoucher"],
    "backup_db_name": "backup_db_20240526_143022"
  }'
```

**Step 2 — Restore**
```bash
curl -X POST http://localhost:8000/restore/ordered \
  -H "Content-Type: application/json" \
  -d '{
    "tables": [
      "account_user",
      "account_student",
    ],
    "backup_db_name": "backup_db_20240526_143022",
    "notes": "restoring deleted user #10"
  }'
```

**Step 3 — Check audit trail**
```bash
curl http://localhost:8000/backups/revert-logs/all
```

### Workflow 3 — Find the right backup DB name

```bash
# List all backups ordered by newest first
curl http://localhost:8000/backups/

# Use the db_name field from the response in your restore request
```