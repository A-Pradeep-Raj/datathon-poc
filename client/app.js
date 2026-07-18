/* ============================================================
   KSP Crime Intelligence AI – Frontend Application
   Handles: Chat, Charts, Network, Heatmap, PDF Export, Voice
   ============================================================ */

// ── Config ────────────────────────────────────────────────────────────────
// Backend Advanced I/O function absolute URL (used when frontend is hosted on
// a different domain, e.g. Catalyst Slate at onslate.in).
const CATALYST_FUNCTION_URL = "https://krime-ai-60078097690.development.catalystserverless.in/server/crime-chat-function";

const API_BASE = window.location.hostname === "localhost"
  ? "http://localhost:3000"
  : window.location.hostname.endsWith("catalystserverless.in")
    ? "/server/crime-chat-function"   // same-origin Catalyst Web Client hosting
    : CATALYST_FUNCTION_URL;          // cross-origin hosting (e.g. Slate)

const DEFAULT_SUGGESTIONS = [
  "How many total crimes are registered in Karnataka?",
  "Show crimes by district",
  "Which crime type is most common?",
  "Show crime trend from 2019 to 2025",
  "Top crime hotspot stations",
  "ಬೆಂಗಳೂರಿನಲ್ಲಿ ಎಷ್ಟು ಅಪರಾಧಗಳಾಗಿವೆ?",
  "How many accused are still wanted?",
  "Show case status breakdown",
];

// ── State ─────────────────────────────────────────────────────────────────
let currentLang = "en";
let conversation = [];       // { role, content, timestamp }
let auditLog = [];           // { query, intents, sql, count, ts }
let currentChartInstance = null;
let isRecording = false;
let mediaRecognition = null;
let networkInstance = null;
let currentTabId = "chat";
let dbCharts = {};           // chart.js instances keyed by canvas id
let sessionId = "session_" + Date.now();

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  renderSuggestions(DEFAULT_SUGGESTIONS);
  await ensureDbReady();
  setupVoice();
});

async function ensureDbReady() {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (!res.ok) throw new Error("Backend not ready");
    showToast("✅ KRIME AI connected");
  } catch (e) {
    // Try to init DB
    showToast("⚙️ Initializing database…");
    try {
      await fetch(`${API_BASE}/api/init-db`, { method: "POST" });
      showToast("✅ Database initialized");
    } catch (err) {
      showToast("⚠️ Could not connect to backend");
    }
  }
}

// ── TABS ─────────────────────────────────────────────────────────────────
function showTab(tabId) {
  document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
  document.getElementById(`tab-${tabId}`).classList.add("active");
  document.querySelectorAll(".nav-btn").forEach(b => {
    if (b.getAttribute("onclick")?.includes(`'${tabId}'`)) b.classList.add("active");
  });
  currentTabId = tabId;

  if (tabId === "dashboard") loadDashboard();
  if (tabId === "analytics") loadAnalytics();
  if (tabId === "heatmap") loadHeatmap();
  if (tabId === "network") loadNetwork();
}

// ── DOCUMENT INTELLIGENCE (RAG) ──────────────────────────────────────────
async function askRagQuestion(presetQuestion) {
  const input = document.getElementById("ragInput");
  const question = (presetQuestion || input.value || "").trim();
  if (!question) return;

  input.value = question;
  const resultsEl = document.getElementById("ragResults");

  const qId = `rag-q-${Date.now()}`;
  resultsEl.insertAdjacentHTML("afterbegin", `
    <div class="rag-entry" id="${qId}">
      <div class="rag-question">🧑‍💼 ${question}</div>
      <div class="rag-answer rag-loading">🔎 Searching knowledge base…</div>
    </div>
  `);

  try {
    const res = await fetch(`${API_BASE}/api/rag-query`, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify({ query: question })
    });
    const data = await res.json();
    const entry = document.getElementById(qId);

    if (data.success && data.answer) {
      const sourcesHtml = (data.sources || []).map(s => `
        <div class="rag-source">
          <span class="rag-source-title">📄 ${s.title}</span>
          <div class="rag-source-snippet">${s.snippet}</div>
        </div>
      `).join("");

      entry.innerHTML = `
        <div class="rag-question">🧑‍💼 ${question}</div>
        <div class="rag-answer">🧠 ${data.answer}</div>
        ${sourcesHtml ? `<div class="rag-sources"><div class="rag-sources-title">Sources:</div>${sourcesHtml}</div>` : ""}
      `;
    } else {
      entry.innerHTML = `
        <div class="rag-question">🧑‍💼 ${question}</div>
        <div class="rag-answer rag-error">❌ ${data.error || "Could not find an answer in the knowledge base."}</div>
      `;
    }
  } catch (e) {
    const entry = document.getElementById(qId);
    if (entry) {
      entry.innerHTML = `
        <div class="rag-question">🧑‍💼 ${question}</div>
        <div class="rag-answer rag-error">❌ Error: ${e.message}</div>
      `;
    }
  }

  input.value = "";
}

