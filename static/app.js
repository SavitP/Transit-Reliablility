// The whole website: fetch JSON from our API and turn it into HTML.
// The part of the URL after "#" says which page to show:
//   #/  (home)   #/route/100001   #/stop/2110   #/worst

const page = document.getElementById("page");
const searchBox = document.getElementById("search");
const results = document.getElementById("results");
let days = 7;

// ---------- helpers ----------

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

// Turn text into safe HTML. Stop names come from outside data; without this, a name
// containing "<script>" would run as code in the visitor's browser.
function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// 50% on time or worse = red, 100% = green, in between = orange/yellow.
function color(pct) {
  if (pct == null) return "var(--empty)";
  const hue = Math.max(0, Math.min(120, (pct - 50) * 2.4));
  return `hsl(${hue}, 65%, 42%)`;
}

const fmtPct = p => (p == null ? "–" : `${Math.round(p)}%`);
const fmtHour = h => (h % 12 || 12) + (h < 12 ? "a" : "p");

// ---------- search ----------

let searchTimer;
searchBox.addEventListener("input", () => {
  clearTimeout(searchTimer);
  // Wait until typing pauses for 250ms, so we don't send a request on every keystroke.
  searchTimer = setTimeout(runSearch, 250);
});

async function runSearch() {
  const q = searchBox.value.trim();
  if (!q) { results.hidden = true; return; }
  const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
  const links = [
    ...data.routes.map(r => `<a href="#/route/${esc(r.route_id)}"><span class="kind">Route</span>
        <b>${esc(r.short_name)}</b> ${esc(r.description)}</a>`),
    ...data.stops.map(s => `<a href="#/stop/${esc(s.stop_id)}"><span class="kind">Stop</span>
        ${esc(s.name)} <small>#${esc(s.stop_id)}</small></a>`),
  ];
  results.innerHTML = links.join("") || `<a>No matches</a>`;
  results.hidden = false;
}

results.addEventListener("click", () => { results.hidden = true; searchBox.value = ""; });
document.addEventListener("click", e => { if (!e.target.closest(".search")) results.hidden = true; });

// ---------- pages ----------

function homePage() {
  page.innerHTML = `
    <h1>How reliable is your bus?</h1>
    <p class="sub">Search for a route or stop above, or see the <a href="#/worst">least reliable routes</a>.
    Every departure is measured from King County Metro's live bus positions.</p>`;
}

function daysPicker() {
  return `<span class="days">${[1, 7, 30].map(d =>
    `<button data-days="${d}" class="${d === days ? "on" : ""}">${d === 1 ? "24 hours" : d + " days"}</button>`
  ).join(" ")}</span>`;
}

function bars(items, label) {
  return `
    <div class="bars">${items.map(i => `
      <div class="bar" title="${esc(label(i))}: ${fmtPct(i.pct_on_time)} on time (${i.departures} departures)">
        <div style="height:${i.pct_on_time ?? 0}%; background:${color(i.pct_on_time)}"></div>
      </div>`).join("")}
    </div>
    <div class="labels">${items.map(i => `<span>${esc(label(i))}</span>`).join("")}</div>`;
}

function grid(cells) {
  const lookup = Object.fromEntries(cells.map(c => [`${c.day}-${c.hour}`, c]));
  const hours = [...Array(24).keys()];
  const rows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(day => `
    <tr><th>${day}</th>${hours.map(h => {
      const c = lookup[`${day}-${h}`];
      return c
        ? `<td style="background:${color(c.pct_on_time)}" title="${day} ${fmtHour(h)}: ${fmtPct(c.pct_on_time)} on time (${c.departures})"></td>`
        : `<td title="${day} ${fmtHour(h)}: no data"></td>`;
    }).join("")}</tr>`).join("");
  return `<div class="scroll"><table class="grid">
    <tr><th></th>${hours.map(h => `<th>${h % 3 === 0 ? fmtHour(h) : ""}</th>`).join("")}</tr>${rows}
  </table></div>`;
}

