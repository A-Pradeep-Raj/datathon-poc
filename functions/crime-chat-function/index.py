"""
KSP Crime AI - Main Catalyst Advanced I/O Function (Flask App)
Handles all API routes for the conversational AI platform
"""
import json
import os
import sys
import sqlite3
import hashlib
import base64
import functools
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, g

# Ensure stdout/stderr handle UTF-8 (important on Windows for Kannada text)
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

# Import our modules
from synthetic_data import create_database
from ai_engine import (
    translate_kannada_to_english, detect_intent, detect_greeting, build_sql_query,
    execute_query, generate_natural_response, get_dashboard_stats, query_rag,
    scan_stations_for_anomalies
)
import auth as auth_module

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False   # Ensure Kannada / Unicode chars are not escaped

# ── DB Path ──────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "ksp_crime.db")

def get_db():
    """Get database connection, create if not exists"""
    if not os.path.exists(DB_PATH):
        create_database(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── CORS helper ───────────────────────────────────────────────────────────────
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Auth-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "3600"
    return response


@app.before_request
def handle_preflight():
    """Short-circuit CORS preflight (OPTIONS) requests for ANY route so the
    browser's preflight check always succeeds, even for routes that don't
    explicitly declare OPTIONS in their methods list. This is required when
    the frontend is hosted on a different origin (e.g. Catalyst Slate)."""
    if request.method == "OPTIONS":
        response = jsonify({"success": True})
        return add_cors(response), 200


@app.after_request
def after_request(response):
    return add_cors(response)


# ── Role-Based Secure Access ─────────────────────────────────────────────────
# Every route below (except /api/health and /api/auth/login) requires a
# valid session token. Certain routes additionally restrict which ROLE may
# call them, e.g. only Admin can wipe/reseed the database, and Analysts
# cannot view the criminal network graph or export PDF reports (protects
# sensitive identity data from non-investigative roles).

def require_role(*allowed_roles):
    """Decorator: reject the request unless it carries a valid session
    token AND (when allowed_roles is given) the user's role is included.
    The authenticated user dict is stashed on flask.g.current_user."""
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapped(*args, **kwargs):
            if request.method == "OPTIONS":
                return view_func(*args, **kwargs)
            token = auth_module.extract_token(request)
            conn = get_db()
            user = auth_module.get_session_user(conn, token)
            conn.close()
            if not user:
                return jsonify({"success": False, "error": "Unauthorized: please sign in.", "code": "AUTH_REQUIRED"}), 401
            if allowed_roles and user["role"] not in allowed_roles:
                return jsonify({
                    "success": False,
                    "error": f"Forbidden: role '{user['role']}' cannot access this feature (requires {', '.join(allowed_roles)}).",
                    "code": "FORBIDDEN"
                }), 403
            g.current_user = user
            return view_func(*args, **kwargs)
        return wrapped
    return decorator


@app.route("/api/auth/login", methods=["POST", "OPTIONS"])
def auth_login():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    try:
        body = request.get_json(force=True)
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        if not username or not password:
            return jsonify({"success": False, "error": "Username and password are required"}), 400

        conn = get_db()
        user = auth_module.verify_login(conn, username, password)
        if not user:
            conn.close()
            return jsonify({"success": False, "error": "Invalid username or password"}), 401

        token = auth_module.create_session(conn, user)
        conn.close()
        return jsonify({
            "success": True,
            "token": token,
            "user": user,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/auth/logout", methods=["POST", "OPTIONS"])
def auth_logout():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    try:
        token = auth_module.extract_token(request)
        conn = get_db()
        auth_module.delete_session(conn, token)
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/auth/me", methods=["GET", "OPTIONS"])
def auth_me():
    if request.method == "OPTIONS":
        return jsonify({}), 200
    token = auth_module.extract_token(request)
    conn = get_db()
    user = auth_module.get_session_user(conn, token)
    conn.close()
    if not user:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    return jsonify({"success": True, "user": user})


# ── Routes ────────────────────────────────────────────────────────────────────

PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "public")

@app.route("/", methods=["GET"])
def index_page():
    return send_from_directory(PUBLIC_DIR, "index.html")

@app.route("/<path:filename>", methods=["GET"])
def static_files(filename):
    """Serve static files (CSS, JS) from the public folder"""
    return send_from_directory(PUBLIC_DIR, filename)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "1.0.0", "timestamp": datetime.now().isoformat()})


