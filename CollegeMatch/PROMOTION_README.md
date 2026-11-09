# CollegeMatch: final promotion of real data (destructive; read before use)

This script uses the six existing table definitions **unchanged**. It does not run `ALTER TABLE`, `DROP TABLE`, or disable foreign-key checks. It deletes the current sample rows and inserts validated real rows into `UNIVERSITY`, `PROGRAM`, `DEGREE`, `OFFERS`, and `RANKING` inside **one transaction**. `STATE` is untouched. Your original samples will be lost from the live tables after a successful commit. A verified backup is strongly recommended, but the user may explicitly waive it.

It requires all six staging tables from the previous scripts, including the `_V2` tables.

## Preflight / mapping policy

- Imports all 6,273 staged institutions.
- Only imports `OFFERS` whose university exists in the institution staging table and whose institution state is present in the existing `STATE` table. Unmatched source records are excluded and counted.
- For each `PROGRAM.CIPCODE`, assigns **one representative `StateCode`**: the state of the lowest-`UNITID` eligible university that offers that program. This is a technical representative for the original schema and **does not mean the program is limited to that state**.
- Imports the relevant `DEGREE` records.
- Combines both ranking sources by `(UNITID,YEAR)`. **National rankings take precedence** if both datasets contain a rank for the same university and year. Rankings are category-specific; the unmodified `RANKING` table has no category field and cannot express the distinction.
- The staged raw field-of-study table includes only the debt/enrollment columns available in the staging schema. Other `OFFERS` debt columns remain NULL. It does not invent values.
- Refuses promotion if live `UNIVERSITY` or `PROGRAM` contains non-sample records, staging tables are missing, unexpected external FK references exist, key counts are too small, or validation fails.

## Back up before promotion

Create a Cloud SQL on-demand backup in Google Cloud Console **and** an independently restorable SQL dump. With Cloud SQL Proxy running and a MySQL CLI installed, run in your Mac's CollegeMatch terminal:

```bash
mysqldump --host=127.0.0.1 --port=3306 --user=hi-411 --password \
  --single-transaction --routines --triggers \
  --result-file="$HOME/Downloads/college_explorer_before_promotion.sql" college_explorer
```

The password prompt is interactive. Verify the command exits successfully and the file is nonempty; ideally verify restoring to a **separate test database**. Never share the dump publicly. If `mysqldump` is not installed or you do not have permission to perform a backup, stop and ask your team/database admin to help.

## Check only: no changes

```bash
python promote_real_data.py \
  --institutions "$HOME/Downloads/College_Scorecard_Raw_Data_06032026/Most-Recent-Cohorts-Institution.csv" \
  --check
```

Inspect counts and excluded records. Review the representative-state and ranking-source policies above with your team before authorizing a live replacement.

## Execute only after reviewing the check and backup

```bash
python promote_real_data.py \
  --institutions "$HOME/Downloads/College_Scorecard_Raw_Data_06032026/Most-Recent-Cohorts-Institution.csv" \
  --apply \
  --backup "$HOME/Downloads/college_explorer_before_promotion.sql" \
  --confirm REPLACE_SAMPLES
```

`--apply` is destructive and should only be used after the backup is verified and your teammates agree. The script attempts a transaction rollback if an error occurs; a separate backup remains necessary.

If you explicitly choose to proceed **without a backup**, use the following instead. There will be no recovery copy of the original sample rows after commit:

```bash
python promote_real_data.py \
  --institutions "$HOME/Downloads/College_Scorecard_Raw_Data_06032026/Most-Recent-Cohorts-Institution.csv" \
  --apply --no-backup --confirm REPLACE_SAMPLES
```

## Afterward, verify read-only

```sql
SELECT COUNT(*) FROM UNIVERSITY;
SELECT COUNT(*) FROM PROGRAM;
SELECT COUNT(*) FROM DEGREE;
SELECT COUNT(*) FROM OFFERS;
SELECT COUNT(*) FROM RANKING;
SELECT COUNT(*) FROM STATE;
SELECT UNITID, INSTNM FROM UNIVERSITY ORDER BY UNITID LIMIT 10;
SELECT COUNT(*) FROM UNIVERSITY WHERE INSTNM LIKE 'Sample University%';
```

Keep the staging tables and backup until everyone verifies the frontend and the team signs off on the new data.
