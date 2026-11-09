"""CollegeMatch Flask API backed by the existing college_explorer schema."""

import os

import pymysql
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


def db_connection():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.getenv("DB_NAME", "college_explorer"),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        read_timeout=20,
        autocommit=True,
        ssl_ca=os.getenv("DB_SSL_CA") or None,
    )


@app.get("/")
def explore():
    return render_template("index.html")


@app.get("/compare")
def compare():
    return render_template("compare.html")


@app.get("/favorites")
def favorites():
    return render_template("favorites.html")


@app.get("/api/universities")
def universities():
    name = request.args.get("name", "").strip()
    major = request.args.get("major", "").strip()
    ids_text = request.args.get("ids", "").strip()
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 200)
        ids = [int(value) for value in ids_text.split(",") if value.strip()] if ids_text else []
    except ValueError:
        return jsonify({"error": "Invalid ID or limit"}), 400
    if len(ids) > 200:
        return jsonify({"error": "Too many IDs"}), 400

    clauses = ["u.INSTNM LIKE %s"]
    params = [f"%{name}%"]
    if ids_text:
        if not ids:
            return jsonify([])
        clauses.append("u.UNITID IN (" + ",".join(["%s"] * len(ids)) + ")")
        params.extend(ids)
    if major:
        clauses.append("""EXISTS (
            SELECT 1 FROM OFFERS o JOIN PROGRAM p ON p.CIPCODE = o.CIPCODE
            WHERE o.UNITID = u.UNITID AND p.CIPDESC LIKE %s
        )""")
        params.append(f"%{major}%")

    # RANKING uses a composite (UNITID, YEAR) key; select its latest year.
    sql = f"""
        SELECT u.UNITID AS id, u.INSTNM AS name,
               (SELECT r.RANK FROM RANKING r
                WHERE r.UNITID = u.UNITID
                ORDER BY r.YEAR DESC LIMIT 1) AS latest_rank,
               (SELECT r.YEAR FROM RANKING r
                WHERE r.UNITID = u.UNITID
                ORDER BY r.YEAR DESC LIMIT 1) AS rank_year
        FROM UNIVERSITY u
        WHERE {' AND '.join(clauses)}
        ORDER BY u.INSTNM ASC
        LIMIT %s
    """
    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params + [limit])
                records = cursor.fetchall()
    except pymysql.MySQLError:
        app.logger.exception("MySQL university lookup failed")
        return jsonify({"error": "Database lookup failed"}), 503
    return jsonify(records)


@app.get("/api/health")
def health():
    try:
        with db_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                cursor.fetchone()
    except pymysql.MySQLError:
        app.logger.exception("Database health check failed")
        return jsonify({"database": "unavailable"}), 503
    return jsonify({"database": "connected"})


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
