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

// Analytics tab "AI Predictive Insights" and "AI Anomaly Detection" sections
// call slow QuickML-backed endpoints. These flags let us kick off both
// requests in the background as soon as the user logs in (see
// preloadAnalyticsInsights(), called from enterApp()) so that by the time the
// user actually clicks the Analytics tab, the results are already cached and
// display instantly instead of showing a multi-second loading state.
let predictiveLoaded = false;
let anomalyLoaded = false;
let analyticsPreloadStarted = false;

// RAG (Documents tab) has its own independent language + voice state,
// separate from the AI Chat tab, since they are different conversations.
let ragLang = "en";
let ragIsRecording = false;
let ragRecognition = null;

// ── AUTH / ROLE-BASED SECURE ACCESS ────────────────────────────────────────
let authToken = sessionStorage.getItem("krimeai_token") || null;
let currentUser = null; // { username, role, full_name, badge_number }

function authHeaders(extra) {
  const h = Object.assign({ "Content-Type": "text/plain;charset=utf-8" }, extra || {});
  // NOTE: Zoho Catalyst's Advanced I/O gateway intercepts the standard
  // "Authorization" header and tries to validate it as its OWN OAuth token,
  // rejecting our custom session tokens with a 401 "invalid oauth token"
  // before the request ever reaches our Flask app. Using a custom header
  // name avoids that collision (see auth.extract_token() on the backend,
  // which reads X-Auth-Token first).
  if (authToken) h["X-Auth-Token"] = authToken;
  return h;
}

async function handleLogin(evt) {
  evt.preventDefault();
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  const errEl = document.getElementById("loginError");
  const btn = document.getElementById("loginSubmitBtn");
  errEl.textContent = "";
  btn.disabled = true;

  try {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (data.success) {
      authToken = data.token;
      currentUser = data.user;
      sessionStorage.setItem("krimeai_token", authToken);
      sessionStorage.setItem("krimeai_user", JSON.stringify(currentUser));
      enterApp();
    } else {
      errEl.textContent = data.error || "Login failed";
    }
  } catch (e) {
    errEl.textContent = "Network error: " + e.message;
  } finally {
    btn.disabled = false;
  }
  return false;
}

async function handleLogout() {
  try {
    await fetch(`${API_BASE}/api/auth/logout`, { method: "POST", headers: authHeaders() });
  } catch (_) {}
  authToken = null;
  currentUser = null;
  sessionStorage.removeItem("krimeai_token");
  sessionStorage.removeItem("krimeai_user");
  document.getElementById("loginScreen").style.display = "flex";
  document.getElementById("appHeader").style.display = "none";
  document.getElementById("appLayout").style.display = "none";
  document.getElementById("loginUsername").value = "";
  document.getElementById("loginPassword").value = "";
}

function applyRoleGating() {
  if (!currentUser) return;
  document.querySelectorAll("[data-roles]").forEach(el => {
    const allowed = el.getAttribute("data-roles").split(",").map(r => r.trim());
    el.style.display = allowed.includes(currentUser.role) ? "" : "none";
  });
}

function enterApp() {
  document.getElementById("loginScreen").style.display = "none";
  document.getElementById("appHeader").style.display = "flex";
  document.getElementById("appLayout").style.display = "flex";
  document.getElementById("userRole").textContent = currentUser.full_name || currentUser.username;
  document.getElementById("userRoleChip").textContent = currentUser.role;
  applyRoleGating();

  renderSuggestions(DEFAULT_SUGGESTIONS);
  ensureDbReady();
  setupVoice();
  setupRagVoice();

  // Fire-and-forget: start warming up the Analytics tab's AI Predictive
  // Insights + AI Anomaly Detection sections right away, in parallel with
  // the rest of the app initialization above, instead of waiting until the
  // user navigates to the Analytics tab.
  preloadAnalyticsInsights();
}

