"""Stage Scorecard field-of-study and national rankings without touching live tables.

Requires STAGE_UNIVERSITY_IMPORT from import_staging.py first.
"""

import argparse
import csv
import os
from pathlib import Path

import pandas as pd
import pymysql


def db():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        database=os.getenv("DB_NAME", "college_explorer"),
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def num(value):
    try:
        if value is None or str(value).strip() in ("", "NA", "PS"):
            return None
        return int(float(value))
    except (ValueError, TypeError, OverflowError):
        return None


def debt(value):
    try:
        if value is None or str(value).strip() in ("", "NA", "PS"):
            return None
        return round(float(value), 2)
    except (ValueError, TypeError):
        return None


def groups(iterable, chunk=500):
    batch = []
    for row in iterable:
        batch.append(row)
        if len(batch) == chunk:
            yield batch
            batch = []
    if batch:
        yield batch


def data_rows(path):
    programs = {}
    degrees = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"UNITID", "CIPCODE", "CIPDESC", "CREDLEV", "CREDDESC", "IPEDSCOUNT1", "IPEDSCOUNT2"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Missing field-of-study columns: {required - set(reader.fieldnames or [])}")
        for line, record in enumerate(reader, start=2):
            uid = num(record["UNITID"])
            code = record["CIPCODE"].strip()
            level = num(record["CREDLEV"])
            if uid is None or not code or level is None:
                # The source contains some incomplete records. They cannot be
                # inserted into OFFERS, whose composite key is NOT NULL.
                continue
            description = record["CIPDESC"].strip()
            degree_description = record["CREDDESC"].strip()
            if code in programs and programs[code] != description:
                raise ValueError(f"Conflicting description for CIPCODE {code}")
            if level in degrees and degrees[level] != degree_description:
                raise ValueError(f"Conflicting description for CREDLEV {level}")
            programs[code] = description
            degrees[level] = degree_description
            yield (line, uid, code, level, num(record["IPEDSCOUNT1"]),
                   num(record["IPEDSCOUNT2"]),
                   num(record.get("DEBT_ALL_STGP_ANY_N")),
                   debt(record.get("DEBT_ALL_STGP_ANY_MEAN")),
                   debt(record.get("DEBT_ALL_STGP_ANY_MDN")))


