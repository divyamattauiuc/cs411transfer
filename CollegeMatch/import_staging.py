"""Stage College Scorecard institutions and numeric liberal-arts rankings safely.

No existing application table is updated, deleted, or truncated.
"""

import argparse
import csv
import os
from pathlib import Path

import pandas as pd
import pymysql


def connect():
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ.get("DB_NAME", "college_explorer"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def schools(path):
    seen = set()
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for record in csv.DictReader(handle):
            uid = integer(record.get("UNITID"))
            name = (record.get("INSTNM") or "").strip()
            if uid is None or not name:
                continue
            if uid in seen:
                raise ValueError(f"Duplicate UNITID in CSV: {uid}")
            seen.add(uid)
            yield (uid, name[:255], integer(record.get("OPEID6")),
                   integer(record.get("CONTROL")), integer(record.get("MAIN")))


def rankings(path, valid_ids):
    frame = pd.read_excel(path, sheet_name="Rankings", header=1)
    year_columns = [column for column in frame.columns if isinstance(column, int) and 1980 <= column <= 2100]
    seen = set()
    ignored_non_numeric = 0
    for _, record in frame.iterrows():
        uid = integer(record.get("IPEDS ID"))
        if uid not in valid_ids:
            continue
        for year in year_columns:
            rank = integer(record.get(year))
            if rank is None or rank <= 0:
                if pd.notna(record.get(year)):
                    ignored_non_numeric += 1
                continue
            key = (uid, year)
            if key in seen:
                raise ValueError(f"Duplicate rank for UNITID/year: {key}")
            seen.add(key)
            yield (uid, year, rank)


def batches(items, size=500):
    group = []
    for item in items:
        group.append(item)
        if len(group) >= size:
            yield group
            group = []
    if group:
        yield group


def query_one(cursor, sql):
    cursor.execute(sql)
    return next(iter(cursor.fetchone().values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institutions", required=True, type=Path)
    parser.add_argument("--rankings", required=True, type=Path)
    parser.add_argument("--stage", action="store_true", help="Create and load new staging tables")
    args = parser.parse_args()

    university_rows = list(schools(args.institutions))
    school_ids = {record[0] for record in university_rows}
    ranking_rows = list(rankings(args.rankings, school_ids))
    print(f"Source: {len(university_rows)} institutions; {len(ranking_rows)} numeric historical ranking rows")
    print(f"Matched ranked colleges: {len({r[0] for r in ranking_rows})}")
    if not args.stage:
        print("Dry run only. Add --stage to create and load staging tables (original tables untouched).")
        return

    with connect() as connection:
        with connection.cursor() as cursor:
            # Never reuse an existing staging table: it might belong to a teammate.
            cursor.execute("SHOW TABLES LIKE 'STAGE_UNIVERSITY_IMPORT'")
            if cursor.fetchone():
                raise RuntimeError("STAGE_UNIVERSITY_IMPORT exists. Stop and inspect it; no changes made.")
            cursor.execute("SHOW TABLES LIKE 'STAGE_RANKING_IMPORT'")
            if cursor.fetchone():
                raise RuntimeError("STAGE_RANKING_IMPORT exists. Stop and inspect it; no changes made.")

            cursor.execute("""CREATE TABLE STAGE_UNIVERSITY_IMPORT (
                UNITID INT NOT NULL PRIMARY KEY,
                INSTNM VARCHAR(255) NOT NULL,
                OPEID6 INT NULL,
                CONTROL INT NULL,
                MAIN INT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cursor.execute("""CREATE TABLE STAGE_RANKING_IMPORT (
                UNITID INT NOT NULL,
                YEAR INT NOT NULL,
                `RANK` INT NOT NULL,
                PRIMARY KEY (UNITID, YEAR),
                FOREIGN KEY (UNITID) REFERENCES STAGE_UNIVERSITY_IMPORT(UNITID)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

            for group in batches(university_rows):
                cursor.executemany("""INSERT INTO STAGE_UNIVERSITY_IMPORT
                    (UNITID, INSTNM, OPEID6, CONTROL, MAIN)
                    VALUES (%s, %s, %s, %s, %s)""", group)
            for group in batches(ranking_rows):
                cursor.executemany("""INSERT INTO STAGE_RANKING_IMPORT
                    (UNITID, YEAR, `RANK`) VALUES (%s, %s, %s)""", group)
            connection.commit()

            count_u = query_one(cursor, "SELECT COUNT(*) FROM STAGE_UNIVERSITY_IMPORT")
            count_r = query_one(cursor, "SELECT COUNT(*) FROM STAGE_RANKING_IMPORT")
            if count_u != len(university_rows) or count_r != len(ranking_rows):
                raise RuntimeError("Staging counts do not match source rows; do not promote")
            print(f"Staged successfully: {count_u} universities, {count_r} rankings")
            cursor.execute("""SELECT
                (SELECT COUNT(*) FROM UNIVERSITY) existing_universities,
                (SELECT COUNT(*) FROM UNIVERSITY WHERE INSTNM LIKE 'Sample University%') sample_universities,
                (SELECT COUNT(*) FROM OFFERS) existing_offers,
                (SELECT COUNT(*) FROM RANKING) existing_rankings,
                (SELECT COUNT(*) FROM OFFERS o JOIN UNIVERSITY u ON u.UNITID=o.UNITID
                 WHERE u.INSTNM LIKE 'Sample University%') sample_offers,
                (SELECT COUNT(*) FROM RANKING r JOIN UNIVERSITY u ON u.UNITID=r.UNITID
                 WHERE u.INSTNM LIKE 'Sample University%') sample_rankings,
                (SELECT COUNT(*) FROM STAGE_UNIVERSITY_IMPORT s JOIN UNIVERSITY u ON s.UNITID=u.UNITID) shared_unitids,
                (SELECT COUNT(*) FROM STAGE_UNIVERSITY_IMPORT s JOIN UNIVERSITY u ON s.UNITID=u.UNITID
                 WHERE u.INSTNM <> s.INSTNM) conflicting_unitid_names""")
            print("Existing-table dependency report:")
            for name, value in cursor.fetchone().items():
                print(f"  {name}: {value}")
            print("No original tables were modified. Review the report before any promotion.")


if __name__ == "__main__":
    main()
