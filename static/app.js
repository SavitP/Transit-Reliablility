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
  page.innerHTML = reliabilityView(`Route ${esc(r.short_name)}`, esc(r.description || ""), r)
    + `<p><a class="button" href="#/alerts/new?route=${esc(r.route_id)}">🔔 Alert me when this route is late</a></p>`;
}

async function stopPage(id) {
  const s = await api(`/api/stops/${encodeURIComponent(id)}?days=${days}`);
  page.innerHTML = reliabilityView(esc(s.name), `Stop #${esc(s.stop_id)}`, s) + `
    <p><a class="button" href="#/alerts/new?stop=${esc(s.stop_id)}">🔔 Alert me when my bus here is late</a></p>
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

// ---------- commute alerts ----------
// There are no accounts. Each alert has a secret id; we remember the ids this browser
// created in localStorage (a small storage area each website gets in the browser).

function myAlertIds() {
  try { return JSON.parse(localStorage.getItem("alerts") || "[]"); } catch { return []; }
}
function saveAlertIds(ids) {
  try { localStorage.setItem("alerts", JSON.stringify(ids)); } catch { /* private browsing: fine */ }
}

// Like api(), but for sending data (POST/DELETE) and showing the server's error message.
async function send(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    const detail = Array.isArray(problem.detail)            // FastAPI validation errors are a list
      ? problem.detail.map(d => d.msg.replace(/^Value error, /, "")).join("; ")
      : problem.detail;
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.status === 204 ? null : response.json();
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const describeDays = d => d.join() === "1,2,3,4,5" ? "Weekdays" : d.join() === "6,7" ? "Weekends"
  : d.length === 7 ? "Every day" : d.map(n => WEEKDAYS[n - 1]).join(", ");
const shortTime = t => t.slice(0, 5);

async function myAlertsPage() {
  const ids = myAlertIds();
  const subs = (await Promise.all(ids.map(id => api(`/api/subscriptions/${id}`).catch(() => null))));
  saveAlertIds(ids.filter((id, i) => subs[i]));            // forget alerts deleted elsewhere
  const live = subs.filter(Boolean);
  page.innerHTML = `
    <h1>My alerts</h1>
    <p class="sub">Get a phone notification when your bus is running late, before you head out.
      Start from a <a href="#/">route or stop page</a>.</p>
    ${live.length ? `<table class="list">
      <tr><th>Route</th><th>Stop</th><th>When</th><th class="num">Late by</th></tr>
      ${live.map(s => `<tr>
        <td><a href="#/alerts/${esc(s.id)}"><b>${esc(s.route_name)}</b></a></td>
        <td>${esc(s.stop_name)}</td>
        <td>${describeDays(s.days)} ${shortTime(s.window_start)}–${shortTime(s.window_end)}</td>
        <td class="num">${s.threshold_minutes}+ min</td>
      </tr>`).join("")}</table>`
      : `<p class="warn">No alerts saved in this browser yet.</p>`}`;
}

async function newAlertPage(params) {
  const routeId = params.get("route"), stopId = params.get("stop");
  let routeChoice, stopChoice;
  if (stopId) {           // coming from a stop page: pick which route
    const [stop, routes] = await Promise.all([api(`/api/stops/${encodeURIComponent(stopId)}`),
                                             api(`/api/stops/${encodeURIComponent(stopId)}/routes`)]);
    stopChoice = `<input type="hidden" name="stop_id" value="${esc(stopId)}"><b>${esc(stop.name)}</b>`;
    routeChoice = `<select name="route_id" required>${routes.map(r =>
      `<option value="${esc(r.route_id)}">${esc(r.short_name)}: ${esc(r.description || "")}</option>`).join("")}</select>`;
  } else {                // coming from a route page: pick which stop
    const [route, stops] = await Promise.all([api(`/api/routes/${encodeURIComponent(routeId)}`),
                                             api(`/api/routes/${encodeURIComponent(routeId)}/stops`)]);
    routeChoice = `<input type="hidden" name="route_id" value="${esc(routeId)}"><b>Route ${esc(route.short_name)}</b>`;
    stopChoice = `<select name="stop_id" required><option value="">Choose your stop…</option>${stops.map(s =>
      `<option value="${esc(s.stop_id)}">${esc(s.name)} (#${esc(s.stop_id)})</option>`).join("")}</select>`;
  }
  page.innerHTML = `
    <h1>New commute alert</h1>
    <p class="sub">We'll notify your phone when the bus is running late at your stop,
      judged from where it is right now, so you hear before it arrives.</p>
    <form id="alert-form" class="form">
      <label>Route ${routeChoice}</label>
      <label>Your stop ${stopChoice}</label>
      <fieldset><legend>Days</legend>${WEEKDAYS.map((d, i) =>
        `<label class="inline"><input type="checkbox" name="days" value="${i + 1}" ${i < 5 ? "checked" : ""}> ${d}</label>`).join("")}
      </fieldset>
      <label>When the bus is due at your stop, between
        <span class="inline"><input type="time" name="window_start" value="07:00" required>
        and <input type="time" name="window_end" value="09:00" required></span></label>
      <label>Alert me if it's at least
        <select name="threshold_minutes">${[5, 10, 15, 20].map(m =>
          `<option value="${m}" ${m === 10 ? "selected" : ""}>${m} minutes late</option>`).join("")}</select></label>
      <p id="form-error" class="warn" hidden></p>
      <button type="submit" class="button">Create alert</button>
    </form>`;

  document.getElementById("alert-form").addEventListener("submit", async e => {
    e.preventDefault();                          // handle it here instead of reloading the page
    const f = new FormData(e.target);
    const error = document.getElementById("form-error");
    try {
      const sub = await send("POST", "/api/subscriptions", {
        route_id: f.get("route_id"), stop_id: f.get("stop_id"),
        days: f.getAll("days").map(Number),
        window_start: f.get("window_start"), window_end: f.get("window_end"),
        threshold_minutes: Number(f.get("threshold_minutes")),
      });
      saveAlertIds([...myAlertIds(), sub.id]);
      location.hash = `#/alerts/${sub.id}?new=1`;
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  });
}

