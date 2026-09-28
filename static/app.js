// The whole website: fetch JSON from our API and turn it into HTML.
// The part of the URL after "#" says which page to show:
//   #/  (home)   #/route/100001   #/stop/2110   #/worst   #/alerts   #/alerts/new?route=...

const page = document.getElementById("page");
const searchBox = document.getElementById("search");
const results = document.getElementById("results");
const tip = document.getElementById("tip");
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

const fmtPct = p => (p == null ? "–" : `${Math.round(p)}%`);
const fmtHour = h => (h % 12 || 12) + (h < 12 ? "am" : "pm");
const shortHour = h => (h % 12 || 12) + (h < 12 ? "a" : "p");
const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
const periodName = () => (days === 1 ? "the last 24 hours" : `the last ${days} days`);

function delayPhrase(minutes) {
  if (minutes == null) return "unknown";
  if (Math.abs(minutes) < 0.5) return "right on schedule";
  return minutes > 0 ? `${minutes} minutes late` : `${-minutes} minutes early`;
}

// A route number as it appears on the front of the bus.
const chip = (r, link = true) => link
  ? `<a class="sign chip" href="#/route/${esc(r.route_id)}" aria-label="Route ${esc(r.short_name)}">${esc(r.short_name)}</a>`
  : `<span class="sign chip" aria-hidden="true">${esc(r.short_name)}</span>`;

// ---------- tooltip: one shared element for every chart mark with data-tip ----------

function showTip(target, x, y) {
  tip.innerHTML = target.dataset.tip;
  tip.hidden = false;
  const box = tip.getBoundingClientRect();
  const left = Math.min(window.innerWidth - box.width - 8, Math.max(8, x - box.width / 2));
  const top = y - box.height - 12 < 8 ? y + 18 : y - box.height - 12;
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}
document.addEventListener("pointermove", e => {
  const target = e.target.closest("[data-tip]");
  if (target) showTip(target, e.clientX, e.clientY); else tip.hidden = true;
});
document.addEventListener("focusin", e => {
  const target = e.target.closest("[data-tip]");
  if (!target) return;
  const r = target.getBoundingClientRect();
  showTip(target, r.left + r.width / 2, r.top);
});
document.addEventListener("focusout", () => { tip.hidden = true; });

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
    ...data.routes.map(r => `<a href="#/route/${esc(r.route_id)}">${chip(r, false)}
        <span>${esc(r.description || `Route ${r.short_name}`)}</span></a>`),
    ...data.stops.map(s => `<a href="#/stop/${esc(s.stop_id)}"><span class="stop-mark">Stop</span>
        <span>${esc(s.name)} <small>${esc(s.stop_id)}</small></span></a>`),
  ];
  results.innerHTML = links.join("") ||
    `<p class="empty">No route or stop matches “${esc(q)}”. Try a route number or a street name.</p>`;
  results.hidden = false;
}

results.addEventListener("click", e => {
  if (e.target.closest("a")) { results.hidden = true; searchBox.value = ""; }
});
document.addEventListener("click", e => { if (!e.target.closest(".search")) results.hidden = true; });
searchBox.addEventListener("keydown", e => { if (e.key === "Escape") results.hidden = true; });

// ---------- shared pieces ----------

function periodPicker() {
  return `<div class="period">
    <span id="period-label">Showing the last</span>
    <div class="segmented" role="group" aria-labelledby="period-label">${[1, 7, 30].map(d =>
      `<button type="button" data-days="${d}" aria-pressed="${d === days}">${d === 1 ? "24 hours" : `${d} days`}</button>`
    ).join("")}</div></div>`;
}