// ── ANOMALY DETECTION (QuickML AutoML Pipeline) ──────────────────
async function runAnomalyScan() {
  const resultsEl = document.getElementById("anomalyResults");
  resultsEl.innerHTML = `<div class="rag-loading">🔍 Scanning all police stations via QuickML model…</div>`;

  try {
    const res = await fetch(`${API_BASE}/api/anomaly-scan`, { method: "GET" });
    const data = await res.json();

    if (!data.success) {
      resultsEl.innerHTML = `<div class="rag-error">❌ ${data.error || "Anomaly scan failed."}</div>`;
      return;
    }

    if (data.anomaly_count === 0) {
      resultsEl.innerHTML = `<div class="anomaly-none">✅ No anomalous hotspots detected among current stations.</div>`;
      return;
    }

    const rows = data.anomalies.map(a => `
      <tr>
        <td>${a.station_name}</td>
        <td>${a.district_name}</td>
        <td>${a.case_count}</td>
        <td>${a.avg_severity}</td>
        <td>${a.pending_count}</td>
        <td>${a.high_severity_count}</td>
      </tr>
    `).join("");

    resultsEl.innerHTML = `
      <div class="anomaly-summary">⚠️ <strong>${data.anomaly_count}</strong> station(s) flagged as anomalous hotspots requiring review:</div>
      <div class="table-container">
        <table class="anomaly-table">
          <thead>
            <tr><th>Station</th><th>District</th><th>Cases</th><th>Avg Severity</th><th>Pending</th><th>High Severity</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  } catch (e) {
    resultsEl.innerHTML = `<div class="rag-error">❌ Error: ${e.message}</div>`;
  }
}

// ── LANG ──────────────────────────────────────────────────────────────────
function setLang(lang) {
  currentLang = lang;
  document.getElementById("btn-en").classList.toggle("active", lang === "en");
  document.getElementById("btn-kn").classList.toggle("active", lang === "kn");
  const input = document.getElementById("chatInput");
  if (lang === "kn") {
    input.placeholder = "ಅಪರಾಧ ಮಾಹಿತಿಯನ್ನು ಕೇಳಿ… (ಕನ್ನಡ ಅಥವಾ English)";
    renderSuggestions(["ಬೆಂಗಳೂರಿನಲ್ಲಿ ಎಷ್ಟು ಕೊಲೆ ಪ್ರಕರಣಗಳಿವೆ?",
      "ಕಳ್ಳತನ ಪ್ರಕರಣಗಳ ಪ್ರವೃತ್ತಿ ತೋರಿಸು",
      "ಯಾವ ಜಿಲ್ಲೆಯಲ್ಲಿ ಅತಿ ಹೆಚ್ಚು ಅಪರಾಧ?",
      "ಅಪರಾಧ ಹಾಟ್‌ಸ್ಪಾಟ್ ತೋರಿಸು"]);
  } else {
    input.placeholder = "Ask about crime patterns, suspects, hotspots… (English or ಕನ್ನಡ)";
    renderSuggestions(DEFAULT_SUGGESTIONS);
  }
}

// ── SUGGESTIONS ──────────────────────────────────────────────────────────
function renderSuggestions(suggestions) {
  const container = document.getElementById("exampleQueries");
  if (!container) return;
  container.innerHTML = suggestions.map(s =>
    `<span class="example-chip" onclick="useExample('${s.replace(/'/g, "\\'")}')">${s}</span>`
  ).join("");
}

