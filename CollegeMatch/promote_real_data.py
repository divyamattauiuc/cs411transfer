"""Promote validated CollegeMatch staging data into the original six-table schema.

Run --check first. --apply requires explicit confirmation; a backup is strongly
recommended but may be waived using --no-backup. Changes use one transaction.
"""

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path

import pymysql


def connect():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        database=os.getenv("DB_NAME", "college_explorer"),
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        autocommit=False, read_timeout=900, write_timeout=900,
    )


def one(cursor, sql, params=()):
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    return next(iter(cursor.fetchone().values()))


def chunks(records, size=1000):
    group = []
    for record in records:
        group.append(record)
        if len(group) >= size:
            yield group
            group = []
    if group:
        yield group


def state_lookup(csv_path):
    states = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                uid = int(row["UNITID"])
            except (ValueError, KeyError):
                continue
            state = row.get("STABBR", "").strip().upper()
            if state:
                states[uid] = state
    return states


def validate_and_prepare(cursor, states):
    required = ["STAGE_UNIVERSITY_IMPORT", "STAGE_PROGRAM_IMPORT_V2",
                "STAGE_DEGREE_IMPORT_V2", "STAGE_OFFERS_RAW_IMPORT_V2",
                "STAGE_NATIONAL_RANKING_IMPORT_V2", "STAGE_RANKING_IMPORT"]
    for table in required:
        cursor.execute("SHOW TABLES LIKE %s", (table,))
        if not cursor.fetchone():
            raise RuntimeError(f"Missing staging table: {table}")

    # Protect against any unexpected external foreign keys.
    cursor.execute("""SELECT TABLE_NAME, REFERENCED_TABLE_NAME
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE REFERENCED_TABLE_SCHEMA = DATABASE()
          AND REFERENCED_TABLE_NAME IN ('UNIVERSITY','PROGRAM','DEGREE','OFFERS','RANKING')
          AND TABLE_NAME NOT IN ('UNIVERSITY','PROGRAM','DEGREE','OFFERS','RANKING','STATE')""")
    external = cursor.fetchall()
    if external:
        raise RuntimeError(f"Unexpected dependent tables: {external}")

    old_total = one(cursor, "SELECT COUNT(*) FROM UNIVERSITY")
    old_samples = one(cursor, "SELECT COUNT(*) FROM UNIVERSITY WHERE INSTNM LIKE 'Sample University%'")
    if not old_total or old_total != old_samples:
        raise RuntimeError("UNIVERSITY contains non-sample records. Refusing replacement.")
    program_count = one(cursor, "SELECT COUNT(*) FROM PROGRAM")
    sample_programs = one(cursor, "SELECT COUNT(*) FROM PROGRAM WHERE CIPDESC LIKE 'Sample Academic Program%'")
    if program_count != sample_programs:
        raise RuntimeError("PROGRAM contains non-sample descriptions. Refusing replacement.")
    for table in ("OFFERS", "RANKING"):
        linked_sample = one(cursor, f"""SELECT COUNT(*) FROM {table} t
            JOIN UNIVERSITY u ON u.UNITID=t.UNITID
            WHERE u.INSTNM LIKE 'Sample University%'""")
        if linked_sample != one(cursor, f"SELECT COUNT(*) FROM {table}"):
            raise RuntimeError(f"{table} contains non-sample or orphaned records")

    cursor.execute("SELECT StateCode FROM STATE")
    valid_states = {r["StateCode"] for r in cursor.fetchall()}
    if not valid_states:
        raise RuntimeError("STATE is empty; cannot satisfy PROGRAM.StateCode")

    cursor.execute("SELECT UNITID FROM STAGE_UNIVERSITY_IMPORT")
    valid_ids = {r["UNITID"] for r in cursor.fetchall()}
    if len(valid_ids) < 6000:
        raise RuntimeError("Too few staged universities; expected ~6273")

    cursor.execute("SELECT CIPCODE, CIPDESC FROM STAGE_PROGRAM_IMPORT_V2")
    program_desc = {r["CIPCODE"]: r["CIPDESC"] for r in cursor.fetchall()}
    cursor.execute("SELECT CREDLEV, CREDDESC FROM STAGE_DEGREE_IMPORT_V2")
    degrees = {r["CREDLEV"]: r["CREDDESC"] for r in cursor.fetchall()}

    # Program's representative state is the state of the numerically lowest
    # eligible university UNITID offering the program. This is not exclusivity.
    rep = {}
    offers = []
    unmatched = 0
    cursor.execute("""SELECT UNITID,CIPCODE,CREDLEV,IPEDSCOUNT1,IPEDSCOUNT2,
        DEBT_ALL_STGP_ANY_N,DEBT_ALL_STGP_ANY_MEAN,DEBT_ALL_STGP_ANY_MDN
        FROM STAGE_OFFERS_RAW_IMPORT_V2 ORDER BY UNITID,CIPCODE,CREDLEV""")
    for row in cursor:
        uid, code, level = row["UNITID"], row["CIPCODE"], row["CREDLEV"]
        if uid not in valid_ids or code not in program_desc or level not in degrees:
            unmatched += 1
            continue
        state = states.get(uid)
        if state not in valid_states:
            unmatched += 1
            continue
        if code not in rep or uid < rep[code][0]:
            rep[code] = (uid, state)
        offers.append((uid, code, level, row["IPEDSCOUNT1"], row["IPEDSCOUNT2"],
                       row["DEBT_ALL_STGP_ANY_N"], row["DEBT_ALL_STGP_ANY_MEAN"],
                       row["DEBT_ALL_STGP_ANY_MDN"]))

    if len({row[:3] for row in offers}) != len(offers):
        raise RuntimeError("Duplicate composite OFFERS keys after filtering")
    programs = [(code, program_desc[code], rep[code][1]) for code in sorted(rep)]
    used_levels = {r[2] for r in offers}
    degree_rows = [(level, degrees[level]) for level in sorted(used_levels)]

    ranking_map = {}
    for name in ("STAGE_RANKING_IMPORT", "STAGE_NATIONAL_RANKING_IMPORT_V2"):
        cursor.execute(f"SELECT UNITID,YEAR,`RANK` FROM {name}")
        for r in cursor.fetchall():
            if r["UNITID"] in valid_ids:
                ranking_map[(r["UNITID"], r["YEAR"])] = r["RANK"]
    # National rankings win if a university/year appears in both sources.
    rankings = [(uid, year, rank) for (uid, year), rank in sorted(ranking_map.items())]
    print(f"CHECK: existing universities={old_total} (all sample)")
    print(f"CHECK: import universities={len(valid_ids)}, degrees={len(degree_rows)}, programs={len(programs)}")
    print(f"CHECK: valid OFFERS={len(offers)}, excluded unmapped OFFERS={unmatched}, rankings={len(rankings)}")
    print("PROGRAM.StateCode represents the state of the lowest-UNITID qualifying offering university.")
    if not offers or not programs or not rankings:
        raise RuntimeError("Prepared data unexpectedly empty")
    return len(valid_ids), programs, degree_rows, offers, rankings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institutions", required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    backup_mode = parser.add_mutually_exclusive_group()
    backup_mode.add_argument("--backup", type=Path, help="Verified SQL backup file")
    backup_mode.add_argument("--no-backup", action="store_true", help="Proceed without recovery copy (irreversible after commit)")
    parser.add_argument("--confirm", help="Must equal REPLACE_SAMPLES for --apply")
    args = parser.parse_args()
    if args.apply:
        if not args.backup and not args.no_backup:
            raise RuntimeError("Choose --backup PATH or explicitly acknowledge --no-backup")
        if args.backup and (not args.backup.is_file() or args.backup.stat().st_size < 10000):
            raise RuntimeError("Backup file not found or unexpectedly small")
        if args.confirm != "REPLACE_SAMPLES":
            raise RuntimeError("--apply requires --confirm REPLACE_SAMPLES")
        if args.no_backup:
            print("WARNING: No backup. Original sample rows cannot be recovered after commit.")

    states = state_lookup(args.institutions)
    with connect() as connection:
        try:
            with connection.cursor() as cursor:
                university_count, programs, degrees, offers, rankings = validate_and_prepare(cursor, states)
                if args.check:
                    print("Read-only check complete. No live tables modified.")
                    return

                # No DDL here: all operations can rollback together.
                cursor.execute("DELETE FROM OFFERS")
                cursor.execute("DELETE FROM RANKING")
                cursor.execute("DELETE FROM PROGRAM")
                cursor.execute("DELETE FROM DEGREE")
                cursor.execute("DELETE FROM UNIVERSITY")

                cursor.execute("""INSERT INTO UNIVERSITY(UNITID,INSTNM,OPEID6,CONTROL,MAIN)
                    SELECT UNITID,INSTNM,OPEID6,CONTROL,MAIN FROM STAGE_UNIVERSITY_IMPORT""")
                for part in chunks(degrees):
                    cursor.executemany("INSERT INTO DEGREE(CREDLEV,CREDDESC) VALUES (%s,%s)", part)
                for part in chunks(programs):
                    cursor.executemany("INSERT INTO PROGRAM(CIPCODE,CIPDESC,StateCode) VALUES (%s,%s,%s)", part)
                for part in chunks(offers):
                    cursor.executemany("""INSERT INTO OFFERS
                        (UNITID,CIPCODE,CREDLEV,IPEDSCOUNT1,IPEDSCOUNT2,
                         DEBT_ALL_STGP_ANY_N,DEBT_ALL_STGP_ANY_MEAN,DEBT_ALL_STGP_ANY_MDN)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", part)
                for part in chunks(rankings):
                    cursor.executemany("INSERT INTO RANKING(UNITID,YEAR,`RANK`) VALUES (%s,%s,%s)", part)

                checks = {"UNIVERSITY": university_count, "PROGRAM": len(programs),
                          "DEGREE": len(degrees), "OFFERS": len(offers), "RANKING": len(rankings)}
                for table, expected in checks.items():
                    actual = one(cursor, f"SELECT COUNT(*) FROM {table}")
                    if actual != expected:
                        raise RuntimeError(f"{table} count {actual} != {expected}; rolling back")
                for table, join in (
                    ("OFFERS", "LEFT JOIN UNIVERSITY u ON u.UNITID=t.UNITID WHERE u.UNITID IS NULL"),
                    ("OFFERS", "LEFT JOIN PROGRAM p ON p.CIPCODE=t.CIPCODE WHERE p.CIPCODE IS NULL"),
                    ("OFFERS", "LEFT JOIN DEGREE d ON d.CREDLEV=t.CREDLEV WHERE d.CREDLEV IS NULL"),
                    ("RANKING", "LEFT JOIN UNIVERSITY u ON u.UNITID=t.UNITID WHERE u.UNITID IS NULL"),
                ):
                    if one(cursor, f"SELECT COUNT(*) FROM {table} t {join}"):
                        raise RuntimeError(f"Unmatched foreign key in {table}; rolling back")
                if one(cursor, "SELECT COUNT(*) FROM UNIVERSITY WHERE INSTNM LIKE 'Sample University%'"):
                    raise RuntimeError("Unexpected sample university names remain; rolling back")
                print("All counts verified in transaction; committing replacement")
            connection.commit()
            print("COMMITTED. Original table definitions unchanged; STATE rows retained.")
        except BaseException:
            connection.rollback()
            raise


if __name__ == "__main__":
    main()