function verdict(data, what) {
  const net = data.network_pct_on_time;
  let comparison = "";
  if (net != null && data.pct_on_time != null) {
    const gap = Math.round(data.pct_on_time - net);
    comparison = Math.abs(gap) < 3
      ? `That's about the same as Metro overall (${fmtPct(net)}).`
      : `Metro overall: ${fmtPct(net)}, so this ${what} is ${Math.abs(gap)} points ${gap < 0 ? "worse" : "better"}.`;
  }
  return `
    <div class="verdict">
      <div><span class="figure">${fmtPct(data.pct_on_time)}</span><span class="figure-label">on time</span></div>
      <p>${comparison} The typical departure is ${delayPhrase(data.median_delay_min)};
        one in ten is more than ${delayPhrase(data.p90_delay_min)}.
        Based on ${plural(data.departures, "departure")} in ${periodName()}.</p>
    </div>
    <div class="split">
      <div class="bar" role="img" aria-label="${fmtPct(data.pct_early)} early, ${fmtPct(data.pct_on_time)} on time, ${fmtPct(data.pct_late)} 5 or more minutes late">
        ${[["early", data.pct_early, "left more than 1 minute early"],
           ["on-time", data.pct_on_time, "on time"],
           ["late", data.pct_late, "5 or more minutes late"]].map(([key, pct, label]) => pct ? `
          <span style="flex:${pct}; background:var(--${key})" data-tip="<b>${fmtPct(pct)}</b> ${label}"></span>` : "").join("")}
      </div>
      <div class="keys">
        <span><i class="swatch" style="background:var(--early)"></i><b>${fmtPct(data.pct_early)}</b> early</span>
        <span><i class="swatch" style="background:var(--on-time)"></i><b>${fmtPct(data.pct_on_time)}</b> on time</span>
        <span><i class="swatch" style="background:var(--late)"></i><b>${fmtPct(data.pct_late)}</b> 5+ minutes late</span>
      </div>
    </div>`;
}

// Column chart of on-time % (one hue; the height carries the value), with Metro-wide as a dashed line.
function columns(items, label, tipTitle, net, extraClass = "") {
  return `
    ${net != null ? `<div class="chart-key"><span class="dash"></span>Metro overall, ${fmtPct(net)} on time</div>` : ""}
    <div class="chart ${extraClass}">
      <div class="plot">
        <div class="gridline" style="top:0"><span>100%</span></div>
        <div class="gridline" style="top:50%"><span>50%</span></div>
        <div class="cols">${items.map(i => `
          <div class="col ${i.departures ? "" : "none"}" data-tip="${esc(i.departures
              ? `<b>${tipTitle(i)}</b><br>${fmtPct(i.pct_on_time)} on time<br>${plural(i.departures, "departure")}`
              : `<b>${tipTitle(i)}</b><br>No departures measured`)}">
            <i style="height:${i.pct_on_time ?? 0}%"></i></div>`).join("")}
        </div>
        ${net != null ? `<div class="refline" style="bottom:${net}%"></div>` : ""}
      </div>
      <div class="xlabels">${items.map(i => `<span>${label(i)}</span>`).join("")}</div>
    </div>`;
}

// Day × hour grid, colored by how each hour compares with Metro overall.
// Diverging scale: blue = better, red = worse, gray midpoint = about the same.
const COMPARE_STEPS = [
  { max: -15, css: "var(--worse-2)", label: "15+ points worse" },
  { max: -5, css: "var(--worse-1)", label: "5–15 points worse" },
  { max: 5, css: "var(--neutral)", label: "About the same" },
  { max: 15, css: "var(--better-1)", label: "5–15 points better" },
  { max: Infinity, css: "var(--better-2)", label: "15+ points better" },
];
const compareStep = diff => COMPARE_STEPS.find(s => diff < s.max) ?? COMPARE_STEPS[4];