function useExample(text) {
  document.getElementById("chatInput").value = text;
  sendMessage();
}

// ── CHAT ──────────────────────────────────────────────────────────────────
function handleKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

async function sendMessage() {
  const input = document.getElementById("chatInput");
  const query = input.value.trim();
  if (!query) return;

  input.value = "";
  input.style.height = "auto";
  document.getElementById("sendBtn").disabled = true;

  const timestamp = new Date().toLocaleTimeString();
  addMessageBubble("user", query, timestamp);
  conversation.push({ role: "user", content: query, timestamp });

  // Show typing indicator
  const typingId = showTyping();

  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify({ query, language: currentLang, session_id: sessionId })
    });
    const data = await res.json();
    removeTyping(typingId);

    if (data.success) {
      const ts = new Date().toLocaleTimeString();
      addMessageBubble("assistant", data.response, ts, data.sql);
      conversation.push({ role: "assistant", content: data.response, timestamp: ts });

      // Render chart if data available
      if (data.data && data.data.length > 0 && data.chart_type !== "number") {
        renderResponseChart(data);
      }

      // Audit log
      addAuditEntry({
        query: query,
        translated: data.translated_query,
        intents: data.intents,
        sql: data.sql,
        count: data.total_records,
        ts: ts
      });

      // Update suggestions
      fetchSuggestions(data.intents[0]);
    } else {
      addMessageBubble("assistant", `❌ Error: ${data.error}`, new Date().toLocaleTimeString());
    }
  } catch (err) {
    removeTyping(typingId);
    addMessageBubble("assistant", `❌ Network error: ${err.message}. Is the backend running?`, new Date().toLocaleTimeString());
  }

  document.getElementById("sendBtn").disabled = false;
}

