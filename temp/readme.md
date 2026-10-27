# temp/ — build verification (temporary)

This folder exists only on the `temp/build-log` branch. It records evidence that the DaaS engine works end to end.

| File | What it is |
|---|---|
| `build.log` | Output captured on 2026-10-27 covering the test suite, the migration check, a live incremental ingest, a data profile, and an API smoke test. |

What the log shows:

- **Tests:** all 50 pass against Postgres 16.
- **Migrations:** they match the models (`alembic check`: no new operations).
- **Ingest:** a live incremental run against NY DOS and CO SOS fetched 9,414 rows, inserted 0 and updated 0. Nothing new had been published upstream since the previous run, so this confirms that re-ingesting is idempotent.
- **Archive:** 10,858 filings, 3,488 of them scoring 75 or higher.
- **API:**
  - A request without a key gets 401.
  - Search with filters returns real leads filed 2026-10-24.
  - Rate-limit and quota headers are set.
  - Usage metering counts 3 records for 3 returned.
  - CSV export works on the Growth plan.

The log contains business names and cities from public state filings. It contains no API keys or contact names.

## Removing it

Delete `temp/` before or after merging. It isn't used by the build, tests or Docker image:

```bash
git rm -r temp && git commit -m "Remove temporary build log"
```

The folder is lowercase `temp/readme.md` on purpose. A second `readme.md` at the repo root would collide with `README.md` on case-insensitive filesystems (macOS, Windows).