function grid(cells, net) {
  const baseline = net ?? 75;
  const lookup = Object.fromEntries(cells.map(c => [`${c.day}-${c.hour}`, c]));
  const hours = [...Array(24).keys()];
  const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const rows = dayNames.map(day => `
    <tr><th scope="row">${day}</th>${hours.map(h => {
      const c = lookup[`${day}-${h}`];
      if (!c) return `<td></td>`;
      return `<td class="has" style="background:${compareStep(c.pct_on_time - baseline).css}"
        data-tip="${esc(`<b>${day} ${fmtHour(h)}</b><br>${fmtPct(c.pct_on_time)} on time<br>${plural(c.departures, "departure")}`)}"></td>`;
    }).join("")}</tr>`).join("");
  const tableRows = cells.slice()
    .sort((a, b) => dayNames.indexOf(a.day) - dayNames.indexOf(b.day) || a.hour - b.hour)
    .map(c => `<tr><td>${c.day}</td><td>${fmtHour(c.hour)}</td><td class="num">${c.departures}</td>
               <td class="num">${fmtPct(c.pct_on_time)}</td></tr>`).join("");
  return `
    <p class="note">Each square is one hour of one weekday, compared with Metro overall
      (${fmtPct(baseline)} on time${net == null ? ", a typical figure while data builds up" : ""}).</p>
    <div class="scroll"><table class="grid">
      <thead><tr><th></th>${hours.map(h => `<th>${h % 3 === 0 ? shortHour(h) : ""}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="legend">${COMPARE_STEPS.map(s =>
      `<span><i class="swatch" style="background:${s.css}"></i>${s.label}</span>`).join("")}
      <span><i class="swatch" style="background:var(--track)"></i>No data</span></div>
    <details class="table-view"><summary>Show these numbers as a table</summary>
      <table class="list"><thead><tr><th>Day</th><th>Hour</th><th class="num">Departures</th><th class="num">On time</th></tr></thead>
      <tbody>${tableRows}</tbody></table></details>`;
}

function meter(pct, net) {
  return `<div class="meter"><div class="track">
      <div class="fill" style="width:${pct ?? 0}%"></div>
      ${net != null ? `<div class="tick" style="left:${net}%"></div>` : ""}
    </div><b>${fmtPct(pct)}</b></div>`;
}

function reliabilityView(data, what) {
  const warning = data.departures < 200
    ? `<p class="warn">Only ${plural(data.departures, "departure")} measured in ${periodName()}.
        These numbers will settle as more buses are measured.</p>` : "";
  const net = data.network_pct_on_time;
  return `
    ${periodPicker()}
    ${warning}
    ${data.departures ? `
      ${verdict(data, what)}
      <h2>By time of day</h2>
      ${columns(data.by_hour, i => (i.hour % 3 === 0 ? shortHour(i.hour) : ""), i => fmtHour(i.hour), net, "hours")}
      <h2>By day of the week</h2>
      ${columns(data.by_day, i => i.day, i => i.day, net, "hours")}
      <h2>Every hour of the week</h2>
      ${grid(data.grid, net)}` : ""}`;
}

// ---------- pages ----------

let heroTimer;

async function homePage() {
  page.innerHTML = `
    <a class="hero-sign" id="hero-sign" href="#/worst" aria-live="off">
      <span class="line1"><span class="num">&nbsp;</span><span class="dest">Loading</span></span>
      <span class="line2">&nbsp;</span>
    </a>
    <p class="hero-caption" id="hero-caption"></p>
    <h1>How reliable is your bus?</h1>
    <p class="lede">On-time records for every King County Metro route and stop, built from the
      live position of every bus. Search above, or start with the routes that are struggling today.</p>
    <h2>Least on time in the last 24 hours</h2>
    <div id="today"><p class="note">Loading…</p></div>
    <div class="cta">
      <p>Want to know before you leave? Get a phone alert when your bus is running late.</p>
      <a class="button" href="#/alerts">Set up a commute alert</a>
    </div>`;

  let routes = await api("/api/worst-routes?days=1&limit=8");
  let period = "today";
  if (!routes.length) { routes = await api("/api/worst-routes?days=7&limit=8"); period = "this week"; }
  const net = (await api("/api/network?days=1")).pct_on_time;

  document.getElementById("today").innerHTML = routes.length ? `
    <table class="list">
      <thead><tr><th>Route</th><th class="wide">Where it goes</th><th>On time</th><th class="num">5+ min late</th></tr></thead>
      <tbody>${routes.slice(0, 5).map(r => `<tr>
        <td>${chip(r)}</td><td class="desc wide">${esc(r.description || "")}</td>
        <td>${meter(r.pct_on_time, net)}</td><td class="num">${fmtPct(r.pct_late)}</td></tr>`).join("")}
      </tbody></table>
    <p class="note">${net != null ? `The small mark on each bar is Metro overall (${fmtPct(net)}). ` : ""}
      <a href="#/worst">See all routes, ranked</a></p>`
    : `<p class="note">Not enough departures measured yet. Check back in an hour.</p>`;

  startHeroSign(routes, period);
}

function startHeroSign(routes, period) {
  const sign = document.getElementById("hero-sign");
  const caption = document.getElementById("hero-caption");
  if (!sign) return;
  if (!routes.length) {
    sign.querySelector(".dest").textContent = "Measuring buses";
    return;
  }
  let index = 0, paused = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const draw = () => {
    const r = routes[index];
    sign.href = `#/route/${r.route_id}`;
    sign.setAttribute("aria-label", `Route ${r.short_name}, ${r.description || ""}: ${fmtPct(r.pct_on_time)} on time ${period}`);
    sign.innerHTML = `
      <span class="line1"><span class="num">${esc(r.short_name)}</span><span class="dest">${esc(r.description || "")}</span></span>
      <span class="line2">${fmtPct(r.pct_on_time)} on time ${period}</span>`;
    sign.classList.remove("flip"); void sign.offsetWidth; sign.classList.add("flip");
  };
  const renderCaption = () => {
    caption.innerHTML = `Showing the ${routes.length} least on-time routes ${period}.
      <button type="button" id="hero-toggle">${paused ? "Play" : "Pause"}</button>`;
    document.getElementById("hero-toggle").addEventListener("click", () => {
      paused = !paused; renderCaption(); schedule();
    });
  };
  const schedule = () => {
    clearInterval(heroTimer);
    if (!paused) heroTimer = setInterval(() => {
      if (!document.body.contains(sign)) return clearInterval(heroTimer);
      index = (index + 1) % routes.length; draw();
    }, 4500);
  };
  draw(); renderCaption(); schedule();
}