def metadata(path):
    programs, degrees = {}, {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for r in csv.DictReader(handle):
            code, level = r["CIPCODE"].strip(), num(r["CREDLEV"])
            if code and level is not None and num(r["UNITID"]) is not None:
                programs[code] = r["CIPDESC"].strip()
                degrees[level] = r["CREDDESC"].strip()
    return programs, degrees


def national_ranks(path, known_ids):
    df = pd.read_excel(path, sheet_name="Top 150 National Universities")
    columns = [c for c in df.columns if str(c).isdigit() and 1980 <= int(c) <= 2100]
    rows = []
    skipped = 0
    for _, record in df.iterrows():
        uid = num(record["IPEDS"])
        if uid not in known_ids:
            skipped += 1
            continue
        for year in columns:
            rank = num(record[year])
            if rank and rank > 0:
                rows.append((uid, int(year), rank))
    if len({(x[0], x[1]) for x in rows}) != len(rows):
        raise ValueError("Duplicate university/year pair in ranking workbook")
    return rows, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--field-of-study", required=True, type=Path)
    parser.add_argument("--national-rankings", required=True, type=Path)
    parser.add_argument("--stage", action="store_true", help="Create new staging tables")
    args = parser.parse_args()

    programs, degrees = metadata(args.field_of_study)
    with open(args.field_of_study, newline="", encoding="utf-8-sig") as handle:
        source_count = sum(1 for _ in csv.DictReader(handle))
    field_count = sum(1 for _ in data_rows(args.field_of_study))
    # Workbook records may include universities missing from the field-of-study CSV.
    with db() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'STAGE_UNIVERSITY_IMPORT'")
            if not cursor.fetchone():
                raise RuntimeError("Run import_staging.py --stage first to stage institutions")
            cursor.execute("SELECT UNITID FROM STAGE_UNIVERSITY_IMPORT")
            known_ids = {r["UNITID"] for r in cursor.fetchall()}
            rank_rows, missing_rank_ids = national_ranks(args.national_rankings, known_ids)
            print(f"Field-of-study rows: {source_count}; valid-key rows: {field_count}; skipped missing-key rows: {source_count-field_count}; programs: {len(programs)}; degree levels: {len(degrees)}")
            print(f"National ranking rows: {len(rank_rows)}; workbook schools absent from institution CSV: {missing_rank_ids}")
            if not args.stage:
                print("Dry run only; pass --stage to create NEW staging tables")
                return

            # V2 names intentionally leave the tables created by the failed
            # previous attempt untouched for investigation.
            names = ["STAGE_PROGRAM_IMPORT_V2", "STAGE_DEGREE_IMPORT_V2", "STAGE_OFFERS_RAW_IMPORT_V2", "STAGE_NATIONAL_RANKING_IMPORT_V2"]
            for name in names:
                cursor.execute(f"SHOW TABLES LIKE '{name}'")
                if cursor.fetchone():
                    raise RuntimeError(f"{name} already exists; no changes made. Inspect before retrying")

            cursor.execute("""CREATE TABLE STAGE_PROGRAM_IMPORT_V2 (
                CIPCODE VARCHAR(20) PRIMARY KEY, CIPDESC VARCHAR(255) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cursor.execute("""CREATE TABLE STAGE_DEGREE_IMPORT_V2 (
                CREDLEV INT PRIMARY KEY, CREDDESC VARCHAR(255) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cursor.execute("""CREATE TABLE STAGE_OFFERS_RAW_IMPORT_V2 (
                source_line INT PRIMARY KEY,
                UNITID INT NOT NULL, CIPCODE VARCHAR(20) NOT NULL, CREDLEV INT NOT NULL,
                IPEDSCOUNT1 INT NULL, IPEDSCOUNT2 INT NULL,
                DEBT_ALL_STGP_ANY_N INT NULL,
                DEBT_ALL_STGP_ANY_MEAN DECIMAL(12,2) NULL,
                DEBT_ALL_STGP_ANY_MDN DECIMAL(12,2) NULL,
                INDEX (UNITID, CIPCODE, CREDLEV)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cursor.execute("""CREATE TABLE STAGE_NATIONAL_RANKING_IMPORT_V2 (
                UNITID INT NOT NULL, YEAR INT NOT NULL, `RANK` INT NOT NULL,
                PRIMARY KEY (UNITID, YEAR)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cursor.executemany("INSERT INTO STAGE_PROGRAM_IMPORT_V2 VALUES (%s,%s)", list(programs.items()))
            cursor.executemany("INSERT INTO STAGE_DEGREE_IMPORT_V2 VALUES (%s,%s)", list(degrees.items()))
            insert_sql = """INSERT INTO STAGE_OFFERS_RAW_IMPORT_V2
                (source_line,UNITID,CIPCODE,CREDLEV,IPEDSCOUNT1,IPEDSCOUNT2,
                 DEBT_ALL_STGP_ANY_N,DEBT_ALL_STGP_ANY_MEAN,DEBT_ALL_STGP_ANY_MDN)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
            for chunk in groups(data_rows(args.field_of_study)):
                cursor.executemany(insert_sql, chunk)
            for chunk in groups(rank_rows):
                cursor.executemany("INSERT INTO STAGE_NATIONAL_RANKING_IMPORT_V2 VALUES (%s,%s,%s)", chunk)
            connection.commit()

            cursor.execute("""SELECT COUNT(*) AS raw_rows,
                COUNT(DISTINCT UNITID,CIPCODE,CREDLEV) AS unique_offers
                FROM STAGE_OFFERS_RAW_IMPORT_V2""")
            print("Staged field records:", cursor.fetchone())
            cursor.execute("""SELECT COUNT(*) AS missing_institutions
                FROM STAGE_OFFERS_RAW_IMPORT_V2 o
                LEFT JOIN STAGE_UNIVERSITY_IMPORT u ON u.UNITID=o.UNITID
                WHERE u.UNITID IS NULL""")
            print("Unmatched field-of-study rows:", cursor.fetchone()["missing_institutions"])
            cursor.execute("""SELECT COUNT(*) AS count_rows FROM STAGE_NATIONAL_RANKING_IMPORT_V2""")
            print("Staged national rankings:", cursor.fetchone()["count_rows"])
            print("Live tables unchanged. PROGRAM.StateCode cannot be sourced from these files.")


if __name__ == "__main__":
    main()