@app.route("/api/dashboard", methods=["GET"])
@require_role()  # any authenticated role
def dashboard():
    """Return key performance indicators for the dashboard"""
    try:
        conn = get_db()
        stats = get_dashboard_stats(conn)
        conn.close()
        return jsonify({"success": True, "data": stats})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/chat", methods=["POST", "OPTIONS"])
@require_role()  # any authenticated role
def chat():
    """Main conversational AI endpoint"""
    if request.method == "OPTIONS":
        return jsonify({}), 200

    try:
        body = request.get_json(force=True)
        user_query = body.get("query", "").strip()
        session_id = body.get("session_id", "default")
        language = body.get("language", "en")

        if not user_query:
            return jsonify({"success": False, "error": "Query is empty"}), 400

        # Translate Kannada if needed
        translated_query = translate_kannada_to_english(user_query) if language == "kn" else user_query

        # Detect greeting first so simple hello/hi returns a friendly intro
        intents = detect_intent(translated_query)
        if detect_greeting(translated_query):
            intents = ["greeting"]

        if intents[0] == "greeting":
            response_text = generate_natural_response(translated_query, intents, [], "none")
            return jsonify({
                "success": True,
                "query": user_query,
                "translated_query": translated_query,
                "intents": intents,
                "response": response_text,
                "chart_type": "none",
                "data": [],
                "total_records": 0,
                "sql": "",
                "timestamp": datetime.now().isoformat()
            })

        conn = get_db()

        # Load prior conversation context for this session (district/year/
        # crime_type last discussed), so follow-up questions like "what
        # about theft there?" can resolve "there" from earlier turns.
        prior_context = _get_session_context(conn, session_id)

        # Build and execute SQL, resolving entities against prior context
        sql, params, chart_type, resolved = build_sql_query(intents[0], translated_query, conn, prior_context)
        results = execute_query(conn, sql, params)

        # Generate natural language response (includes a transparency note
        # when context was carried over from earlier in the conversation)
        response_text = generate_natural_response(translated_query, intents, results, chart_type, resolved)

        # Persist the resolved context so the NEXT turn in this session can
        # build on it.
        _save_session_context(conn, session_id, resolved, intents[0])

        # Audit log
        _log_query(conn, session_id, user_query, translated_query, intents, sql, len(results))

        conn.close()

        return jsonify({
            "success": True,
            "query": user_query,
            "translated_query": translated_query,
            "intents": intents,
            "response": response_text,
            "chart_type": chart_type,
            "data": results[:100],  # limit payload
            "total_records": len(results),
            "sql": sql,  # for explainability/audit trail
            "context_used": resolved.get("context_used", {}),  # which entities (if any) were carried over
            "resolved_entities": {
                "district": resolved.get("district"),
                "year": resolved.get("year"),
                "crime_type": resolved.get("crime_type"),
            },
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/rag-query", methods=["POST", "OPTIONS"])
@require_role()  # any authenticated role
def rag_query():
    """
    Retrieval-Augmented Generation (RAG) endpoint for querying uploaded
    policy/SOP documents in natural language via Catalyst QuickML's RAG
    service. Returns a grounded answer plus source citations from the
    Knowledge Base.
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200

    try:
        body = request.get_json(force=True)
        question = (body.get("query") or "").strip()
        # NOTE: RAG doc Q&A allowed for all authenticated roles (see decorator
        # applied to the route below).
        document_ids = body.get("document_ids")  # optional override
        language = body.get("language", "en")  # "en" or "kn" (mirrors /api/chat)

        if not question:
            return jsonify({"success": False, "error": "Query is empty"}), 400

        # Translate Kannada keywords to English before hitting the RAG
        # service (same lightweight keyword-map approach used for /api/chat),
        # so voice/typed Kannada questions still retrieve the right documents.
        translated_question = translate_kannada_to_english(question) if language == "kn" else question

        result = query_rag(translated_question, document_ids)

        return jsonify({
            "success": result["success"],
            "query": question,
            "translated_query": translated_question,
            "language": language,
            "answer": result["answer"],
            "sources": result["sources"],
            "error": result["error"],
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/anomaly-scan", methods=["GET", "POST", "OPTIONS"])
@require_role("Admin", "SP", "Inspector")  # Analysts excluded: flags sensitive station-level data
def anomaly_scan():
    """
    Custom QuickML pipeline endpoint: scans all police stations' crime
    statistics through a trained AutoML classification model to flag
    anomalous hotspots (potential fraud/under-reporting/resource-strain
    indicators) requiring administrative review.
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200

    try:
        conn = get_db()
        flagged = scan_stations_for_anomalies(conn)
        conn.close()

        return jsonify({
            "success": True,
            "anomaly_count": len(flagged),
            "anomalies": flagged,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/chart-data", methods=["POST"])
@require_role()  # any authenticated role
def chart_data():
    """Return chart-ready data for a specific metric"""
    try:
        body = request.get_json(force=True)
        chart_id = body.get("chart_id", "crimes_by_district")
        year = body.get("year")
        district = body.get("district")

        conn = get_db()
        c = conn.cursor()

        charts = {
            "crimes_by_district": {
                "sql": """SELECT d.district_name as label, COUNT(*) as value
                          FROM fir_cases f
                          JOIN police_stations ps ON f.station_id = ps.station_id
                          JOIN districts d ON ps.district_id = d.district_id
                          GROUP BY d.district_name ORDER BY value DESC LIMIT 15""",
                "params": [], "type": "bar", "title": "Crimes by District"
            },
            "crimes_by_type": {
                "sql": "SELECT crime_type as label, COUNT(*) as value FROM fir_cases GROUP BY crime_type ORDER BY value DESC",
                "params": [], "type": "pie", "title": "Crime Type Distribution"
            },
            "yearly_trend": {
                "sql": """SELECT strftime('%Y', date_of_incident) as label, COUNT(*) as value
                          FROM fir_cases GROUP BY label ORDER BY label""",
                "params": [], "type": "line", "title": "Yearly Crime Trend"
            },
            "monthly_trend": {
                "sql": """SELECT strftime('%Y-%m', date_of_incident) as label, COUNT(*) as value
                          FROM fir_cases WHERE date_of_incident >= date('now','-18 months')
                          GROUP BY label ORDER BY label""",
                "params": [], "type": "line", "title": "Monthly Crime Trend (18 months)"
            },
            "case_status": {
                "sql": "SELECT status as label, COUNT(*) as value FROM fir_cases GROUP BY status ORDER BY value DESC",
                "params": [], "type": "doughnut", "title": "Case Status Distribution"
            },
            "severity_distribution": {
                "sql": """SELECT severity_score as label, COUNT(*) as value FROM fir_cases
                          GROUP BY severity_score ORDER BY severity_score""",
                "params": [], "type": "bar", "title": "Severity Score Distribution"
            },
            "top_hotspots": {
                "sql": """SELECT ps.station_name || ', ' || d.district_name as label,
                                 COUNT(*) as value, AVG(f.severity_score) as severity
                          FROM fir_cases f
                          JOIN police_stations ps ON f.station_id = ps.station_id
                          JOIN districts d ON ps.district_id = d.district_id
                          GROUP BY ps.station_id ORDER BY value DESC LIMIT 10""",
                "params": [], "type": "bar", "title": "Top 10 Crime Hotspots"
            },
            "gender_accused": {
                "sql": "SELECT gender as label, COUNT(*) as value FROM accused GROUP BY gender",
                "params": [], "type": "pie", "title": "Accused by Gender"
            },
            "arrest_status": {
                "sql": "SELECT arrest_status as label, COUNT(*) as value FROM accused GROUP BY arrest_status",
                "params": [], "type": "doughnut", "title": "Arrest Status"
            },
            "property_recovery": {
                "sql": """SELECT property_type as label,
                                 SUM(CASE WHEN recovered=1 THEN 1 ELSE 0 END) as recovered,
                                 SUM(CASE WHEN recovered=0 THEN 1 ELSE 0 END) as not_recovered
                          FROM stolen_property GROUP BY property_type ORDER BY recovered DESC""",
                "params": [], "type": "stacked_bar", "title": "Property Recovery Status"
            },
        }

        if chart_id not in charts:
            return jsonify({"success": False, "error": "Unknown chart_id"}), 400

        cfg = charts[chart_id]
        c.execute(cfg["sql"], cfg["params"])
        cols = [d[0] for d in c.description]
        rows = [dict(zip(cols, r)) for r in c.fetchall()]
        conn.close()

        return jsonify({
            "success": True,
            "chart_id": chart_id,
            "type": cfg["type"],
            "title": cfg["title"],
            "data": rows
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/network", methods=["GET"])
@require_role("Admin", "SP", "Inspector")  # Analysts excluded: identifiable criminal-network data
def criminal_network():
    """Return network graph data for criminal network visualization"""
    try:
        conn = get_db()
        c = conn.cursor()

        # Nodes: accused with gang affiliation
        c.execute("""
            SELECT a.accused_id as id, a.name, a.gang_affiliation,
                   COUNT(DISTINCT a.fir_id) as case_count, a.criminal_history,
                   a.arrest_status
            FROM accused a
            WHERE a.gang_affiliation IS NOT NULL AND a.gang_affiliation != ''
            GROUP BY a.accused_id
            ORDER BY case_count DESC LIMIT 50
        """)
        cols = [d[0] for d in c.description]
        nodes_raw = [dict(zip(cols, r)) for r in c.fetchall()]

        nodes = []
        for n in nodes_raw:
            nodes.append({
                "id": f"acc_{n['id']}",
                "label": n["name"],
                "group": n["gang_affiliation"],
                "size": min(30, 8 + n["case_count"] * 3),
                "color": "#e74c3c" if n["arrest_status"] in ("Wanted", "Absconding") else "#3498db",
                "title": f"{n['name']}\nGang: {n['gang_affiliation']}\nCases: {n['case_count']}\nStatus: {n['arrest_status']}"
            })

        # Edges: accused sharing the same FIR (co-accused)
        c.execute("""
            SELECT a1.accused_id as id1, a2.accused_id as id2, a1.fir_id,
                   f.crime_type
            FROM accused a1
            JOIN accused a2 ON a1.fir_id = a2.fir_id AND a1.accused_id < a2.accused_id
            JOIN fir_cases f ON a1.fir_id = f.fir_id
            WHERE a1.gang_affiliation IS NOT NULL AND a2.gang_affiliation IS NOT NULL
            LIMIT 100
        """)
        edges_raw = c.fetchall()
        node_ids = {n["id"] for n in nodes}
        edges = []
        for e in edges_raw:
            src = f"acc_{e[0]}"
            tgt = f"acc_{e[1]}"
            if src in node_ids and tgt in node_ids:
                edges.append({"from": src, "to": tgt,
                               "label": e[3], "color": "#aaa"})

        conn.close()
        return jsonify({"success": True, "nodes": nodes, "edges": edges})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/heatmap", methods=["GET"])
@require_role()  # any authenticated role
def heatmap():
    """Return lat/lon data for crime heatmap"""
    try:
        conn = get_db()
        c = conn.cursor()
        crime_type = request.args.get("crime_type")
        year = request.args.get("year")

        sql = "SELECT latitude, longitude, severity_score FROM fir_cases WHERE latitude IS NOT NULL"
        params = []
        if crime_type:
            sql += " AND crime_type = ?"
            params.append(crime_type)
        if year:
            sql += " AND strftime('%Y', date_of_incident) = ?"
            params.append(str(year))
        sql += " LIMIT 500"

        c.execute(sql, params)
        rows = c.fetchall()
        conn.close()

        points = [{"lat": r[0], "lng": r[1], "weight": r[2]} for r in rows]
        return jsonify({"success": True, "points": points})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/suggest", methods=["POST"])
@require_role()  # any authenticated role
def suggest_queries():
    """Return suggested follow-up queries based on context"""
    body = request.get_json(force=True)
    last_intent = body.get("last_intent", "general")

    suggestions_map = {
        "crime_by_district": [
            "Which district has the highest murder rate?",
            "Show monthly trend for Bengaluru Urban",
            "What is the case clearance rate by district?",
        ],
        "crime_by_type": [
            "Show cybercrime trend over the years",
            "Which areas have the most drug trafficking cases?",
            "Compare theft vs robbery cases",
        ],
        "crime_trend": [
            "Which crime type is increasing the fastest?",
            "Show hotspots for this crime type",
            "Predict next month's crime count",
        ],
        "accused_search": [
            "Show accused with repeat criminal history",
            "List gang-affiliated accused",
            "How many accused are still wanted or absconding?",
        ],
        "hotspot": [
            "Show crime heatmap for Bengaluru",
            "Which stations need more officers?",
            "Show severity scores for top hotspots",
        ],
        "general": [
            "How many total crimes are registered?",
            "Show crimes by district",
            "What are the top crime types in Karnataka?",
            "Show crime trend from 2019 to 2025",
            "Which areas are crime hotspots?",
            "ಬೆಂಗಳೂರಿನಲ್ಲಿ ಎಷ್ಟು ಅಪರಾಧಗಳಾಗಿವೆ? (Kannada)",
        ]
    }

    return jsonify({
        "suggestions": suggestions_map.get(last_intent, suggestions_map["general"])
    })


@app.route("/api/export-pdf", methods=["POST", "OPTIONS"])
@require_role("Admin", "SP", "Inspector")  # Analysts excluded: no official report generation
def export_pdf():
    """
    Export conversation history as a base64-encoded minimal HTML report.
    Full PDF generation happens client-side using jsPDF.
    This endpoint validates and formats the data.
    """
    if request.method == "OPTIONS":
        return jsonify({}), 200
    try:
        body = request.get_json(force=True)
        conversation = body.get("conversation", [])
        title = body.get("title", "KSP Crime AI Investigation Report")
        officer = body.get("officer", "Investigating Officer")
        badge = body.get("badge", "KA-XXXX")

        html_lines = [
            f"<h1>{title}</h1>",
            f"<p><b>Officer:</b> {officer} | <b>Badge:</b> {badge} | <b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>",
            "<hr/>",
        ]

        for turn in conversation:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            ts = turn.get("timestamp", "")
            if role == "user":
                html_lines.append(f"<p><b>🔍 Query [{ts}]:</b> {content}</p>")
            else:
                html_lines.append(f"<p><b>🤖 AI Response:</b><br/>{content.replace(chr(10), '<br/>')}</p>")
                html_lines.append("<hr/>")

        html_content = "\n".join(html_lines)
        html_b64 = base64.b64encode(html_content.encode()).decode()

        return jsonify({
            "success": True,
            "html_b64": html_b64,
            "filename": f"ksp_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/reset-context", methods=["POST", "OPTIONS"])
@require_role()  # any authenticated role
def reset_context():
    """Explicitly clear the stored conversation context for a session
    (called by the frontend when the user starts a 'New Chat')."""
    if request.method == "OPTIONS":
        return jsonify({}), 200
    try:
        body = request.get_json(force=True, silent=True) or {}
        session_id = body.get("session_id", "default")
        conn = get_db()
        _ensure_session_context_table(conn)
        conn.execute("DELETE FROM session_context WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/init-db", methods=["POST", "OPTIONS"])
@require_role("Admin")  # destructive op: Admin-only
def init_db():
    """Initialize / re-seed the synthetic database"""
    if request.method == "OPTIONS":
        return jsonify({}), 200
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        create_database(DB_PATH)
        return jsonify({"success": True, "message": "Database initialized with synthetic data"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_session_context_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS session_context (
        session_id TEXT PRIMARY KEY,
        last_district TEXT,
        last_year TEXT,
        last_crime_type TEXT,
        last_intent TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")


def _get_session_context(conn, session_id: str) -> dict:
    """Load the last-known district/year/crime_type for this session so the
    current turn can resolve follow-up questions that omit those entities."""
    try:
        _ensure_session_context_table(conn)
        row = conn.execute(
            "SELECT last_district, last_year, last_crime_type, last_intent FROM session_context WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return {}
        district, year, crime_type, intent = row
        return {
            "district": district or None,
            "year": int(year) if year else None,
            "crime_type": crime_type or None,
            "intent": intent or None,
        }
    except Exception:
        return {}


def _save_session_context(conn, session_id: str, resolved: dict, intent: str):
    """Persist the resolved entities from this turn as the new session
    context, so the next message in the same conversation can build on it."""
    try:
        _ensure_session_context_table(conn)
        conn.execute(
            """INSERT INTO session_context (session_id, last_district, last_year, last_crime_type, last_intent, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(session_id) DO UPDATE SET
                 last_district = excluded.last_district,
                 last_year = excluded.last_year,
                 last_crime_type = excluded.last_crime_type,
                 last_intent = excluded.last_intent,
                 updated_at = CURRENT_TIMESTAMP""",
            (
                session_id,
                resolved.get("district"),
                str(resolved.get("year")) if resolved.get("year") else None,
                resolved.get("crime_type"),
                intent,
            ),
        )
        conn.commit()
    except Exception:
        pass  # non-critical


def _log_query(conn, session_id, original, translated, intents, sql, result_count):
    try:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT, original_query TEXT, translated_query TEXT,
            intents TEXT, sql_executed TEXT, result_count INTEGER,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""INSERT INTO audit_log (session_id, original_query, translated_query,
                     intents, sql_executed, result_count) VALUES (?,?,?,?,?,?)""",
                  (session_id, original, translated, json.dumps(intents), sql, result_count))
        conn.commit()
    except Exception:
        pass  # non-critical


# ── Entry point ───────────────────────────────────────────────────────────────

def handler(context):
    """Zoho Catalyst Advanced I/O function entry point"""
    return app


if __name__ == "__main__":
    # Local dev
    if not os.path.exists(DB_PATH):
        print("Initializing database...")
        create_database(DB_PATH)
    app.run(debug=True, port=3000)