async function routePage(id) {
  const r = await api(`/api/routes/${encodeURIComponent(id)}?days=${days}`);
  page.innerHTML = `
    <h1 class="sign plate" aria-label="Route ${esc(r.short_name)}: ${esc(r.description || "")}">
      <span class="num">${esc(r.short_name)}</span><span class="dest">${esc(r.description || "")}</span></h1>
    ${reliabilityView(r, "route")}
    <div class="cta">
      <p>Ride Route ${esc(r.short_name)}? Get a phone alert when it's running late at your stop.</p>
      <a class="button" href="#/alerts/new?route=${esc(r.route_id)}">Set up an alert for Route ${esc(r.short_name)}</a>
    </div>`;
}

async function stopPage(id) {
  const s = await api(`/api/stops/${encodeURIComponent(id)}?days=${days}`);
  page.innerHTML = `
    <h1>${esc(s.name)}</h1>
    <p class="lede">Stop ${esc(s.stop_id)}. Every route that stops here, combined.</p>
    ${reliabilityView(s, "stop")}
    ${s.routes.length ? `<h2>Each route at this stop</h2>
      <table class="list">
        <thead><tr><th>Route</th><th>On time here</th><th class="num wide">Departures</th></tr></thead>
        <tbody>${s.routes.map(r => `<tr>
          <td>${chip(r)}</td><td>${meter(r.pct_on_time, s.network_pct_on_time)}</td>
          <td class="num wide">${r.departures.toLocaleString()}</td></tr>`).join("")}</tbody>
      </table>` : ""}
    <div class="cta">
      <p>Catch a bus here? Get a phone alert when it's running late.</p>
      <a class="button" href="#/alerts/new?stop=${esc(s.stop_id)}">Set up an alert at this stop</a>
    </div>`;
}

