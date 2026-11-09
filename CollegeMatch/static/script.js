// Real database records are loaded through Flask, never from a hardcoded array.
const FAVORITES_KEY = "collegeMatchFavoritesIds";
const COMPARE_KEY = "collegeMatchCompareIds";
const byId = (id) => document.getElementById(id);

function savedIds(key) {
  try {
    const values = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(values) ? values.filter(Number.isInteger) : [];
  } catch {
    return [];
  }
}

function toggleSaved(key, id, limit = Infinity) {
  const values = savedIds(key);
  const next = values.includes(id) ? values.filter((value) => value !== id) : [...values, id];
  if (next.length > limit) {
    alert(`You can compare up to ${limit} universities.`);
    return false;
  }
  localStorage.setItem(key, JSON.stringify(next));
  return true;
}

async function loadUniversities(params = {}) {
  const url = new URL("/api/universities", window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value != null) url.searchParams.set(key, String(value));
  });
  const response = await fetch(url);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Unable to load universities");
  return result;
}

function button(label, onClick) {
  const element = document.createElement("button");
  element.type = "button";
  element.className = "button button-outline";
  element.textContent = label;
  element.addEventListener("click", onClick);
  return element;
}

function universityCard(university, refresh) {
  const card = document.createElement("article");
  card.className = "university-card";
  const title = document.createElement("h3");
  title.textContent = university.name;
  const rank = document.createElement("p");
  rank.className = "meta";
  rank.textContent = university.latest_rank == null
    ? "Ranking not available"
    : `Rank #${university.latest_rank} (${university.rank_year})`;
  card.append(title, rank);
  const favorite = savedIds(FAVORITES_KEY).includes(university.id);
  card.appendChild(button(favorite ? "♥ Saved" : "♡ Save to Favorites", () => {
    toggleSaved(FAVORITES_KEY, university.id);
    refresh();
  }));
  const compared = savedIds(COMPARE_KEY).includes(university.id);
  card.appendChild(button(compared ? "✓ Added to Compare" : "+ Compare", () => {
    if (toggleSaved(COMPARE_KEY, university.id, 3)) refresh();
  }));
  return card;
}

async function renderExplore() {
  const container = byId("university-results");
  if (!container) return;
  const status = byId("results-status");
  status.textContent = "Loading universities from database…";
  try {
    const data = await loadUniversities({
      name: byId("search-input").value.trim(),
      major: byId("major-filter").value,
      limit: 200,
    });
    const sort = byId("sort-select").value;
    if (sort === "name") data.sort((a, b) => a.name.localeCompare(b.name));
    container.replaceChildren(...data.map((university) => universityCard(university, renderExplore)));
    byId("results-count").textContent = `${data.length} University Results`;
    status.textContent = data.length ? "Showing database results (up to 200)." : "No universities found.";
  } catch (error) {
    container.replaceChildren();
    status.textContent = error.message;
  }
}

async function renderFavorites() {
  const container = byId("favorites-list");
  if (!container) return;
  const ids = savedIds(FAVORITES_KEY);
  if (!ids.length) {
    container.textContent = "No favorites saved yet. Explore universities to add some.";
    byId("favorites-count").textContent = "0 saved universities";
    return;
  }
  try {
    const data = await loadUniversities({ ids: ids.join(","), limit: 200 });
    container.replaceChildren(...data.map((university) => universityCard(university, renderFavorites)));
    byId("favorites-count").textContent = `${data.length} saved universities`;
  } catch (error) {
    container.textContent = error.message;
  }
}

async function renderCompare() {
  const selected = byId("selected-universities");
  if (!selected) return;
  const head = byId("comparison-head");
  const body = byId("comparison-body");
  const ids = savedIds(COMPARE_KEY);
  try {
    const data = ids.length ? await loadUniversities({ ids: ids.join(",") }) : [];
    selected.replaceChildren();
    for (const university of data) {
      selected.appendChild(button(`${university.name} ×`, () => {
        toggleSaved(COMPARE_KEY, university.id);
        renderCompare();
      }));
    }
    const header = document.createElement("tr");
    const first = document.createElement("th");
    first.textContent = "Metric";
    header.appendChild(first);
    for (const university of data) {
      const cell = document.createElement("th");
      cell.textContent = university.name;
      header.appendChild(cell);
    }
    head.replaceChildren(header);
    body.replaceChildren();
    const row = document.createElement("tr");
    const label = document.createElement("th");
    label.textContent = "Latest ranking";
    row.appendChild(label);
    for (const university of data) {
      const cell = document.createElement("td");
      cell.textContent = university.latest_rank == null ? "—" : `#${university.latest_rank} (${university.rank_year})`;
      row.appendChild(cell);
    }
    body.appendChild(row);
    if (!data.length) selected.textContent = "No universities selected yet.";
    for (const id of ["earnings-chart", "tuition-chart"]) {
      const chart = byId(id);
      if (chart) chart.textContent = "Not available in the current MySQL schema.";
    }
  } catch (error) {
    selected.textContent = error.message;
  }
}

byId("search-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  renderExplore();
});
byId("filter-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  renderExplore();
});
byId("sort-select")?.addEventListener("change", renderExplore);
byId("filter-form")?.addEventListener("reset", () => setTimeout(renderExplore, 0));

// These filters need data columns not present in the supplied schema.
for (const id of ["tuition-filter", "earnings-filter", "location-filter", "size-filter", "acceptance-filter"]) {
  const control = byId(id);
  if (control) {
    control.disabled = true;
    control.title = "This filter requires additional database columns.";
  }
}
byId("sort-select")?.querySelector('[value="tuition-asc"]')?.remove();
for (const [inputId, outputId, suffix] of [
  ["tuition-filter", "tuition-value", "money"],
  ["earnings-filter", "earnings-value", "money"],
  ["acceptance-filter", "acceptance-value", "percent"],
]) {
  const input = byId(inputId);
  const output = byId(outputId);
  if (input && output) {
    const update = () => { output.textContent = suffix === "money" ? `$${Number(input.value).toLocaleString()}` : `${input.value}%`; };
    input.addEventListener("input", update);
    input.form?.addEventListener("reset", () => setTimeout(update, 0));
    update();
  }
}

byId("add-university")?.addEventListener("click", () => { window.location.href = "/"; });
renderExplore();
renderFavorites();
renderCompare();
