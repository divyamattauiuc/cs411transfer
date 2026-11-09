# CollegeMatch: safe GCP MySQL staging import

These scripts stage all four supplied datasets **without changing** any existing `UNIVERSITY`, `RANKING`, `OFFERS`, `PROGRAM`, `DEGREE`, or `STATE` row. They make no production table replacements.

## What it imports

- College Scorecard institution CSV: `UNITID`, `INSTNM`, `OPEID6`, `CONTROL`, `MAIN` into `STAGE_UNIVERSITY_IMPORT`.
- Andrew G. Reiter, *U.S. News & World Report Historical Liberal Arts College and University Rankings* (`http://andyreiter.com/datasets/`): numeric year/rank rows whose IPEDS IDs match the institution CSV into `STAGE_RANKING_IMPORT`. Nonnumeric tier labels are skipped, not converted to fabricated ranks.

The CSV also includes metrics not represented in the current five-column `UNIVERSITY` schema. Those are **not imported** in this phase. The liberal arts rankings cover only a subset of all institutions.

The second script stages field-of-study rows with complete keys into `STAGE_OFFERS_RAW_IMPORT_V2` (preserving duplicate keys), plus `STAGE_PROGRAM_IMPORT_V2` and `STAGE_DEGREE_IMPORT_V2`. It also stages national rankings into `STAGE_NATIONAL_RANKING_IMPORT_V2`. It reports source records skipped for missing required keys. The V2 names avoid modifying potentially half-created tables from an earlier failed attempt. The existing `PROGRAM` table requires a `StateCode` that is not present in the field-of-study file, so that missing mapping remains a deliberate blocker to promotion. Historical rankings are not a comprehensive ranking of all US institutions.

## Before running

1. Have a team admin create a verified **Cloud SQL backup** or independent SQL export of the full `college_explorer` database. Do not rely solely on staging tables for disaster recovery.
2. Start the proxy in Terminal 1:

   ```bash
   ~/Downloads/cloud-sql-proxy --address 127.0.0.1 --port 3306 teamhi411:us-east1:hi-411
   ```

3. In Terminal 2, open `CollegeMatch`, activate `.venv`, install packages:

   ```bash
   source .venv/bin/activate
   pip install -r staging-requirements.txt
   ```

4. Configure credentials without placing your password in the command history:

   ```zsh
   export DB_HOST=127.0.0.1
   export DB_PORT=3306
   export DB_USER=hi-411
   export DB_NAME=college_explorer
   read -s 'DB_PASSWORD?MySQL password: '
   echo
   export DB_PASSWORD
   ```

5. Put both original datasets anywhere convenient (for example, Downloads). Supply their exact file paths; do not rename the columns or workbook sheet.

## Preview source data without touching GCP

```bash
python import_staging.py \
  --institutions "$HOME/Downloads/Most-Recent-Cohorts-Institution.csv" \
  --rankings "$HOME/Downloads/US-News-Rankings-Liberal-Arts-Colleges-Through-2027.xlsx"
```

## Import into NEW staging tables only

```bash
python import_staging.py \
  --institutions "$HOME/Downloads/Most-Recent-Cohorts-Institution.csv" \
  --rankings "$HOME/Downloads/US-News-Rankings-Liberal-Arts-Colleges-Through-2027.xlsx" \
  --stage
```

The staging command refuses to overwrite existing staging tables. It then prints original table counts, counts of sample records and their related rows, overlapping IDs, and name collisions. The script never deletes sample data or promotes staging rows.

## Stage the field-of-study data and national rankings

Run **after** the first staging import, with the two newly uploaded files:

```bash
python stage_additional_data.py \
  --field-of-study "$HOME/Downloads/Most-Recent-Cohorts-Field-of-Study.csv" \
  --national-rankings "$HOME/Downloads/US-News-National-University-Rankings-Top-150-Through-2027.xlsx"
```

This dry run reads the staging institution IDs from GCP but does not change any data.

After reviewing its output, run the same command with `--stage` appended. It creates four new staging tables, preserves all source rows, and prints unmatched university and duplicate-offer counts. It refuses to overwrite staging tables that already exist.

## Independent SQL verification (Cloud SQL Studio)

```sql
SELECT COUNT(*) FROM STAGE_UNIVERSITY_IMPORT;
SELECT COUNT(*) FROM STAGE_RANKING_IMPORT;
SELECT UNITID, INSTNM FROM STAGE_UNIVERSITY_IMPORT ORDER BY UNITID LIMIT 10;
SELECT s.UNITID, s.INSTNM AS incoming, u.INSTNM AS existing
FROM STAGE_UNIVERSITY_IMPORT s
JOIN UNIVERSITY u ON u.UNITID = s.UNITID
WHERE s.INSTNM <> u.INSTNM
LIMIT 30;
SELECT COUNT(*) AS dependent_offers
FROM OFFERS o JOIN UNIVERSITY u ON u.UNITID = o.UNITID
WHERE u.INSTNM LIKE 'Sample University%';
SELECT COUNT(*) AS dependent_rankings
FROM RANKING r JOIN UNIVERSITY u ON u.UNITID = r.UNITID
WHERE u.INSTNM LIKE 'Sample University%';
SELECT COUNT(*) AS raw_offers FROM STAGE_OFFERS_RAW_IMPORT_V2;
SELECT UNITID, CIPCODE, CREDLEV, COUNT(*) AS repetitions
FROM STAGE_OFFERS_RAW_IMPORT_V2
GROUP BY UNITID, CIPCODE, CREDLEV
HAVING COUNT(*) > 1
ORDER BY repetitions DESC LIMIT 25;
SELECT COUNT(*) FROM STAGE_NATIONAL_RANKING_IMPORT_V2;
```

**Stop here and review** the report with the team. Production promotion will require a separate migration design, especially because the institution CSV has no accurate `OFFERS` program/degree records, and existing IDs may collide with real ones. Avoid `SET FOREIGN_KEY_CHECKS=0`, direct renaming of sample universities, or deleting any existing tables.