async function worstPage() {
  const [rows, network] = await Promise.all([api(`/api/worst-routes?days=${days}`), api(`/api/network?days=${days}`)]);
  const net = network.pct_on_time;
  page.innerHTML = `
    <h1>Least reliable routes</h1>
    <p class="lede">Routes ranked by the share of departures that were on time.
      Only routes with at least 100 measured departures are included.</p>
    ${periodPicker()}
    ${rows.length ? `<table class="list">
      <thead><tr><th>Route</th><th class="wide">Where it goes</th><th>On time</th>
        <th class="num">5+ min late</th><th class="num wide">Average delay</th><th class="num wide">Departures</th></tr></thead>
      <tbody>${rows.map(r => `<tr>
        <td>${chip(r)}</td>
        <td class="desc wide">${esc(r.description || "")}</td>
        <td>${meter(r.pct_on_time, net)}</td>
        <td class="num">${fmtPct(r.pct_late)}</td>
        <td class="num wide">${r.avg_delay_min} min</td>
        <td class="num wide">${Number(r.departures).toLocaleString()}</td>
      </tr>`).join("")}</tbody></table>
      ${net != null ? `<p class="note">The small mark on each bar is Metro overall: ${fmtPct(net)} on time.</p>` : ""}`
    : `<p class="warn">Not enough departures measured in ${periodName()} yet. Try a longer period.</p>`}`;
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
function clockTime(t) {                     // "07:30:00" -> "7:30am"
  const [h, m] = t.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")}${h < 12 ? "am" : "pm"}`;
}

async function myAlertsPage() {
  const ids = myAlertIds();
  const subs = await Promise.all(ids.map(id => api(`/api/subscriptions/${id}`).catch(() => null)));
  saveAlertIds(ids.filter((id, i) => subs[i]));            // forget alerts deleted elsewhere
  const live = subs.filter(Boolean);
  page.innerHTML = `
    <h1>Commute alerts</h1>
    <p class="lede">Get a notification on your phone when your bus is running late, while it's
      still a few stops away. Free, and no account needed.</p>
    ${live.length ? `<h2>Your alerts</h2><table class="list">
      <thead><tr><th>Route</th><th>Stop</th><th class="wide">When</th><th class="num">Alert at</th></tr></thead>
      <tbody>${live.map(s => `<tr>
        <td>${chip({ route_id: s.route_id, short_name: s.route_name }, false)}</td>
        <td><a href="#/alerts/${esc(s.id)}">${esc(s.stop_name)}</a></td>
        <td class="wide">${describeDays(s.days)}, ${clockTime(s.window_start)} to ${clockTime(s.window_end)}</td>
        <td class="num">${s.threshold_minutes}+ min late</td>
      </tr>`).join("")}</tbody></table>`
      : `<p class="note">You haven't set up any alerts in this browser yet.</p>`}
    <h2>Set up a new alert</h2>
    <p>Find your route or stop with the search box above, then choose
      <b>Set up an alert</b> at the bottom of its page.</p>`;
}

async function newAlertPage(params) {
  const routeId = params.get("route"), stopId = params.get("stop");
  let routeChoice, stopChoice;
  if (stopId) {           // coming from a stop page: pick which route
    const [stop, routes] = await Promise.all([api(`/api/stops/${encodeURIComponent(stopId)}?days=1`),
                                             api(`/api/stops/${encodeURIComponent(stopId)}/routes`)]);
    stopChoice = `<input type="hidden" name="stop_id" value="${esc(stopId)}"><b>${esc(stop.name)}</b>`;
    routeChoice = `<select name="route_id" required>${routes.map(r =>
      `<option value="${esc(r.route_id)}">${esc(r.short_name)}: ${esc(r.description || "")}</option>`).join("")}</select>`;
  } else {                // coming from a route page: pick which stop
    const [route, stops] = await Promise.all([api(`/api/routes/${encodeURIComponent(routeId)}?days=1`),
                                             api(`/api/routes/${encodeURIComponent(routeId)}/stops`)]);
    routeChoice = `<input type="hidden" name="route_id" value="${esc(routeId)}">${chip(route, false)}
      <span class="desc">${esc(route.description || "")}</span>`;
    stopChoice = `<select name="stop_id" required><option value="">Choose your stop</option>${stops.map(s =>
      `<option value="${esc(s.stop_id)}">${esc(s.name)} (${esc(s.stop_id)})</option>`).join("")}</select>`;
  }
  page.innerHTML = `
    <h1>New commute alert</h1>
    <p class="lede">We'll tell you when the bus is running late, judged from where it is right now,
      so you hear before it reaches your stop.</p>
    <form id="alert-form" class="form">
      <div class="field"><span>Route</span><div>${routeChoice}</div></div>
      <label class="field"><span>Your stop</span>${stopChoice}</label>
      <fieldset><legend>Days you ride</legend><div class="days-choice">${WEEKDAYS.map((d, i) =>
        `<label><input type="checkbox" name="days" value="${i + 1}" ${i < 5 ? "checked" : ""}><span>${d}</span></label>`).join("")}
      </div></fieldset>
      <div class="field"><span>When the bus is due at your stop</span>
        <div class="times"><label>From <input type="time" name="window_start" value="07:00" required></label>
        <label>to <input type="time" name="window_end" value="09:00" required></label></div></div>
      <label class="field"><span>Alert me when it's at least</span>
        <select name="threshold_minutes">${[5, 10, 15, 20].map(m =>
          `<option value="${m}" ${m === 10 ? "selected" : ""}>${m} minutes late</option>`).join("")}</select></label>
      <p id="form-error" class="warn" role="alert" hidden></p>
      <div><button type="submit" class="button">Create alert</button></div>
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
      error.textContent = `Couldn't create the alert: ${err.message}.`;
      error.hidden = false;
    }
  });
}

