# ValuePilot — Claude Code Guidelines

## Database schema changes

### Rule: schema constraints must be fixed at the schema level

When runtime code hits a DB constraint violation (column too short, wrong type, missing index, etc.), the correct fix is **always a migration**, not a code-level workaround.

**Wrong (band-aid):**
```python
# Silently truncates data to fit the column
source=source[:20]
```
```python
# Renaming a string constant to sneak under the limit
source = "sec_co_tickers"   # was "edgar_company_tickers" (21 chars → 20 limit)
```

**Right:**
1. Write an Alembic migration to fix the column definition:
   ```python
   op.alter_column("table", "column",
       existing_type=sa.String(20),
       type_=sa.String(50),
       existing_nullable=True)
   ```
2. Update the SQLAlchemy model (`String(20)` → `String(50)`).
3. Remove every code-level guard/truncation introduced as a workaround.
4. Apply with `alembic upgrade head`.

**Why:** band-aids hide the root cause, silently truncate data, and leave the system in a state where any new value longer than the limit will fail again — or worse, succeed silently with corrupted data.

---

## Alembic conventions

- Migration filename: `YYYYMMDDHHMMSS-<slug>.py`
- `down_revision` must match the **`revision` variable** inside the parent file, not the filename.
- Always verify applied with `\d <table>` in psql after running `alembic upgrade head`.

---

## EDGAR / 13F pipeline

- `shrsOrPrnAmt` is a wrapper element in infotable XML; unwrap it to read `sshPrnamt` / `sshPrnamtType`.
- `xslForm13F_X02/` paths in EDGAR filing index are XSLT-rendered HTML, not machine-readable XML — skip them when scanning for infotable URLs.
- `cusip_ticker_map.source` is VARCHAR(50); valid source strings: `"dataroma"`, `"sec_co_tickers"`, `"manual"`.
- Kahn Brothers (`0001039565-*`) reports values in dollars, not thousands — reconciliation warnings for this filer are True Positives, not bugs.