function preloadAnalyticsInsights() {
  if (analyticsPreloadStarted) return;
  analyticsPreloadStarted = true;

  loadPredictive();
  // Anomaly scan hits a role-gated endpoint (Admin/SP/Inspector only) --
  // skip it entirely for Analyst accounts to avoid a guaranteed 403.
  if (currentUser && ["Admin", "SP", "Inspector"].includes(currentUser.role)) {
    runAnomalyScan();
  }
}

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  const savedUser = sessionStorage.getItem("krimeai_user");
  if (authToken && savedUser) {
    try {
      currentUser = JSON.parse(savedUser);
      // Verify token is still valid server-side
      const res = await fetch(`${API_BASE}/api/auth/me`, { headers: authHeaders() });
      const data = await res.json();
      if (data.success) {
        currentUser = data.user;
        enterApp();
        return;
      }
    } catch (_) { /* fall through to login screen */ }
  }
  // Not authenticated (or session expired) — show login screen
  authToken = null;
  currentUser = null;
  sessionStorage.removeItem("krimeai_token");
  sessionStorage.removeItem("krimeai_user");
});

async function ensureDbReady() {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    if (!res.ok) throw new Error("Backend not ready");
    showToast("✅ KRIME AI connected");
  } catch (e) {
    showToast("⚠️ Could not connect to backend");
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
      headers: authHeaders(),
      body: JSON.stringify({ query: question, language: ragLang })
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
      // Same defensive fallback as the Chat tab -- a killed/timed-out
      // request may not carry our expected error shape at all.
      const errMsg = data && data.error ? data.error : "Could not find an answer in the knowledge base.";
      entry.innerHTML = `
        <div class="rag-question">🧑‍💼 ${question}</div>
        <div class="rag-answer rag-error">❌ ${errMsg}</div>
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

// ── RAG LANGUAGE SWITCH (Documents tab) ──────────────────────────────────
function setLangRag(lang) {
  ragLang = lang;
  document.getElementById("btn-en-rag").classList.toggle("active", lang === "en");
  document.getElementById("btn-kn-rag").classList.toggle("active", lang === "kn");
  const input = document.getElementById("ragInput");
  if (input) {
    input.placeholder = lang === "kn"
      ? "ಉದಾ. ಪ್ರಕರಣ ಇತ್ಯರ್ಥ ದರದ ಗುರಿ ಏನು?"
      : "e.g. What is the case clearance rate target?";
  }
  if (ragRecognition) ragRecognition.lang = lang === "kn" ? "kn-IN" : "en-IN";
}

// ── RAG VOICE INPUT (Documents tab) ───────────────────────────────────────
function setupRagVoice() {
  const ragVoiceBtn = document.getElementById("ragVoiceBtn");
  if (!('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)) {
    if (ragVoiceBtn) ragVoiceBtn.style.display = "none";
    return;
  }
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  ragRecognition = new SpeechRecognition();
  ragRecognition.continuous = false;
  ragRecognition.interimResults = true;
  ragRecognition.lang = ragLang === "kn" ? "kn-IN" : "en-IN";

  ragRecognition.onresult = (event) => {
    let transcript = Array.from(event.results).map(r => r[0].transcript).join("");
    document.getElementById("ragInput").value = transcript;
    document.getElementById("ragVoiceStatus").textContent = "🎤 " + transcript;
  };

  ragRecognition.onend = () => {
    ragIsRecording = false;
    document.getElementById("ragVoiceBtn").classList.remove("recording");
    document.getElementById("ragVoiceStatus").textContent = "";
    // Auto-send if we have input
    const val = document.getElementById("ragInput").value.trim();
    if (val) askRagQuestion();
  };

  ragRecognition.onerror = (e) => {
    ragIsRecording = false;
    document.getElementById("ragVoiceBtn").classList.remove("recording");
    document.getElementById("ragVoiceStatus").textContent = "";
    showToast("⚠️ Voice error: " + e.error);
  };
}

function toggleRagVoice() {
  if (!ragRecognition) { showToast("⚠️ Voice not supported in this browser"); return; }
  if (ragIsRecording) {
    ragRecognition.stop();
    ragIsRecording = false;
    document.getElementById("ragVoiceBtn").classList.remove("recording");
    document.getElementById("ragVoiceStatus").textContent = "";
  } else {
    ragRecognition.lang = ragLang === "kn" ? "kn-IN" : "en-IN";
    ragRecognition.start();
    ragIsRecording = true;
    document.getElementById("ragVoiceBtn").classList.add("recording");
    document.getElementById("ragVoiceStatus").textContent = "🔴 Listening… Speak now";
  }
}

// ── ANOMALY DETECTION (QuickML AutoML Pipeline) ──────────────────
async function runAnomalyScan() {
  const resultsEl = document.getElementById("anomalyResults");
  resultsEl.innerHTML = `<div class="rag-loading">🔍 Scanning all police stations via QuickML model…</div>`;

  try {
    const res = await fetch(`${API_BASE}/api/anomaly-scan`, { method: "GET", headers: authHeaders() });
    const data = await res.json();

    if (!data.success) {
      resultsEl.innerHTML = `<div class="rag-error">❌ ${data.error || "Anomaly scan failed."}</div>`;
      return;
    }

    if (data.anomaly_count === 0) {
      resultsEl.innerHTML = `<div class="anomaly-none">✅ No anomalous hotspots detected among current stations.</div>`;
      anomalyLoaded = true;
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
    anomalyLoaded = true;
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
      headers: authHeaders(),
      body: JSON.stringify({ query, language: currentLang, session_id: sessionId })
    });
    const data = await res.json();
    removeTyping(typingId);

    if (data.success) {
      const ts = new Date().toLocaleTimeString();
      addMessageBubble("assistant", data.response, ts);
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
        ts: ts,
        contextUsed: data.context_used,
        resolvedEntities: data.resolved_entities
      });

      // Update suggestions
      fetchSuggestions(data.intents[0]);
    } else if (data.code === "AUTH_REQUIRED") {
      showToast("⚠️ Session expired. Please sign in again.");
      handleLogout();
    } else {
      // If the platform/gateway killed the request (e.g. a timeout) before
      // our Flask app could respond, `data` may not match our expected
      // shape at all, leaving data.error undefined -- show a friendly
      // fallback message instead of literally rendering "undefined".
      const errMsg = data && data.error ? data.error : "The request took too long or the server didn't respond as expected. Please try again.";
      addMessageBubble("assistant", `❌ Error: ${errMsg}`, new Date().toLocaleTimeString());
    }
  } catch (err) {
    removeTyping(typingId);
    addMessageBubble("assistant", `❌ Network error: ${err.message}. Is the backend running?`, new Date().toLocaleTimeString());
  }

  document.getElementById("sendBtn").disabled = false;
}

function addMessageBubble(role, content, timestamp) {
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

  // NOTE: the SQL query executed for this answer is intentionally NOT shown
  // here to keep the chat clean for end users -- it's still fully visible
  // (untruncated) in the Audit Trail tab for explainability/auditing.
  div.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div>
      <div class="msg-bubble">${renderedContent}</div>
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

  // Tell the backend to forget this session's conversation context, then
  // start a brand new session so no district/year/crime_type carries over
  // into the new chat.
  fetch(`${API_BASE}/api/reset-context`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ session_id: sessionId })
  }).catch(() => {});
  sessionId = "session_" + Date.now();
}

async function fetchSuggestions(lastIntent) {
  try {
    const res = await fetch(`${API_BASE}/api/suggest`, {
      method: "POST",
      headers: authHeaders(),
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
  const chartContainer = document.querySelector(".chart-container");
  const tableContainer = document.getElementById("tableContainer");
  const ctx = document.getElementById("responseChart").getContext("2d");

  if (currentChartInstance) { currentChartInstance.destroy(); currentChartInstance = null; }

  if (data.chart_type === "table") {
    chartTitle.textContent = "📋 Data Table";
    // Hide the whole fixed-height chart container (not just the canvas),
    // otherwise its reserved height leaves a blank gap above the table.
    chartContainer.style.display = "none";
    tableContainer.style.display = "block";
    tableContainer.innerHTML = buildTable(data.data);
    return;
  }

  chartContainer.style.display = "block";
  tableContainer.style.display = "none";

  const items = data.data.slice(0, 20);

  // choose x (category) and y (numeric) keys heuristically so charts are meaningful
  function pickXYKeys(sample) {
    const keys = Object.keys(sample || {});
    const xCandidates = ["label", "station_name", "district_name", "crime_type", "name", "month", "year"];
    const yCandidates = ["value", "case_count", "count", "cases", "items_stolen", "total_value", "avg_severity", "severity_score", "severity", "percentage"];

    let xKey = keys.find(k => xCandidates.includes(k)) || null;
    let yKey = keys.find(k => yCandidates.includes(k)) || null;

    if (!xKey) {
      // prefer the first string column
      xKey = keys.find(k => typeof sample[k] === 'string') || keys[0] || 'label';
    }
    if (!yKey) {
      // prefer the first numeric column
      yKey = keys.find(k => typeof sample[k] === 'number') || keys.find(k => !isNaN(Number(sample[k]))) || keys[1] || keys[0];
    }
    return [xKey, yKey];
  }

  const [firstKey, secondKey] = pickXYKeys(items[0] || {});

  const labels = items.map(r => String(r[firstKey] ?? "N/A"));
  const values = items.map(r => Number(r[secondKey]) || 0);

  let chartType = data.chart_type === "line" ? "line"
    : data.chart_type === "pie" ? "pie"
    : data.chart_type === "doughnut" ? "doughnut"
    : "bar";

  // Prefer explicit chart title when provided, else derive from intent
  chartTitle.textContent = "📊 " + (data.title || (data.intents?.[0] || "Results")).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

  // helper: wrap long labels into multiple lines for readability
  function wrapLabel(label, maxLen = 12) {
    if (!label) return "";
    const words = String(label).split(/\s+/);
    let line = "", out = [];
    words.forEach(w => {
      if ((line + " " + w).trim().length > maxLen) {
        if (line) out.push(line.trim());
        line = w;
      } else {
        line = (line + " " + w).trim();
      }
    });
    if (line) out.push(line.trim());
    return out.join("\n");
  }

  // apply wrapping to labels shown on chart
  const chartLabels = labels.map(l => wrapLabel(l, 14));

  // determine a friendly y-axis title
  let yAxisTitle = secondKey ? String(secondKey).replace(/_/g, ' ').toUpperCase() : 'Value';
  const sk = (secondKey || '').toLowerCase();
  if (sk.includes('case') || sk.includes('count') || sk.includes('cases')) yAxisTitle = 'Cases';
  else if (sk.includes('severity')) yAxisTitle = 'Avg Severity (0-10)';

  // detect severity field to color-code bars
  const severityKey = items[0] && (items[0].avg_severity !== undefined ? 'avg_severity' : (items[0].severity !== undefined ? 'severity' : null));
  const severityArr = severityKey ? items.map(r => Number(r[severityKey]) || 0) : null;

  function severityColor(v) {
    const x = Math.max(0, Math.min(10, Number(v) || 0)) / 10; // 0..1
    const r = Math.round(240 * x + 15 * (1 - x));
    const g = Math.round(200 * (1 - x) + 80 * x);
    return `rgba(${r}, ${g}, 50, 0.95)`;
  }

  currentChartInstance = new Chart(ctx, {
    type: chartType,
    data: {
      labels: chartLabels,
      datasets: [{
        label: (secondKey || "Value").replace(/_/g, ' ').toUpperCase(),
        data: values,
        backgroundColor: chartType === "pie" || chartType === "doughnut"
          ? CHART_COLORS
          : (severityArr ? severityArr.map(severityColor) : CHART_COLORS[0]),
        borderColor: chartType === "line" ? CHART_COLORS[0] : undefined,
        borderWidth: chartType === "line" ? 2 : 1,
        fill: chartType === "line" ? false : undefined,
        tension: 0.3,
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
        tooltip: {
          mode: "index",
          intersect: false,
          callbacks: {
            label: function(context) {
              const v = context.parsed.y ?? context.parsed ?? 0;
              const parts = [`${context.dataset.label || "Value"}: ${Number(v).toLocaleString()}`];
              if (severityArr && context.dataIndex !== undefined) {
                parts.push(`Avg Severity: ${severityArr[context.dataIndex].toFixed(2)}`);
              }
              return parts.join(' — ');
            }
          }
        }
      },
      scales: chartType === "bar" || chartType === "line" ? {
        x: {
          ticks: { color: "#8b949e", font: { size: 10 }, maxRotation: 60, autoSkip: true },
          grid: { color: "#21262d" },
          title: { display: true, text: firstKey ? String(firstKey).replace(/_/g, ' ').toUpperCase() : 'Category', color: '#8b949e', font: { size: 11 } }
        },
        y: {
          ticks: { color: "#8b949e", font: { size: 10 }, callback: v => Number(v).toLocaleString() },
          grid: { color: "#21262d" },
          title: { display: true, text: yAxisTitle, color: '#8b949e', font: { size: 11 } }
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
    const res = await fetch(`${API_BASE}/api/dashboard`, { headers: authHeaders() });
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
      headers: authHeaders(),
      body: JSON.stringify({ chart_id: chartId })
    });
    const d = await res.json();
    if (!d.success || !d.data?.length) return;

    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    if (dbCharts[canvasId]) { dbCharts[canvasId].destroy(); }

    // wrap long labels for readability
    function _wrapLabel(label, maxLen = 14) {
      if (!label) return "";
      const words = String(label).split(/\s+/);
      let line = "", out = [];
      words.forEach(w => {
        if ((line + " " + w).trim().length > maxLen) {
          if (line) out.push(line.trim());
          line = w;
        } else {
          line = (line + " " + w).trim();
        }
      });
      if (line) out.push(line.trim());
      return out.join("\n");
    }

    const type = d.type === "line" ? "line"
      : d.type === "pie" ? "pie"
      : d.type === "doughnut" ? "doughnut"
      : "bar";

    // labels / values
    const labels = d.data.map(r => _wrapLabel(String(r.label || ""), 14));
    const values = d.data.map(r => Number(r.value) || 0);

    // detect optional severity column to color-code bars
    const severityField = d.data[0] && (d.data[0].severity !== undefined ? 'severity' : (d.data[0].avg_severity !== undefined ? 'avg_severity' : null));
    const severityValues = severityField ? d.data.map(r => Number(r[severityField]) || 0) : null;

    // decide y-axis title based on title or presence of severity
    let yAxisTitle = 'Count';
    if (severityField) yAxisTitle = 'Avg Severity (0-10)';
    else if (String(d.title || '').toLowerCase().includes('value')) yAxisTitle = 'Value (₹)';
    else if (String(d.title || '').toLowerCase().includes('cases') || String(d.title || '').toLowerCase().includes('count')) yAxisTitle = 'Cases';

    function sevColor(v) {
      const x = Math.max(0, Math.min(10, Number(v) || 0)) / 10;
      const r = Math.round(240 * x + 15 * (1 - x));
      const g = Math.round(200 * (1 - x) + 80 * x);
      return `rgba(${r}, ${g}, 50, 0.95)`;
    }

    dbCharts[canvasId] = new Chart(ctx, {
      type,
      data: {
        labels,
        datasets: [{
          label: d.title || '',
          data: values,
          backgroundColor: (type === "pie" || type === "doughnut")
            ? CHART_COLORS
            : (severityValues ? severityValues.map(sevColor) : CHART_COLORS[0]),
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
          title: { display: false },
          tooltip: {
            callbacks: {
              label: function(ctx) { return `${ctx.dataset.label || 'Value'}: ${Number(ctx.parsed.y ?? ctx.parsed ?? 0).toLocaleString()}`; }
            }
          }
        },
        scales: type === "bar" || type === "line" ? {
          x: { ticks: { color: "#8b949e", font: { size: 10 }, maxRotation: 60, autoSkip: true }, grid: { color: "#21262d" }, title: { display: true, text: d.title || '', color: '#8b949e', font: { size: 11 } } },
          y: { ticks: { color: "#8b949e", font: { size: 10 }, callback: v => Number(v).toLocaleString() }, grid: { color: "#21262d" }, title: { display: true, text: yAxisTitle, color: '#8b949e', font: { size: 11 } } }
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
  // Predictive Insights is usually already preloaded (see
  // preloadAnalyticsInsights(), triggered at login) -- only fetch here if
  // that preload hasn't completed yet (e.g. still in-flight, or failed).
  if (!predictiveLoaded) loadPredictive();
}

async function loadPredictive() {
  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ query: "predict crime trend next months early warning", language: "en", session_id: sessionId })
    });
    const d = await res.json();
    const box = document.getElementById("predictiveText");
    if (d.success && box) {
      box.innerHTML = typeof marked !== "undefined"
        ? marked.parse(d.response)
        : d.response.replace(/\n/g, "<br/>");
      predictiveLoaded = true;
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

    const res = await fetch(url, { headers: authHeaders() });
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
    const res = await fetch(`${API_BASE}/api/network`, { headers: authHeaders() });
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
    ${_renderContextBadge(entry.contextUsed, entry.resolvedEntities)}
  `;
  container.insertBefore(div, container.firstChild);
}

