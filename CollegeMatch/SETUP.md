# Connect CollegeMatch to Google Cloud SQL (MySQL)

Place `app.py`, `requirements.txt`, and `static/script.js` in your existing Flask project. Keep your existing `templates/index.html`, `templates/compare.html`, `templates/favorites.html`, and `static/style.css` unchanged. This starter does not include those HTML/CSS files.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set environment variables locally (replace placeholders in your own terminal; never commit passwords):

```bash
export DB_HOST="YOUR_CLOUD_SQL_PUBLIC_IP_OR_HOST"
export DB_USER="YOUR_MYSQL_USERNAME"
export DB_PASSWORD="YOUR_MYSQL_PASSWORD"
export DB_NAME="college_explorer"
python app.py
```

Visit `http://127.0.0.1:5000/api/health` to check connectivity, then `http://127.0.0.1:5000/` to load the frontend. Test `http://127.0.0.1:5000/api/universities?name=Illinois` to verify a real search.

**Google Cloud SQL:** Your machine must have an authorized route to the instance (such as an authorized public-IP network, or a properly configured Cloud SQL Auth Proxy). Set `DB_HOST` to `127.0.0.1` when using a proxy forwarding local port 3306. If the instance requires TLS, set `DB_SSL_CA` to the trusted CA certificate path.

The current schema supports university names, program-description filtering, and latest rankings. It **does not** expose university state, tuition, acceptance rate, school size, or postgraduate earnings, so those frontend controls are disabled and the comparison charts do not invent values.

Favorites and comparison choices are stored in browser localStorage by `UNITID` (not in MySQL). The API defaults to the first 100 alphabetical matches and allows up to 200 per request. Production deployments should add authentication, pagination, and rate limiting as appropriate.
