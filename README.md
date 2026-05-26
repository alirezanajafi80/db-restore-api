# LMS Backup Restore API

Async FastAPI service that connects to **two PostgreSQL databases** (main + backup)
and restores deleted records **in FK-dependency order**.

---

## Project structure

```
lms_restore_api/
├── app/
│   ├── main.py                  ← FastAPI app factory + lifespan
│   ├── core/
│   │   ├── config.py            ← Settings (pydantic-settings, .env)
│   │   └── database.py          ← Async engine factory (main / backup / meta)
│   ├── models/
│   │   ├── meta_models.py       ← SQLAlchemy ORM: BackupLog, RevertLog
│   │   └── schemas.py           ← Pydantic v2 request/response schemas
│   ├── services/
│   │   └── restore_service.py   ← Core async restore logic (raw SQL)
│   └── api/
│       ├── restore.py           ← POST /restore/ordered, /restore/detect-missing
│       ├── backups.py           ← GET/DELETE /backups/, /revert-logs/
│       └── health.py            ← GET /health
├── run.py                       ← uvicorn entrypoint
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## Quick start

### 1. Install
```bash
cd lms_restore_api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure
```bash
cp example.env  .env
# Edit .env with your DB credentials
```

### 3. Run
```bash
python run.py
# or
uvicorn app.main:app --reload
```

### 4. Docs
Open http://localhost:8000/docs (Swagger UI)

---

## Docker

```bash
docker-compose up --build
```

| Service  | Port |
|----------|------|
| API      | 8000 |
| main_db  | 5432 |
| backup_db| 5433 |
| meta_db  | 5434 |

---

## API Reference

### `GET /health`
Tests all DB connections.

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

### `POST /restore/detect-missing`  *(read-only)*

Preview what would be restored — **safe to call in production**.

```json
POST /restore/detect-missing
{
  "tables": ["vouchers_voucher", "account_user", "vouchers_studentvoucher"],
  "backup_db_name": "lms_backup_2024_01"
}
```

Response:
```json
{
  "backup_db_used": "lms_backup_2024_01",
  "backup_log_id": null,
  "total_missing": 2,
  "missing": [
    {
      "table": "account_user",
      "object_id": 10,
      "data": { "id": 10, "username": "john", "email": "john@example.com", ... }
    },
    {
      "table": "vouchers_studentvoucher",
      "object_id": 201,
      "data": { "id": 201, "voucher_id": 55, "student_id": 10, ... }
    }
  ]
}
```

---

### `POST /restore/ordered`  *(writes to main DB)*

Restores missing records in order.

```json
POST /restore/ordered
{
  "tables": [
    "vouchers_voucher",
    "account_user",
    "account_student",
    "vouchers_studentvoucher"
  ],
  "backup_db_name": "lms_backup_2024_01",
  "notes": "Restoring user #10 and related records",
  "dry_run": false
}
```

Response:
```json
{
  "backup_db_used": "lms_backup_2024_01",
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

**HTTP 200** = all restored  
**HTTP 207** = partial success (some failed)

---

### `backup_db_name` logic

| Request body | Connects to |
|---|---|
| `"backup_db_name": "lms_backup_jan"` | DB named `lms_backup_jan` on backup host |
| `"backup_db_name": null` or omitted | Default backup DB from `.env` |

The backup host, port, user, password are always taken from `.env`.
Only the **database name** changes per request.

---

## ⚠️ Order matters — FK dependency rule

Always list **parent tables before child tables**:

```
WRONG:  ["vouchers_studentvoucher", "vouchers_voucher"]
                   ↑ child before parent → FK error

CORRECT: ["vouchers_voucher", "account_user", "vouchers_studentvoucher"]
                ↑ parents first ↑              ↑ child last
```

---

## Settings reference (`.env`)

| Variable | Description |
|---|---|
| `MAIN_DB_*` | Production database connection |
| `DEFAULT_BACKUP_DB_*` | Default backup database connection |
| `META_DB_*` | Internal audit-trail database |
| `AWS_*` | S3 credentials (optional) |
| `APP_ENV` | `development` or `production` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` |