function _renderContextBadge(contextUsed, resolvedEntities) {
  if (!contextUsed || Object.keys(contextUsed).length === 0) return "";
  const carried = Object.keys(contextUsed)
    .filter(k => contextUsed[k])
    .map(k => `${k.replace("_", " ")}: ${escapeHtml(String((resolvedEntities || {})[k] ?? ""))}`);
  if (!carried.length) return "";
  return `<div class="audit-context-used" title="Entity remembered from earlier in this conversation">🧭 Context carried over — ${carried.join(", ")}</div>`;
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
      headers: authHeaders(),
      body: JSON.stringify({
        conversation,
        title: "KRIME AI Investigation Report",
        officer: (currentUser && currentUser.full_name) || "Investigating Officer",
        badge: (currentUser && currentUser.badge_number) || ("KA-" + Math.floor(Math.random() * 90000 + 10000))
      })
    });
    const d = await res.json();

    if (d.success && typeof jspdf !== "undefined") {
      await renderConversationToPdf(d.filename);
      showToast("✅ PDF report exported successfully");
    } else {
      // Fallback: open print dialog. NOTE: atob() alone returns a raw binary
      // string, which mangles any multi-byte UTF-8 character (emoji,
      // Kannada, the · middle-dot, etc.) into mojibake -- decode the bytes
      // properly as UTF-8 instead.
      const htmlContent = decodeBase64Utf8(d.html_b64);
      const w = window.open("", "_blank");
      w.document.write(`<html><head><title>KSP Report</title>
        <meta charset="UTF-8">
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

// jsPDF's built-in fonts (helvetica/times/courier) only embed the WinAnsi
// (Latin-1) glyph set. Any character outside that -- Kannada (ಕನ್ನಡ),
// emoji like 📊/🧠/🔍, etc. -- has no matching glyph and doc.text() either
// silently drops it or (worse, as reported) renders garbled bytes from the
// font's internal encoding table instead. Rather than trying to strip/detect
// every unsupported script, we render the conversation as real HTML (reusing
// the exact same marked.js + .msg-bubble/table CSS already used on-screen,
// where Kannada and tables are known to display correctly) and rasterize it
// into the PDF via jsPDF's doc.html() + html2canvas. This uses the browser's
// own font stack, so any language the browser can render, the PDF can too --
// and markdown tables become real <table> grids instead of plain text with
// stray pipe characters.
async function renderConversationToPdf(filename) {
  const { jsPDF } = jspdf;
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const pageWidthPt = doc.internal.pageSize.getWidth();

  // Build an off-screen container with the report content as real HTML.
  const container = document.createElement("div");
  container.style.cssText = [
    "position:fixed", "left:0", "top:0", "z-index:-1000",
    "width:760px", "background:#0d1117", "color:#e6edf3",
    "font-family:'Segoe UI',system-ui,-apple-system,sans-serif",
    "padding:28px", "box-sizing:border-box"
  ].join(";");

  const officer = (currentUser && currentUser.full_name) || "Investigating Officer";
  const badge = (currentUser && currentUser.badge_number) || ("KA-" + Math.floor(Math.random() * 90000 + 10000));

  const headerHtml = `
    <div style="border-bottom:2px solid #30363d;padding-bottom:14px;margin-bottom:18px;">
      <div style="font-size:22px;font-weight:700;color:#e6edf3;">KRIME AI</div>
      <div style="font-size:12px;color:#8b949e;margin-top:4px;">Karnataka State Police &middot; SCRB &middot; Datathon 2026</div>
      <div style="font-size:11px;color:#8b949e;margin-top:2px;">
        Officer: ${escapeHtml(officer)} | Badge: ${escapeHtml(badge)} | Generated: ${escapeHtml(new Date().toLocaleString())}
      </div>
    </div>`;

  const bodyHtml = conversation.map(msg => {
    if (msg.role === "user") {
      return `
        <div style="margin:14px 0 6px;">
          <div style="font-size:12px;font-weight:700;color:#fbbc04;">[${escapeHtml(msg.timestamp || "")}] Query:</div>
          <div style="font-size:13px;color:#e6edf3;margin-top:3px;white-space:pre-wrap;">${escapeHtml(msg.content)}</div>
        </div>`;
    }
    const rendered = typeof marked !== "undefined" ? marked.parse(msg.content || "") : escapeHtml(msg.content || "");
    return `
      <div style="margin:6px 0 14px;">
        <div style="font-size:12px;font-weight:700;color:#34a853;margin-bottom:4px;">AI Response:</div>
        <div class="pdf-msg-body" style="font-size:12px;color:#c8d2dc;line-height:1.5;">${rendered}</div>
      </div>
      <hr style="border:none;border-top:1px solid #30363d;margin:10px 0;">`;
  }).join("");

  // Reuse the same table look as the on-screen chat bubbles (see .msg-bubble
  // table/th/td rules in style.css) so exported tables look like real grids.
  const tableCss = `
    <style>
      .pdf-msg-body p { margin: 4px 0; }
      .pdf-msg-body ul, .pdf-msg-body ol { padding-left: 18px; margin: 4px 0; }
      .pdf-msg-body strong { color: #fbbc04; }
      .pdf-msg-body table {
        width: 100%;
        border-collapse: collapse;
        margin: 8px 0;
        font-size: 11px;
      }
      .pdf-msg-body th, .pdf-msg-body td {
        border: 1px solid #30363d;
        padding: 5px 7px;
        text-align: left;
        vertical-align: top;
        color: #e6edf3;
      }
      .pdf-msg-body th { background: rgba(26,115,232,0.18); color: #8ecbff; }
      .pdf-msg-body tr:nth-child(even) { background: rgba(255,255,255,0.03); }
    </style>`;

  container.innerHTML = tableCss + headerHtml + bodyHtml;
  document.body.appendChild(container);

  try {
    // IMPORTANT: jsPDF's doc.html() does NOT rasterize pixels by default --
    // it replays html2canvas's parsed layout through jsPDF's own vector
    // "context2d" shim, which still draws glyphs via doc.text() under the
    // hood. That means it still hits the WinAnsiEncoding font limitation and
    // Kannada still comes out as mojibake, even though CSS layout (e.g.
    // tables) is respected. To get TRUE font-agnostic rendering, we call
    // html2canvas() directly ourselves to get a real pixel bitmap (rendered
    // using the browser's own font engine, which already displays Kannada
    // correctly on-screen), then embed that bitmap as a plain image via
    // doc.addImage() -- no jsPDF font/glyph logic is involved at all for the
    // text pixels themselves. Sliced across pages since a canvas image can't
    // span multiple PDF pages directly.
    const canvas = await html2canvas(container, {
      scale: 2,
      backgroundColor: "#0d1117",
      useCORS: true
    });

    const pageHeightPt = doc.internal.pageSize.getHeight();
    const pxToPt = pageWidthPt / canvas.width;
    const pageHeightPx = Math.floor(pageHeightPt / pxToPt);

    let renderedPx = 0;
    let firstPage = true;
    while (renderedPx < canvas.height) {
      const sliceHeightPx = Math.min(pageHeightPx, canvas.height - renderedPx);

      const sliceCanvas = document.createElement("canvas");
      sliceCanvas.width = canvas.width;
      sliceCanvas.height = sliceHeightPx;
      sliceCanvas.getContext("2d").drawImage(
        canvas, 0, renderedPx, canvas.width, sliceHeightPx, 0, 0, canvas.width, sliceHeightPx
      );

      if (!firstPage) doc.addPage();
      doc.addImage(
        sliceCanvas.toDataURL("image/png"), "PNG",
        0, 0, pageWidthPt, sliceHeightPx * pxToPt
      );
      firstPage = false;
      renderedPx += sliceHeightPx;
    }

    doc.save(filename || "ksp_report.pdf");
  } finally {
    document.body.removeChild(container);
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
    const res = await fetch(`${API_BASE}/api/init-db`, { method: "POST", headers: authHeaders() });
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

// jsPDF's built-in fonts (helvetica/times/courier) only embed the WinAnsi
// (Latin-1 + a few extra) glyph set. Any character outside that range --
// emoji like 📊/🧠/🔍/🚨, dingbats, variation selectors, ZWJ, etc. -- has no
// matching glyph, so the PDF renderer falls back to whatever raw bytes it
// can find in the font's internal encoding table, producing garbled
// mojibake such as "Ø=ÜÊ" instead of silently skipping the character.
// Stripping them before calling doc.text()/splitTextToSize() avoids this;
// Kannada (ಕನ್ನಡ) text is unaffected since it's outside these ranges too --
// note it will still not RENDER with helvetica (which has no Kannada
// glyphs), but at least it fails safely by being invisible rather than
// showing corrupted symbols.
function stripPdfUnsafeChars(str) {
  if (!str) return "";
  return String(str).replace(
    // Covers all emoji/pictographs actually used in this app (📊 🧠 🔍 🚨
    // ⚠️ ✅ ❌ 🎤 🔊 🗑️ ➤ 🧭 📈 📋 💰 🕸️ 👥 🏥 🏫 🔴 🚪 etc.) plus variation
    // selectors (FE0F) and zero-width joiner (200D) used in multi-codepoint
    // emoji, WITHOUT touching normal WinAnsi-safe punctuation like em-dash
    // (—), curly quotes (“ ”), ellipsis (…) or the bullet (•) that jsPDF's
    // built-in fonts render correctly.
    /[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{200D}]/gu,
    ""
  ).replace(/[ \t]{2,}/g, " ").trim();
}

// atob() decodes base64 into a raw "binary string" where each char code is
// a single byte (0-255) -- it does NOT interpret multi-byte UTF-8 sequences.
// Since the backend base64-encodes UTF-8 bytes (see export_pdf() in
// index.py: html_content.encode() defaults to UTF-8), decoding with atob()
// alone corrupts any non-ASCII character (emoji, Kannada, the · middle-dot)
// into mojibake. Re-interpreting the binary string's bytes through
// TextDecoder('utf-8') decodes them correctly.
function decodeBase64Utf8(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder("utf-8").decode(bytes);
}