async function alertPage(id, params) {
  const s = await api(`/api/subscriptions/${encodeURIComponent(id)}`);
  if (!myAlertIds().includes(s.id)) saveAlertIds([...myAlertIds(), s.id]);   // opened via saved link
  page.innerHTML = `
    <h1>Route ${esc(s.route_name)} at ${esc(s.stop_name)}</h1>
    <p class="lede">${describeDays(s.days)}, for buses due between ${clockTime(s.window_start)} and
      ${clockTime(s.window_end)}. You'll hear when one is ${s.threshold_minutes} or more minutes late.</p>
    ${params.get("new") ? `<p class="ok">Alert created. Two steps to get it on your phone:</p>` : ""}
    <ol class="steps">
      <li>Install the free ntfy app for
        <a href="https://apps.apple.com/app/ntfy/id1625396347">iPhone</a> or
        <a href="https://play.google.com/store/apps/details?id=io.heckel.ntfy">Android</a>.</li>
      <li>In the app, tap <b>+</b> and subscribe to this topic:
        <code class="topic">${esc(s.topic)}</code>
        <button type="button" class="small" data-copy="${esc(s.topic)}">Copy topic</button>
        <br><span class="note">No phone handy? Open <a href="${esc(s.ntfy_url)}">${esc(s.ntfy_url)}</a> in a browser.</span></li>
      <li><button type="button" class="button" id="test-alert">Send a test notification</button>
        <span id="test-result" class="note" role="status"></span></li>
    </ol>
    <p class="note">Bookmark this page. Its address is the only way to change or delete this alert,
      and it's also listed under <a href="#/alerts">My alerts</a> in this browser.
      Keep the topic private: anyone who has it can read these notifications.</p>
    <h2>Recent notifications</h2>
    ${s.recent_alerts.length ? `<table class="list"><tbody>${s.recent_alerts.map(a => `<tr>
        <td class="wide">${new Date(a.created_at).toLocaleString()}</td>
        <td><b>${esc(a.title)}</b><br><span class="desc">${esc(a.message)}</span></td>
        <td class="num">${esc(a.status)}</td></tr>`).join("")}</tbody></table>`
      : `<p class="note">None yet. They'll appear here when a bus runs late in your window.</p>`}
    <p style="margin-top:40px"><button type="button" class="danger" id="delete-alert">Delete this alert</button>
       <span id="confirm-delete" hidden>This can't be undone.
         <button type="button" class="danger" id="really-delete">Delete it</button></span></p>`;

  document.getElementById("test-alert").addEventListener("click", async () => {
    const result = document.getElementById("test-result");
    try {
      await send("POST", `/api/subscriptions/${s.id}/test`);
      result.textContent = "Test sent. It should arrive within a few seconds.";
    } catch (err) {
      result.textContent = `Couldn't send the test: ${err.message}.`;
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
  catch { copy.textContent = "Select the topic and copy it"; }
});

// ---------- router: pick the page from the URL ----------

async function show() {
  // "#/alerts/new?route=100001" -> path parts ["", "alerts", "new"], params route=100001
  const [path, query = ""] = location.hash.slice(1).split("?");
  const [, kind, id] = path.split("/");
  const params = new URLSearchParams(query);
  clearInterval(heroTimer);
  tip.hidden = true;
  document.querySelectorAll(".masthead nav a").forEach(a => {
    if (a.getAttribute("href") === `#/${kind}`) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  page.innerHTML = `<p class="note">Loading…</p>`;
  try {
    if (kind === "route") await routePage(decodeURIComponent(id));
    else if (kind === "stop") await stopPage(decodeURIComponent(id));
    else if (kind === "worst") await worstPage();
    else if (kind === "alerts" && id === "new") await newAlertPage(params);
    else if (kind === "alerts" && id) await alertPage(decodeURIComponent(id), params);
    else if (kind === "alerts") await myAlertsPage();
    else await homePage();
  } catch (err) {
    page.innerHTML = `<h1>This page didn't load</h1>
      <p class="warn">The server answered: ${esc(err.message)}. Check the address, or go back to the
      <a href="#/">start page</a>.</p>`;
  }
}

page.addEventListener("click", e => {
  const button = e.target.closest("button[data-days]");
  if (button) { days = Number(button.dataset.days); show(); }
});
window.addEventListener("hashchange", show);
show();
