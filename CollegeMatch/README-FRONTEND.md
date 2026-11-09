# CollegeMatch Frontend Starter

Based on the team's Explore, Compare, and Favorites mockups.

## Files
- `templates/index.html`: Explore/search/filter layout (Checkpoint 1 priority)
- `templates/compare.html`: comparison table and chart placeholders
- `templates/favorites.html`: favorites list placeholder
- `static/style.css`: shared responsive styling
- `static/script.js`: minimal JavaScript starter, NOT database integration

## Run locally with Flask
Ask the backend teammate to serve these pages with Flask:

```python
from flask import Flask, render_template
app = Flask(__name__)

@app.get('/')
def explore():
    return render_template('index.html')

@app.get('/compare')
def compare():
    return render_template('compare.html')

@app.get('/favorites')
def favorites():
    return render_template('favorites.html')
```

These route examples should be integrated into the team's existing Flask app, not replace it.

## Preview without Flask
From the project root:

```bash
python3 -m http.server 8000
```

Open `http://localhost:8000/templates/index.html` (and `compare.html` / `favorites.html`).
Note: navigation links `/`, `/compare`, and `/favorites` require Flask routes; they won't work as intended in the static preview.

## Integration contract to confirm with backend
- `GET /api/universities?name=...` for university retrieval.
- Agree on the returned JSON fields before implementing card rendering.
- IDs: `search-form`, `search-input`, `search-button`, `filter-form`, `university-results`, `results-count`, `results-status`, `sort-select`.
- Do not show invented university metrics as real data. The Explore results area is empty until the API is connected.
- Compare and Favorites are structural placeholders, not completed CRUD features.

## Checkpoint 1
Ensure at least one real retrieval operation is demonstrated in the browser. Commit and release with the exact tag `stage.4.1`.