function addMessageBubble(role, content, timestamp, sql) {
  const container = document.getElementById("chatMessages");

  // Remove welcome card on first message
  const welcome = container.querySelector(".welcome-card");
  if (welcome) welcome.remove();

  const div = document.createElement("div");
  div.className = `message ${role}`;

  const avatar = role === "user" ? "👮" : "🤖";
  const renderedContent = role === "assistant" && typeof marked !== "undefined"
    ? marked.parse(content)
    : escapeHtml(content);

  let sqlBlock = "";
  if (sql && role === "assistant") {
    sqlBlock = `<div class="sql-badge" title="SQL Query executed">🔍 SQL: ${escapeHtml(sql.substring(0, 150))}${sql.length > 150 ? "…" : ""}</div>`;
  }

  div.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div>
      <div class="msg-bubble">${renderedContent}${sqlBlock}</div>
      <div class="msg-meta">${timestamp}</div>
    </div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function showTyping() {
  const container = document.getElementById("chatMessages");
  const id = "typing_" + Date.now();
  const div = document.createElement("div");
  div.id = id;
  div.className = "message assistant";
  div.innerHTML = `<div class="msg-avatar">🤖</div>
    <div class="msg-bubble">
      <div class="typing-indicator">
        <div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>
      </div>
    </div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return id;
}

function removeTyping(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function clearChat() {
  document.getElementById("chatMessages").innerHTML = `
    <div class="welcome-card">
      <div class="welcome-icon">🚔</div>
      <h2>KRIME AI</h2>
      <p>Ask me anything about Karnataka crime data in <strong>English</strong> or <strong>ಕನ್ನಡ</strong></p>
      <div class="example-queries" id="exampleQueries"></div>
    </div>`;
  renderSuggestions(DEFAULT_SUGGESTIONS);
  conversation = [];
  // Hide chart panel
  document.getElementById("chartPanel").classList.add("hidden");
}

async function fetchSuggestions(lastIntent) {
  try {
    const res = await fetch(`${API_BASE}/api/suggest`, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify({ last_intent: lastIntent })
    });
    const data = await res.json();
    if (data.suggestions) renderSuggestions(data.suggestions);
  } catch (_) {}
}

// ── CHARTS ────────────────────────────────────────────────────────────────
const CHART_COLORS = [
  "#1a73e8", "#34a853", "#fbbc04", "#e53935", "#ab47bc",
  "#00acc1", "#ff7043", "#43a047", "#7e57c2", "#26a69a",
  "#ec407a", "#8d6e63", "#78909c", "#ffa726", "#66bb6a"
];

function renderResponseChart(data) {
  const panel = document.getElementById("chartPanel");
  panel.classList.remove("hidden");

  const chartTitle = document.getElementById("chartTitle");
  const tableContainer = document.getElementById("tableContainer");
  const ctx = document.getElementById("responseChart").getContext("2d");

  if (currentChartInstance) { currentChartInstance.destroy(); currentChartInstance = null; }

  if (data.chart_type === "table") {
    chartTitle.textContent = "📋 Data Table";
    document.getElementById("responseChart").style.display = "none";
    tableContainer.style.display = "block";
    tableContainer.innerHTML = buildTable(data.data);
    return;
  }

  document.getElementById("responseChart").style.display = "block";
  tableContainer.style.display = "none";

  const items = data.data.slice(0, 20);
  const firstKey = Object.keys(items[0] || {})[0];
  const secondKey = Object.keys(items[0] || {})[1];

  const labels = items.map(r => String(r[firstKey] || "N/A").substring(0, 20));
  const values = items.map(r => Number(r[secondKey]) || 0);

  let chartType = data.chart_type === "line" ? "line"
    : data.chart_type === "pie" ? "pie"
    : data.chart_type === "doughnut" ? "doughnut"
    : "bar";

  chartTitle.textContent = "📊 " + (data.intents?.[0] || "Results").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

  currentChartInstance = new Chart(ctx, {
    type: chartType,
    data: {
      labels,
      datasets: [{
        label: secondKey,
        data: values,
        backgroundColor: chartType === "pie" || chartType === "doughnut"
          ? CHART_COLORS
          : CHART_COLORS[0],
        borderColor: chartType === "line" ? CHART_COLORS[0] : undefined,
        borderWidth: chartType === "line" ? 2 : 1,
        fill: chartType === "line" ? false : undefined,
        tension: 0.4,
        pointRadius: chartType === "line" ? 4 : undefined,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: {
          display: chartType !== "bar",
          labels: { color: "#e6edf3", font: { size: 11 } }
        },
        tooltip: { mode: "index", intersect: false }
      },
      scales: chartType === "bar" || chartType === "line" ? {
        x: {
          ticks: { color: "#8b949e", maxRotation: 45, font: { size: 10 } },
          grid: { color: "#21262d" }
        },
        y: {
          ticks: { color: "#8b949e", font: { size: 10 } },
          grid: { color: "#21262d" }
        }
      } : {}
    }
  });
}

function buildTable(data) {
  if (!data || !data.length) return "<p style='color:#8b949e'>No data</p>";
  const cols = Object.keys(data[0]);
  return `<table class="data-table">
    <thead><tr>${cols.map(c => `<th>${c}</th>`).join("")}</tr></thead>
    <tbody>${data.slice(0, 50).map(row =>
      `<tr>${cols.map(c => `<td title="${row[c] ?? ""}">${row[c] ?? "—"}</td>`).join("")}</tr>`
    ).join("")}</tbody>
  </table>`;
}

function toggleChartPanel() {
  document.getElementById("chartPanel").classList.toggle("hidden");
}

// ── DASHBOARD ─────────────────────────────────────────────────────────────
async function loadDashboard() {
  try {
    // KPIs
    const res = await fetch(`${API_BASE}/api/dashboard`);
    const { data } = await res.json();
    document.getElementById("kpi-total").textContent = (data.total_cases || 0).toLocaleString();
    document.getElementById("kpi-pending").textContent = (data.pending_cases || 0).toLocaleString();
    document.getElementById("kpi-wanted").textContent = (data.wanted_accused || 0).toLocaleString();
    document.getElementById("kpi-clearance").textContent = (data.clearance_rate || 0) + "%";
    document.getElementById("kpi-accused").textContent = (data.total_accused || 0).toLocaleString();
    document.getElementById("kpi-victims").textContent = (data.total_victims || 0).toLocaleString();
    document.getElementById("kpi-stations").textContent = (data.total_stations || 0).toLocaleString();
    document.getElementById("kpi-topcrime").textContent = data.top_crime || "—";
    document.getElementById("dashTimestamp").textContent = "Updated: " + new Date().toLocaleString();

    // Charts
    await loadDashChart("dash-trend", "yearly_trend", "line");
    await loadDashChart("dash-type", "crimes_by_type", "pie");
    await loadDashChart("dash-status", "case_status", "doughnut");
    await loadDashChart("dash-district", "crimes_by_district", "bar");
    await loadDashChart("dash-arrest", "arrest_status", "doughnut");
    await loadDashChart("dash-severity", "severity_distribution", "bar");
  } catch (e) {
    console.error("Dashboard error:", e);
    showToast("❌ Dashboard load failed: " + e.message);
  }
}

async function loadDashChart(canvasId, chartId, defaultType) {
  try {
    const res = await fetch(`${API_BASE}/api/chart-data`, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify({ chart_id: chartId })
    });
    const d = await res.json();
    if (!d.success || !d.data?.length) return;

    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    if (dbCharts[canvasId]) { dbCharts[canvasId].destroy(); }

    const labels = d.data.map(r => String(r.label || "").substring(0, 18));
    const values = d.data.map(r => Number(r.value) || 0);
    const type = d.type === "line" ? "line"
      : d.type === "pie" ? "pie"
      : d.type === "doughnut" ? "doughnut"
      : "bar";

    dbCharts[canvasId] = new Chart(ctx, {
      type,
      data: {
        labels,
        datasets: [{
          label: d.title,
          data: values,
          backgroundColor: type === "pie" || type === "doughnut"
            ? CHART_COLORS
            : type === "line" ? "rgba(26,115,232,0.2)" : CHART_COLORS[0],
          borderColor: type === "line" ? CHART_COLORS[0] : "transparent",
          borderWidth: type === "line" ? 2 : 0,
          fill: type === "line",
          tension: 0.4,
          pointRadius: type === "line" ? 3 : undefined,
          pointBackgroundColor: type === "line" ? CHART_COLORS[0] : undefined,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: {
            display: type !== "bar",
            labels: { color: "#8b949e", font: { size: 10 }, boxWidth: 12 }
          },
          title: { display: false }
        },
        scales: type === "bar" || type === "line" ? {
          x: { ticks: { color: "#8b949e", font: { size: 10 }, maxRotation: 45 }, grid: { color: "#21262d" } },
          y: { ticks: { color: "#8b949e", font: { size: 10 } }, grid: { color: "#21262d" } }
        } : {}
      }
    });
  } catch (e) { console.warn(`Chart ${canvasId} failed:`, e); }
}

// ── ANALYTICS ─────────────────────────────────────────────────────────────
async function loadAnalytics() {
  await loadDashChart("ana-monthly", "monthly_trend", "line");
  await loadDashChart("ana-hotspot", "top_hotspots", "bar");
  await loadDashChart("ana-property", "property_recovery", "bar");
  await loadDashChart("ana-gender", "gender_accused", "pie");
  loadPredictive();
}

async function loadPredictive() {
  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify({ query: "predict crime trend next months early warning", language: "en", session_id: sessionId })
    });
    const d = await res.json();
    const box = document.getElementById("predictiveText");
    if (d.success && box) {
      box.innerHTML = typeof marked !== "undefined"
        ? marked.parse(d.response)
        : d.response.replace(/\n/g, "<br/>");
    }
  } catch (e) { console.warn("Predictive load failed:", e); }
}

// ── HEATMAP ───────────────────────────────────────────────────────────────
async function loadHeatmap() {
  const crimeType = document.getElementById("hmCrimeType")?.value || "";
  const year = document.getElementById("hmYear")?.value || "";

  try {
    let url = `${API_BASE}/api/heatmap`;
    const params = [];
    if (crimeType) params.push(`crime_type=${encodeURIComponent(crimeType)}`);
    if (year) params.push(`year=${year}`);
    if (params.length) url += "?" + params.join("&");

    const res = await fetch(url);
    const d = await res.json();

    if (d.success) renderHeatmapCanvas(d.points, crimeType, year);
  } catch (e) {
    showToast("❌ Heatmap failed: " + e.message);
  }
}

function renderHeatmapCanvas(points, crimeType, year) {
  const canvas = document.getElementById("heatmapCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  // Karnataka approximate bounding box
  const LAT_MIN = 11.5, LAT_MAX = 18.5;
  const LON_MIN = 74.0, LON_MAX = 78.6;
  const W = canvas.width, H = canvas.height;

  ctx.clearRect(0, 0, W, H);

  // Background – simplified Karnataka map outline (filled polygon)
  ctx.fillStyle = "#1a2744";
  ctx.fillRect(0, 0, W, H);

  // Grid lines
  ctx.strokeStyle = "rgba(255,255,255,0.05)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 8; i++) {
    ctx.beginPath();
    ctx.moveTo(0, (H / 7) * i);
    ctx.lineTo(W, (H / 7) * i);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo((W / 7) * i, 0);
    ctx.lineTo((W / 7) * i, H);
    ctx.stroke();
  }

  // Plot crime incidents as colored dots
  points.forEach(pt => {
    const x = ((pt.lng - LON_MIN) / (LON_MAX - LON_MIN)) * W;
    const y = H - ((pt.lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * H;
    const severity = pt.weight || 5;

    const r = Math.min(255, Math.floor(severity * 25));
    const g = Math.max(0, Math.floor(255 - severity * 25));
    const alpha = 0.5 + (severity / 20);

    // Glow effect
    const gradient = ctx.createRadialGradient(x, y, 0, x, y, 12 + severity);
    gradient.addColorStop(0, `rgba(${r}, ${g}, 0, ${alpha})`);
    gradient.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(x, y, 12 + severity, 0, Math.PI * 2);
    ctx.fill();
  });

  // Label major cities
  const cities = [
    { name: "Bengaluru", lat: 12.97, lng: 77.56 },
    { name: "Mysuru", lat: 12.29, lng: 76.64 },
    { name: "Mangaluru", lat: 12.87, lng: 74.84 },
    { name: "Hubballi", lat: 15.36, lng: 75.12 },
    { name: "Belagavi", lat: 15.86, lng: 74.50 },
    { name: "Kalaburagi", lat: 17.32, lng: 76.82 },
    { name: "Ballari", lat: 15.14, lng: 76.92 },
    { name: "Davanagere", lat: 14.47, lng: 75.92 },
    { name: "Shivamogga", lat: 13.93, lng: 75.56 },
  ];

  cities.forEach(city => {
    const x = ((city.lng - LON_MIN) / (LON_MAX - LON_MIN)) * W;
    const y = H - ((city.lat - LAT_MIN) / (LAT_MAX - LAT_MIN)) * H;
    ctx.fillStyle = "rgba(255,255,255,0.8)";
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.font = "bold 11px Segoe UI";
    ctx.fillText(city.name, x + 6, y + 4);
  });

  // Stats overlay
  const statsDiv = document.getElementById("heatmap-stats");
  if (statsDiv) {
    statsDiv.innerHTML = `
      <strong>${points.length}</strong> incidents shown<br/>
      ${crimeType ? `Crime: <strong>${crimeType}</strong><br/>` : ""}
      ${year ? `Year: <strong>${year}</strong>` : ""}
    `;
  }
}

// ── NETWORK ───────────────────────────────────────────────────────────────
async function loadNetwork() {
  try {
    const res = await fetch(`${API_BASE}/api/network`);
    const d = await res.json();

    if (!d.success || !d.nodes?.length) {
      document.getElementById("network-graph").innerHTML =
        '<div style="padding:40px;color:#8b949e;text-align:center">No network data available</div>';
      return;
    }

    if (typeof vis === "undefined") {
      document.getElementById("network-graph").innerHTML =
        '<div style="padding:40px;color:#8b949e;text-align:center">Network library loading…</div>';
      return;
    }

    const container = document.getElementById("network-graph");
    const nodes = new vis.DataSet(d.nodes);
    const edges = new vis.DataSet(d.edges);

    const options = {
      nodes: {
        shape: "dot",
        font: { color: "#e6edf3", size: 11 },
        borderWidth: 2,
      },
      edges: {
        color: { color: "#30363d", highlight: "#1a73e8" },
        font: { color: "#8b949e", size: 10, align: "middle" },
        arrows: { to: { enabled: false } },
        smooth: { type: "dynamic" }
      },
      physics: {
        enabled: true,
        barnesHut: { gravitationalConstant: -3000, springLength: 120 }
      },
      interaction: { hover: true, tooltipDelay: 200 },
      background: { color: "transparent" }
    };

    if (networkInstance) networkInstance.destroy();
    networkInstance = new vis.Network(container, { nodes, edges }, options);

    networkInstance.on("selectNode", (params) => {
      if (params.nodes.length > 0) {
        const node = nodes.get(params.nodes[0]);
        document.getElementById("network-info").innerHTML = `
          <strong>Name:</strong> ${node.label}<br/>
          <strong>Gang:</strong> ${node.group}<br/>
          <strong>Node color:</strong> ${node.color === "#e74c3c" ? "🔴 WANTED / ABSCONDING" : "🔵 Arrested"}<br/>
          <strong>Connections:</strong> ${networkInstance.getConnectedNodes(node.id).length}
        `;
      }
    });

  } catch (e) {
    showToast("❌ Network load failed: " + e.message);
  }
}

// ── AUDIT LOG ─────────────────────────────────────────────────────────────
function addAuditEntry(entry) {
  auditLog.unshift(entry);
  const container = document.getElementById("auditLog");
  const empty = container.querySelector(".audit-empty");
  if (empty) empty.remove();

  const div = document.createElement("div");
  div.className = "audit-entry";
  div.innerHTML = `
    <div class="audit-entry-header">
      <div class="audit-query">🔍 "${entry.query}"</div>
      <div class="audit-time">${entry.ts}</div>
    </div>
    ${entry.translated && entry.translated !== entry.query
      ? `<div style="font-size:11px;color:#8b949e">Translated: "${entry.translated}"</div>` : ""}
    <div class="audit-intents">
      ${(entry.intents || []).map(i => `<span class="intent-badge">${i}</span>`).join("")}
    </div>
    <div class="audit-sql">${escapeHtml(entry.sql || "")}</div>
    <div class="audit-result-count">✅ ${entry.count} record(s) returned</div>
  `;
  container.insertBefore(div, container.firstChild);
}

// ── PDF EXPORT ────────────────────────────────────────────────────────────
async function exportPDF() {
  if (!conversation.length) {
    showToast("⚠️ No conversation to export. Start chatting first.");
    return;
  }

  showLoading("Generating PDF report…");

  try {
    const res = await fetch(`${API_BASE}/api/export-pdf`, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify({
        conversation,
        title: "KRIME AI Investigation Report",
        officer: "Investigating Officer",
        badge: "KA-" + Math.floor(Math.random() * 90000 + 10000)
      })
    });
    const d = await res.json();

    if (d.success && typeof jspdf !== "undefined") {
      const { jsPDF } = jspdf;
      const doc = new jsPDF({ unit: "mm", format: "a4" });

      doc.setFillColor(13, 17, 23);
      doc.rect(0, 0, 210, 297, "F");
      doc.setTextColor(230, 237, 243);

      doc.setFontSize(18);
      doc.setFont("helvetica", "bold");
      doc.text("KRIME AI", 15, 20);
      doc.setFontSize(10);
      doc.setFont("helvetica", "normal");
      doc.setTextColor(139, 148, 158);
      doc.text("Karnataka State Police · SCRB · Datathon 2026", 15, 27);
      doc.text("Report generated: " + new Date().toLocaleString(), 15, 33);

      let y = 45;
      conversation.forEach((msg, i) => {
        if (y > 270) { doc.addPage(); y = 20; }
        if (msg.role === "user") {
          doc.setTextColor(251, 188, 4);
          doc.setFontSize(11);
          doc.setFont("helvetica", "bold");
          doc.text(`[${msg.timestamp}] Query:`, 15, y);
          y += 6;
          doc.setTextColor(230, 237, 243);
          doc.setFont("helvetica", "normal");
          doc.setFontSize(10);
          const lines = doc.splitTextToSize(msg.content, 180);
          doc.text(lines, 20, y);
          y += lines.length * 5 + 3;
        } else {
          doc.setTextColor(52, 168, 83);
          doc.setFontSize(10);
          doc.setFont("helvetica", "bold");
          doc.text("AI Response:", 15, y);
          y += 5;
          doc.setTextColor(200, 210, 220);
          doc.setFont("helvetica", "normal");
          // Strip markdown
          const plain = msg.content.replace(/\*\*/g, "").replace(/\*/g, "").replace(/#+\s/g, "").replace(/•\s/g, "- ");
          const lines = doc.splitTextToSize(plain, 175);
          doc.text(lines, 20, y);
          y += lines.length * 4.5 + 6;
          doc.setDrawColor(48, 54, 61);
          doc.line(15, y - 2, 195, y - 2);
        }
      });

      doc.save(d.filename || "ksp_report.pdf");
      showToast("✅ PDF report exported successfully");
    } else {
      // Fallback: open print dialog
      const htmlContent = atob(d.html_b64);
      const w = window.open("", "_blank");
      w.document.write(`<html><head><title>KSP Report</title>
        <style>body{font-family:Arial;padding:20px;} hr{border-color:#ccc;}</style>
        </head><body>${htmlContent}</body></html>`);
      w.print();
    }
  } catch (e) {
    showToast("❌ Export failed: " + e.message);
  } finally {
    hideLoading();
  }
}

// ── VOICE INPUT ───────────────────────────────────────────────────────────
function setupVoice() {
  if (!('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)) {
    document.getElementById("voiceBtn").style.display = "none";
    return;
  }
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  mediaRecognition = new SpeechRecognition();
  mediaRecognition.continuous = false;
  mediaRecognition.interimResults = true;
  mediaRecognition.lang = currentLang === "kn" ? "kn-IN" : "en-IN";

  mediaRecognition.onresult = (event) => {
    let transcript = Array.from(event.results).map(r => r[0].transcript).join("");
    document.getElementById("chatInput").value = transcript;
    document.getElementById("voiceStatus").textContent = "🎤 " + transcript;
  };

  mediaRecognition.onend = () => {
    isRecording = false;
    document.getElementById("voiceBtn").classList.remove("recording");
    document.getElementById("voiceStatus").textContent = "";
    // Auto-send if we have input
    const val = document.getElementById("chatInput").value.trim();
    if (val) sendMessage();
  };

  mediaRecognition.onerror = (e) => {
    isRecording = false;
    document.getElementById("voiceBtn").classList.remove("recording");
    document.getElementById("voiceStatus").textContent = "";
    showToast("⚠️ Voice error: " + e.error);
  };
}

function toggleVoice() {
  if (!mediaRecognition) { showToast("⚠️ Voice not supported in this browser"); return; }
  if (isRecording) {
    mediaRecognition.stop();
    isRecording = false;
    document.getElementById("voiceBtn").classList.remove("recording");
    document.getElementById("voiceStatus").textContent = "";
  } else {
    mediaRecognition.lang = currentLang === "kn" ? "kn-IN" : "en-IN";
    mediaRecognition.start();
    isRecording = true;
    document.getElementById("voiceBtn").classList.add("recording");
    document.getElementById("voiceStatus").textContent = "🔴 Listening… Speak now";
  }
}

// ── DB Init ───────────────────────────────────────────────────────────────
async function initDb() {
  showLoading("Reinitializing database with synthetic data…");
  try {
    const res = await fetch(`${API_BASE}/api/init-db`, { method: "POST" });
    const d = await res.json();
    showToast(d.success ? "✅ " + d.message : "❌ " + d.error);
  } catch (e) {
    showToast("❌ " + e.message);
  } finally {
    hideLoading();
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────
function showLoading(text = "Processing…") {
  document.getElementById("loadingText").textContent = text;
  document.getElementById("loadingOverlay").style.display = "flex";
}
function hideLoading() {
  document.getElementById("loadingOverlay").style.display = "none";
}

let toastTimer;
function showToast(msg) {
  const toast = document.getElementById("toast");
  toast.textContent = msg;
  toast.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.style.display = "none"; }, 4000);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
