# Database migrations

Alembic is the authoritative mechanism for database schema evolution. The
application's existing `create_all()` startup behavior remains temporarily for
fresh local development; application startup does not run Alembic migrations.

For a fresh database configured through the application settings:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

For an existing database that has been independently confirmed to match the
baseline schema:

```powershell
.\.venv\Scripts\python.exe -m alembic stamp 0001_analysis_baseline
```

`stamp` records migration state without changing or validating the database
schema. Never stamp a database until its schema has been confirmed to match the
baseline.

After future revisions are added, update a database with:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```