async function alertPage(id, params) {
  const s = await api(`/api/subscriptions/${encodeURIComponent(id)}`);
  if (!myAlertIds().includes(s.id)) saveAlertIds([...myAlertIds(), s.id]);   // opened via saved link
  page.innerHTML = `
    <h1>Route ${esc(s.route_name)} at ${esc(s.stop_name)}</h1>
    <p class="sub">${describeDays(s.days)}, bus due ${shortTime(s.window_start)}–${shortTime(s.window_end)},
      alert when ${s.threshold_minutes}+ minutes late.</p>
    ${params.get("new") ? `<p class="ok">Alert created. Two quick steps to get it on your phone:</p>` : ""}
    <ol class="steps">
      <li>Install the free <b>ntfy</b> app
        (<a href="https://apps.apple.com/app/ntfy/id1625396347">iPhone</a> ·
        <a href="https://play.google.com/store/apps/details?id=io.heckel.ntfy">Android</a>).</li>
      <li>In the app, tap <b>+</b> and subscribe to this topic:
        <code class="topic">${esc(s.topic)}</code>
        <button type="button" class="small" data-copy="${esc(s.topic)}">Copy</button>
        <br><small>Or open <a href="${esc(s.ntfy_url)}">${esc(s.ntfy_url)}</a> in a browser.</small></li>
      <li><button type="button" class="button" id="test-alert">Send me a test notification</button>
        <span id="test-result" class="sub"></span></li>
    </ol>
    <p class="sub">Bookmark this page: its address is the only way to manage this alert
      (it's also saved under <a href="#/alerts">My alerts</a> in this browser). Keep the topic
      private: anyone who knows it can read these notifications.</p>
    <h2>Recent notifications</h2>
    ${s.recent_alerts.length ? `<table class="list">${s.recent_alerts.map(a => `<tr>
        <td>${new Date(a.created_at).toLocaleString()}</td><td><b>${esc(a.title)}</b><br>${esc(a.message)}</td>
        <td>${esc(a.status)}</td></tr>`).join("")}</table>` : `<p class="sub">None yet.</p>`}
    <p><button type="button" class="danger" id="delete-alert">Delete this alert</button>
       <span id="confirm-delete" hidden>Sure? <button type="button" class="danger" id="really-delete">Yes, delete</button></span></p>`;

  document.getElementById("test-alert").addEventListener("click", async () => {
    const result = document.getElementById("test-result");
    try {
      await send("POST", `/api/subscriptions/${s.id}/test`);
      result.textContent = "Sent. It should arrive within a few seconds.";
    } catch (err) {
      result.textContent = err.message;
    }
  });
  // Two-step delete instead of a confirm() pop-up.
  document.getElementById("delete-alert").addEventListener("click", () => {
    document.getElementById("confirm-delete").hidden = false;
  });
  document.getElementById("really-delete").addEventListener("click", async () => {
    await send("DELETE", `/api/subscriptions/${s.id}`);
    saveAlertIds(myAlertIds().filter(x => x !== s.id));
    location.hash = "#/alerts";
  });
}

page.addEventListener("click", async e => {
  const copy = e.target.closest("button[data-copy]");
  if (!copy) return;
  try { await navigator.clipboard.writeText(copy.dataset.copy); copy.textContent = "Copied"; }
  catch { copy.textContent = "Select and copy it manually"; }
});

// ---------- router: pick the page from the URL ----------

async function show() {
  // "#/alerts/new?route=100001" -> path parts ["", "alerts", "new"], params route=100001
  const [path, query = ""] = location.hash.slice(1).split("?");
  const [, kind, id] = path.split("/");
  const params = new URLSearchParams(query);
  page.innerHTML = `<p class="sub">Loading…</p>`;
  try {
    if (kind === "route") await routePage(decodeURIComponent(id));
    else if (kind === "stop") await stopPage(decodeURIComponent(id));
    else if (kind === "worst") await worstPage();
    else if (kind === "alerts" && id === "new") await newAlertPage(params);
    else if (kind === "alerts" && id) await alertPage(decodeURIComponent(id), params);
    else if (kind === "alerts") await myAlertsPage();
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