function reliabilityView(title, subtitle, data) {
  const warning = data.departures < 200
    ? `<p class="warn">Only ${data.departures} departures recorded in this period, so these numbers may not be reliable yet.</p>` : "";
  return `
    <h1>${title}</h1>
    <p class="sub">${subtitle}</p>
    ${daysPicker()}
    ${warning}
    <div class="stats">
      <div class="stat"><b style="color:${color(data.pct_on_time)}">${fmtPct(data.pct_on_time)}</b><span>on time</span></div>
      <div class="stat"><b>${fmtPct(data.pct_late)}</b><span>5+ min late</span></div>
      <div class="stat"><b>${fmtPct(data.pct_early)}</b><span>1+ min early</span></div>
      <div class="stat"><b>${data.median_delay_min ?? "–"} min</b><span>typical delay (median)</span></div>
      <div class="stat"><b>${data.p90_delay_min ?? "–"} min</b><span>bad day (1 in 10 worse)</span></div>
      <div class="stat"><b>${data.departures.toLocaleString()}</b><span>departures measured</span></div>
    </div>
    <h2>On time by hour of day</h2>
    ${bars(data.by_hour, i => (i.hour % 3 === 0 ? fmtHour(i.hour) : ""))}
    <h2>On time by day of week</h2>
    ${bars(data.by_day, i => i.day)}
    <h2>Day × hour</h2>
    ${grid(data.grid)}`;
}

async function routePage(id) {
  const r = await api(`/api/routes/${encodeURIComponent(id)}?days=${days}`);
  page.innerHTML = reliabilityView(`Route ${esc(r.short_name)}`, esc(r.description || ""), r);
}

async function stopPage(id) {
  const s = await api(`/api/stops/${encodeURIComponent(id)}?days=${days}`);
  page.innerHTML = reliabilityView(esc(s.name), `Stop #${esc(s.stop_id)}`, s) + `
    <h2>Routes at this stop</h2>
    <table class="list">
      <tr><th>Route</th><th class="num">Departures</th><th class="num">On time</th></tr>
      ${s.routes.map(r => `<tr>
        <td><a href="#/route/${esc(r.route_id)}">${esc(r.short_name)}</a></td>
        <td class="num">${r.departures}</td>
        <td class="num"><span class="pill" style="background:${color(r.pct_on_time)}">${fmtPct(r.pct_on_time)}</span></td>
      </tr>`).join("")}
    </table>`;
}

async function worstPage() {
  const rows = await api(`/api/worst-routes?days=${days}`);
  page.innerHTML = `
    <h1>Least reliable routes</h1>
    <p class="sub">Routes with at least 100 measured departures, ranked by share of on-time departures.</p>
    ${daysPicker()}
    ${rows.length ? `<table class="list">
      <tr><th>Route</th><th></th><th class="num">On time</th><th class="num">5+ min late</th>
          <th class="num">Average delay</th><th class="num">Departures</th></tr>
      ${rows.map(r => `<tr>
        <td><a href="#/route/${esc(r.route_id)}"><b>${esc(r.short_name)}</b></a></td>
        <td>${esc(r.description || "")}</td>
        <td class="num"><span class="pill" style="background:${color(r.pct_on_time)}">${fmtPct(r.pct_on_time)}</span></td>
        <td class="num">${fmtPct(r.pct_late)}</td>
        <td class="num">${r.avg_delay_min} min</td>
        <td class="num">${r.departures.toLocaleString()}</td>
      </tr>`).join("")}
    </table>` : `<p class="warn">Not enough data yet for this period.</p>`}`;
}

// ---------- router: pick the page from the URL ----------

async function show() {
  const [, kind, id] = location.hash.split("/");
  page.innerHTML = `<p class="sub">Loading…</p>`;
  try {
    if (kind === "route") await routePage(decodeURIComponent(id));
    else if (kind === "stop") await stopPage(decodeURIComponent(id));
    else if (kind === "worst") await worstPage();
    else homePage();
  } catch (err) {
    page.innerHTML = `<p class="warn">Couldn't load this page: ${esc(err.message)}</p>`;
  }
}

page.addEventListener("click", e => {
  const button = e.target.closest("button[data-days]");
  if (button) { days = Number(button.dataset.days); show(); }
});
window.addEventListener("hashchange", show);
show();
