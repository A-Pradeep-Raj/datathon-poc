"""
AI Engine for KSP Crime Database Chatbot
Handles NL -> SQL translation, response generation, pattern analysis
"""
import re
import json
import sqlite3
import time
from datetime import datetime
from typing import Optional, List, Tuple
import os

try:
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None


# ── Catalyst QuickML (GLM-4.7-Flash) integration ─────────────────────────────
# Provides an optional LLM-generated natural-language insight layered on top
# of the deterministic SQL-driven response. Falls back silently (returns
# None) if credentials are missing or the call fails, so the chatbot keeps
# working even when QuickML is unavailable.

_QUICKML_ACCOUNTS_URL = os.environ.get("QUICKML_ACCOUNTS_URL", "https://accounts.zoho.in")
_QUICKML_CLIENT_ID = os.environ.get("QUICKML_CLIENT_ID")
_QUICKML_CLIENT_SECRET = os.environ.get("QUICKML_CLIENT_SECRET")
_QUICKML_REFRESH_TOKEN = os.environ.get("QUICKML_REFRESH_TOKEN")
_QUICKML_GLM_ENDPOINT = os.environ.get(
    "QUICKML_GLM_ENDPOINT",
    "https://api.catalyst.zoho.in/quickml/v1/project/51742000000028001/glm/chat",
)
_QUICKML_ORG_ID = os.environ.get("QUICKML_ORG_ID", "60078097690")
_QUICKML_MODEL = "crm-di-glm47b_30b_it"

_quickml_token_cache = {"access_token": None, "expires_at": 0}


def _get_quickml_access_token() -> Optional[str]:
    """Return a cached/valid QuickML OAuth access token, refreshing if needed."""
    if not (_QUICKML_CLIENT_ID and _QUICKML_CLIENT_SECRET and _QUICKML_REFRESH_TOKEN):
        return None
    if _requests is None:
        return None

    now = time.time()
    if _quickml_token_cache["access_token"] and _quickml_token_cache["expires_at"] > now + 60:
        return _quickml_token_cache["access_token"]

    try:
        resp = _requests.post(
            f"{_QUICKML_ACCOUNTS_URL}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": _QUICKML_CLIENT_ID,
                "client_secret": _QUICKML_CLIENT_SECRET,
                "refresh_token": _QUICKML_REFRESH_TOKEN,
            },
            timeout=10,
        )
        data = resp.json()
        token = data.get("access_token")
        if not token:
            return None
        _quickml_token_cache["access_token"] = token
        _quickml_token_cache["expires_at"] = now + int(data.get("expires_in", 3600))
        return token
    except Exception:
        return None


def generate_llm_insight(user_query: str, data_summary: str) -> Optional[str]:
    """
    Call Catalyst QuickML's GLM-4.7-Flash LLM Serving endpoint to produce a
    short natural-language insight/summary grounded in the SQL results.
    Returns None if QuickML is not configured or the call fails (caller
    should gracefully fall back to the deterministic response).

    Note: the GLM endpoint's safety layer rejects requests that use the
    "system" role (treats it as a prompt-injection attempt), so instructions
    are folded into the "user" message instead.
    """
    token = _get_quickml_access_token()
    if not token:
        return None

    prompt = (
        "You are KRIME AI, a crime-intelligence assistant for Karnataka State Police. "
        "Based ONLY on the data below, write a concise (2-3 sentence) analytical insight "
        "for an investigating officer. Do not invent numbers not present in the data. "
        "IMPORTANT: Output ONLY the finished 2-3 sentence insight as plain prose. "
        "Do NOT show your thinking, drafts, numbered steps, or any text other than "
        "the finished insight itself. Start your reply directly with the insight text.\n\n"
        f"Officer's question: {user_query}\n\n"
        f"Query result data:\n{data_summary}\n\n"
        "ANSWER_ONLY>>>"
    )

    try:
        resp = _requests.post(
            _QUICKML_GLM_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Zoho-oauthtoken {token}",
                "CATALYST-ORG": _QUICKML_ORG_ID,
            },
            json={
                "model": _QUICKML_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                # This model ("thinking" variant) emits a <think>...</think>
                # reasoning trace before the real answer, which can consume
                # several hundred tokens on its own -- budget generously so
                # the final answer isn't truncated mid-sentence.
                "max_tokens": 1500,
                "temperature": 0.3,
                "stream": False,
            },
            timeout=30,
        )
        data = resp.json()
        text = (data.get("response") or "").strip()
        return _clean_llm_output(text) or None
    except Exception:
        return None


def _clean_llm_output(text: str) -> str:
    """
    Strip visible chain-of-thought / step-by-step reasoning that some models
    emit despite instructions, keeping only the final answer text.
    """
    if not text:
        return text
    # GLM's "thinking" models wrap reasoning in <think>...</think> tags and
    # place the real answer right after the closing tag.
    if "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
        if text:
            return text.strip('"').strip()
    # If the model used a numbered "reasoning steps" format, take content
    # after the last occurrence of a "final" marker if present.
    markers = [
        "answer_only>>>", "final polish:", "final insight:", "final answer:",
        "final version:", "insight:",
    ]
    lowered = text.lower()
    for marker in markers:
        idx = lowered.rfind(marker)
        if idx != -1:
            text = text[idx + len(marker):].strip()
            lowered = text.lower()
    # Drop numbered step lines like "1. **Analyze..." if the whole thing is
    # still clearly a reasoning trace (starts with a digit + period).
    if re.match(r"^\s*\d+\.\s", text) or "*draft" in lowered:
        # Keep only the last paragraph, which is usually the drafted answer.
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if paragraphs:
            text = paragraphs[-1]
        # Remove leading "*Draft N:*" style prefixes and stray leading quotes
        text = re.sub(r"^\*+\s*Draft\s*\d*\**:?\s*", "", text, flags=re.IGNORECASE).strip()
        text = text.strip('"').strip()
    return text.strip()


# --- Kannada <-> English keyword map ---
KANNADA_KEYWORD_MAP = {
    # Crime types
    "ಕೊಲೆ": "murder", "ಕಳ್ಳತನ": "theft", "ದರೋಡೆ": "robbery",
    "ಅತ್ಯಾಚಾರ": "rape", "ವಾಹನ ಕಳ್ಳತನ": "vehicle theft",
    "ಮಾದಕ ದ್ರವ್ಯ": "drug", "ಸೈಬರ್": "cybercrime",
    # Districts
    "ಬೆಂಗಳೂರು": "bengaluru", "ಮೈಸೂರು": "mysuru", "ಮಂಗಳೂರು": "mangaluru",
    "ಹುಬ್ಬಳ್ಳಿ": "hubballi", "ಬೆಳಗಾವಿ": "belagavi", "ಕಲಬುರಗಿ": "kalaburagi",
    # Time
    "ಈ ವರ್ಷ": "this year", "ಕಳೆದ ವರ್ಷ": "last year",
    "ಇಂದು": "today", "ಈ ತಿಂಗಳು": "this month",
    # Questions
    "ಎಷ್ಟು": "how many", "ಯಾವ": "which", "ಎಲ್ಲಿ": "where",
    "ಯಾರು": "who", "ಯಾವಾಗ": "when", "ತೋರಿಸು": "show",
    "ವರದಿ": "report", "ಅಂಕಿಅಂಶ": "statistics",
}


def translate_kannada_to_english(text: str) -> str:
    """Basic Kannada keyword translation for query understanding"""
    # Ensure text is properly decoded as unicode
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    translated = text
    for kannada, english in KANNADA_KEYWORD_MAP.items():
        translated = translated.replace(kannada, english)
    return translated


# --- Intent detection ---
INTENT_PATTERNS = {
    "count_crimes": [
        r"how many (crimes?|cases?|firs?|incidents?)",
        r"total (crimes?|cases?|firs?|incidents?)",
        r"number of (crimes?|cases?)",
        r"count (of )?(crimes?|cases?)",
    ],
    "crime_by_district": [
        r"crimes? in (\w[\w\s]*) district",
        r"cases? in (\w[\w\s]*)",
        r"(\w[\w\s]*) district (crime|case)",
        r"district.*(crime|case|statistics)",
        r"which district has (most|highest|maximum)",
        r"crimes? by district",
        r"show.*(district|districts)",
        r"district.*(wise|breakdown|distribution|comparison)",
        r"top.*district",
    ],
    "crime_by_type": [
        r"(murder|theft|robbery|rape|cybercrime|drug|dacoity|kidnapping|arson|burglary) (cases?|crimes?|statistics)?",
        r"crimes? by type",
        r"type of crimes?",
        r"breakdown of crimes?",
    ],
    "crime_trend": [
        r"trend",
        r"over the years?",
        r"year(ly)? (data|statistics|report)",
        r"increase|decrease|rise|fall|spike",
        r"2019|2020|2021|2022|2023|2024|2025",
        r"monthly",
    ],
    "hotspot": [
        r"hotspot",
        r"high crime area",
        r"most dangerous",
        r"crime prone",
        r"where (are|is) (the )?(most|highest) crimes?",
    ],
    "accused_search": [
        r"accused",
        r"criminal",
        r"offender",
        r"perpetrator",
        r"arrested",
        r"wanted",
        r"gang",
        r"repeat offender",
    ],
    "victim_stats": [
        r"victim",
        r"who (was|were) affected",
        r"age of victim",
        r"female victim",
        r"child victim",
    ],
    "case_status": [
        r"status",
        r"pending",
        r"investigation",
        r"chargesheet",
        r"conviction",
        r"trial",
        r"solved",
        r"unsolved",
        r"clearance rate",
    ],
    "officer_stats": [
        r"officer",
        r"inspector",
        r"police station",
        r"station",
        r"performance",
    ],
    "predictive": [
        r"predict",
        r"forecast",
        r"expect",
        r"will there be",
        r"next (month|year|quarter)",
        r"early warning",
        r"likely",
    ],
    "network_analysis": [
        r"network",
        r"gang",
        r"connection",
        r"linked",
        r"associate",
        r"criminal network",
    ],
    "property_crime": [
        r"stolen",
        r"property",
        r"recovered",
        r"loss",
        r"value",
    ],
    "severity": [
        r"severe",
        r"serious",
        r"high severity",
        r"brutal",
        r"violent",
        r"top.*crime",
        r"worst",
    ],
}


def detect_intent(query: str) -> list:
    """Detect one or more intents from the query"""
    query_lower = query.lower()
    detected = []
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, query_lower):
                detected.append(intent)
                break
    return detected if detected else ["general"]


def detect_greeting(query: str) -> bool:
    """Return True for simple greetings that should trigger a friendly intro."""
    if not query:
        return False
    cleaned = re.sub(r"[^a-zA-Z\s]", "", query).strip().lower()
    if not cleaned:
        return False
    greetings = [
        "hi", "hello", "hey", "hola", "good morning", "good afternoon", "good evening",
        "namaste", "welcome", "greetings"
    ]
    return any(cleaned == greeting or cleaned.startswith(greeting + " ") for greeting in greetings)


def extract_district(query: str) -> Optional[str]:
    districts = [
        "bengaluru urban", "bengaluru rural", "bengaluru",
        "mysuru", "mangaluru", "hubballi-dharwad", "hubballi", "dharwad",
        "belagavi", "kalaburagi", "ballari", "tumakuru", "shivamogga",
        "davanagere", "vijayapura", "raichur", "bidar", "hassan",
        "chitradurga", "udupi", "chikkamagaluru", "kodagu", "gadag"
    ]
    query_lower = query.lower()
    for d in districts:
        if d in query_lower:
            return d.title()
    return None


def extract_year(query: str) -> Optional[int]:
    match = re.search(r"\b(201[0-9]|202[0-5])\b", query)
    if match:
        return int(match.group(1))
    current_year = datetime.now().year
    if "this year" in query.lower():
        return current_year
    if "last year" in query.lower():
        return current_year - 1
    return None


def extract_crime_type(query: str) -> Optional[str]:
    crime_map = {
        "murder": "Murder", "theft": "Theft", "robbery": "Robbery",
        "rape": "Rape", "kidnapping": "Kidnapping", "dacoity": "Dacoity",
        "cybercrime": "Cybercrime", "drug": "Drug Trafficking",
        "burglary": "Burglary", "arson": "Arson", "vehicle theft": "Vehicle Theft",
        "dowry": "Dowry Death", "domestic violence": "Domestic Violence",
        "cheating": "Cheating", "forgery": "Forgery", "arms": "Arms Act Violation",
        "rioting": "Rioting", "hit and run": "Hit and Run",
        "sexual assault": "Sexual Assault", "attempt to murder": "Attempt to Murder",
    }
    query_lower = query.lower()
    for keyword, crime in crime_map.items():
        if keyword in query_lower:
            return crime
    return None


# --- SQL Query Builder ---
def build_sql_query(intent: str, query: str, db_conn) -> Tuple[str, list, str]:
    """Returns (sql, params, chart_type)"""
    district = extract_district(query)
    year = extract_year(query)
    crime_type = extract_crime_type(query)

    if intent == "count_crimes":
        if district:
            sql = """SELECT COUNT(*) as total_cases FROM fir_cases f
                     JOIN police_stations ps ON f.station_id = ps.station_id
                     JOIN districts d ON ps.district_id = d.district_id
                     WHERE LOWER(d.district_name) LIKE ?"""
            return sql, [f"%{district.lower()}%"], "number"
        elif crime_type:
            sql = "SELECT COUNT(*) as total_cases FROM fir_cases WHERE crime_type = ?"
            return sql, [crime_type], "number"
        elif year:
            sql = "SELECT COUNT(*) as total_cases FROM fir_cases WHERE strftime('%Y', date_of_incident) = ?"
            return sql, [str(year)], "number"
        else:
            return "SELECT COUNT(*) as total_cases FROM fir_cases", [], "number"

    elif intent == "crime_by_district":
        sql = """SELECT d.district_name, COUNT(*) as case_count
                 FROM fir_cases f
                 JOIN police_stations ps ON f.station_id = ps.station_id
                 JOIN districts d ON ps.district_id = d.district_id
                 GROUP BY d.district_name
                 ORDER BY case_count DESC LIMIT 20"""
        if year:
            sql = sql.replace("GROUP BY", f"WHERE strftime('%Y', f.date_of_incident) = '{year}' GROUP BY")
        return sql, [], "bar"

    elif intent == "crime_by_type":
        if district:
            sql = """SELECT f.crime_type, COUNT(*) as case_count
                     FROM fir_cases f
                     JOIN police_stations ps ON f.station_id = ps.station_id
                     JOIN districts d ON ps.district_id = d.district_id
                     WHERE LOWER(d.district_name) LIKE ?
                     GROUP BY f.crime_type ORDER BY case_count DESC"""
            return sql, [f"%{district.lower()}%"], "pie"
        else:
            sql = """SELECT crime_type, COUNT(*) as case_count FROM fir_cases
                     GROUP BY crime_type ORDER BY case_count DESC"""
            return sql, [], "pie"

    elif intent == "crime_trend":
        if crime_type:
            sql = """SELECT strftime('%Y', date_of_incident) as year, COUNT(*) as case_count
                     FROM fir_cases WHERE crime_type = ?
                     GROUP BY year ORDER BY year"""
            return sql, [crime_type], "line"
        elif district:
            sql = """SELECT strftime('%Y', f.date_of_incident) as year, COUNT(*) as case_count
                     FROM fir_cases f
                     JOIN police_stations ps ON f.station_id = ps.station_id
                     JOIN districts d ON ps.district_id = d.district_id
                     WHERE LOWER(d.district_name) LIKE ?
                     GROUP BY year ORDER BY year"""
            return sql, [f"%{district.lower()}%"], "line"
        else:
            sql = """SELECT strftime('%Y', date_of_incident) as year, COUNT(*) as case_count
                     FROM fir_cases GROUP BY year ORDER BY year"""
            return sql, [], "line"

    elif intent == "hotspot":
        sql = """SELECT ps.station_name, d.district_name, COUNT(*) as case_count,
                        AVG(f.severity_score) as avg_severity
                 FROM fir_cases f
                 JOIN police_stations ps ON f.station_id = ps.station_id
                 JOIN districts d ON ps.district_id = d.district_id
                 GROUP BY ps.station_id ORDER BY case_count DESC LIMIT 15"""
        return sql, [], "bar"

    elif intent == "accused_search":
        if "repeat" in query.lower() or "history" in query.lower():
            sql = """SELECT a.name, a.age, a.occupation, a.criminal_history, a.arrest_status,
                            COUNT(cr.record_id) as prior_cases
                     FROM accused a
                     LEFT JOIN criminal_records cr ON a.accused_id = cr.accused_id
                     WHERE a.criminal_history > 0
                     GROUP BY a.accused_id ORDER BY prior_cases DESC LIMIT 20"""
            return sql, [], "table"
        elif "gang" in query.lower():
            sql = """SELECT gang_affiliation, COUNT(*) as member_count,
                            AVG(age) as avg_age, COUNT(DISTINCT fir_id) as cases_involved
                     FROM accused WHERE gang_affiliation IS NOT NULL AND gang_affiliation != ''
                     GROUP BY gang_affiliation ORDER BY member_count DESC"""
            return sql, [], "table"
        elif "wanted" in query.lower() or "absconding" in query.lower():
            sql = """SELECT a.name, a.age, a.occupation, f.crime_type, d.district_name, a.gang_affiliation
                     FROM accused a
                     JOIN fir_cases f ON a.fir_id = f.fir_id
                     JOIN police_stations ps ON f.station_id = ps.station_id
                     JOIN districts d ON ps.district_id = d.district_id
                     WHERE a.arrest_status IN ('Wanted','Absconding')
                     ORDER BY f.severity_score DESC LIMIT 30"""
            return sql, [], "table"
        else:
            sql = """SELECT arrest_status, COUNT(*) as count FROM accused
                     GROUP BY arrest_status ORDER BY count DESC"""
            return sql, [], "pie"

    elif intent == "victim_stats":
        sql = """SELECT
                   CASE WHEN v.age < 18 THEN 'Minor (<18)'
                        WHEN v.age < 30 THEN 'Youth (18-29)'
                        WHEN v.age < 50 THEN 'Adult (30-49)'
                        ELSE 'Senior (50+)' END as age_group,
                   v.gender, COUNT(*) as victim_count
                 FROM victims v GROUP BY age_group, v.gender ORDER BY victim_count DESC"""
        return sql, [], "bar"

    elif intent == "case_status":
        sql = """SELECT status, COUNT(*) as case_count FROM fir_cases
                 GROUP BY status ORDER BY case_count DESC"""
        return sql, [], "pie"

    elif intent == "property_crime":
        sql = """SELECT property_type, COUNT(*) as items_stolen,
                        SUM(estimated_value) as total_value,
                        SUM(recovered) as recovered_count
                 FROM stolen_property GROUP BY property_type ORDER BY total_value DESC"""
        return sql, [], "bar"

    elif intent == "severity":
        sql = """SELECT f.fir_number, f.crime_type, f.date_of_incident, d.district_name,
                        f.severity_score, f.status
                 FROM fir_cases f
                 JOIN police_stations ps ON f.station_id = ps.station_id
                 JOIN districts d ON ps.district_id = d.district_id
                 WHERE f.severity_score >= 8 ORDER BY f.severity_score DESC LIMIT 25"""
        return sql, [], "table"

    elif intent == "predictive":
        sql = """SELECT strftime('%Y-%m', date_of_incident) as month,
                        crime_type, COUNT(*) as case_count
                 FROM fir_cases
                 WHERE date_of_incident >= date('now', '-24 months')
                 GROUP BY month, crime_type ORDER BY month, case_count DESC"""
        return sql, [], "line"

    elif intent == "network_analysis":
        sql = """SELECT a.name, a.gang_affiliation, COUNT(DISTINCT a.fir_id) as cases,
                        GROUP_CONCAT(DISTINCT f.crime_type) as crime_types,
                        a.criminal_history
                 FROM accused a
                 JOIN fir_cases f ON a.fir_id = f.fir_id
                 WHERE a.gang_affiliation IS NOT NULL
                 GROUP BY a.accused_id ORDER BY cases DESC LIMIT 30"""
        return sql, [], "network"

    elif intent == "officer_stats":
        sql = """SELECT o.name, o.rank, ps.station_name, d.district_name, o.cases_handled
                 FROM officers o
                 JOIN police_stations ps ON o.station_id = ps.station_id
                 JOIN districts d ON ps.district_id = d.district_id
                 ORDER BY o.cases_handled DESC LIMIT 20"""
        return sql, [], "table"

    else:
        # General fallback
        sql = """SELECT crime_type, COUNT(*) as case_count,
                        AVG(severity_score) as avg_severity
                 FROM fir_cases GROUP BY crime_type ORDER BY case_count DESC LIMIT 10"""
        return sql, [], "bar"


def execute_query(conn, sql: str, params: list) -> list:
    try:
        c = conn.cursor()
        c.execute(sql, params)
        columns = [desc[0] for desc in c.description]
        rows = c.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        return [{"error": str(e)}]


def _format_cell(value):
    """Format values for markdown table rendering."""
    if value is None:
        return "-"
    if isinstance(value, float):
        if abs(value - round(value)) < 1e-9:
            return f"{int(round(value))}"
        return f"{value:.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, str):
        return value.replace("|", "\\|")
    return str(value)


def _build_markdown_table(rows: list, columns: list, title: str, intro: str = "", max_rows: int = 10) -> str:
    """Convert a list of result rows into a markdown table."""
    if not rows:
        return title

    headers = [name for name, _ in columns]
    keys = [key for _, key in columns]
    lines = [f"**{title}**", ""]
    if intro:
        lines.append(intro)
        lines.append("")

    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in rows[:max_rows]:
        values = [_format_cell(row.get(key)) for key in keys]
        lines.append("| " + " | ".join(values) + " |")

    if len(rows) > max_rows:
        lines.append("")
        lines.append(f"_Showing first {max_rows} of {len(rows)} rows._")

    return "\n".join(lines)


def generate_natural_response(query: str, intents: list, results: list, chart_type: str) -> str:
    """
    Generate a human-readable response from query results.
    Builds the deterministic, explainable (SQL-backed) response first, then
    layers an optional AI-generated insight from Catalyst QuickML's
    GLM-4.7-Flash LLM on top -- giving investigators both the auditable data
    table AND a natural-language analytical summary.
    """
    base_response = _generate_deterministic_response(query, intents, results, chart_type)

    intent = intents[0] if intents else "general"
    if intent == "greeting" or not results or "error" in results[0]:
        return base_response

    # Summarize just enough data for the LLM prompt (keep payload small)
    data_summary = json.dumps(results[:15], default=str, ensure_ascii=False)
    insight = generate_llm_insight(query, data_summary)
    if insight:
        return f"{base_response}\n\n---\n🧠 **AI Insight (QuickML · GLM-4.7-Flash):** {insight}"
    return base_response


def _generate_deterministic_response(query: str, intents: list, results: list, chart_type: str) -> str:
    """Rule-based, explainable response builder (original implementation)."""
    if intents and intents[0] == "greeting":
        return "Hello! 👋 I’m KSP Crime Intelligence AI. I can help you explore crime trends, district-wise patterns, suspect details, hotspots, and case status. What would you like to know today?"

    if not results:
        return "I couldn't find any data matching your query. Please try a different question."

    if "error" in results[0]:
        return f"There was an error processing your query: {results[0]['error']}"

    district = extract_district(query)
    year = extract_year(query)
    crime_type = extract_crime_type(query)
    intent = intents[0] if intents else "general"

    if chart_type == "number":
        count = list(results[0].values())[0]
        context = ""
        if district:
            context = f" in **{district.title()}**"
        elif crime_type:
            context = f" for **{crime_type}**"
        elif year:
            context = f" in **{year}**"
        return f"📊 There are **{count:,}** total cases{context} in the KSP database."

    if intent == "crime_by_district":
        total = sum(r.get("case_count", 0) for r in results)
        intro = f"📊 Total across all districts: **{total:,}** cases"
        return _build_markdown_table(
            results,
            [("District", "district_name"), ("Cases", "case_count")],
            title="Crime Distribution by District",
            intro=intro,
        )

    if intent == "crime_by_type" or (chart_type == "pie" and "crime_type" in (results[0] if results else {})):
        intro = f"📍 {district.title()} district" if district else "📊 Top categories in the dataset"
        return _build_markdown_table(
            results,
            [("Crime Type", "crime_type"), ("Cases", "case_count")],
            title="Crime Type Breakdown",
            intro=intro,
        )

    if intent == "crime_trend":
        title = f"{crime_type} - Yearly Trend" if crime_type else "Crime Trend Analysis"
        intro = "📈 Year-wise incident count"
        return _build_markdown_table(
            results,
            [("Year", "year"), ("Cases", "case_count")],
            title=title,
            intro=intro,
        )

    if intent == "hotspot":
        intro = "⚠️ High-volume stations with average severity"
        return _build_markdown_table(
            results,
            [("Station", "station_name"), ("District", "district_name"), ("Cases", "case_count"), ("Avg Severity", "avg_severity")],
            title="Crime Hotspot Analysis",
            intro=intro,
        )

    if intent == "case_status":
        intro = "📋 Current status of registered cases"
        return _build_markdown_table(
            results,
            [("Status", "status"), ("Cases", "case_count")],
            title="Case Status Summary",
            intro=intro,
        )

    if intent == "accused_search":
        if results and "error" not in results[0]:
            columns = [("Field", "field"), ("Value", "value")]
            normalized_rows = []
            for r in results[:8]:
                for key, value in r.items():
                    if value is not None and value != "":
                        normalized_rows.append({"field": key, "value": value})
            return _build_markdown_table(
                normalized_rows,
                columns,
                title="Accused / Criminal Data",
                intro="📋 Key details from the matching records",
                max_rows=12,
            )

    if intent == "predictive":
        intro = "🔮 Historical pattern summary"
        return _build_markdown_table(
            results,
            [("Crime Type", "crime_type"), ("Cases", "case_count")],
            title="Predictive Crime Trend",
            intro=intro,
        )

    if intent == "network_analysis":
        intro = "🕸️ Key suspects and gang affiliations"
        return _build_markdown_table(
            results,
            [("Name", "name"), ("Gang", "gang_affiliation"), ("Cases", "cases"), ("Crime Types", "crime_types")],
            title="Criminal Network Analysis",
            intro=intro,
        )

    if intent == "property_crime":
        intro = "💰 Property loss and recovery summary"
        return _build_markdown_table(
            results,
            [("Property Type", "property_type"), ("Items Stolen", "items_stolen"), ("Value", "total_value"), ("Recovered", "recovered_count")],
            title="Stolen Property Analysis",
            intro=intro,
        )

    # Generic table response
    first_row = results[0]
    if "crime_type" in first_row and "case_count" in first_row:
        columns = [("Crime Type", "crime_type"), ("Cases", "case_count"), ("Avg Severity", "avg_severity")]
        return _build_markdown_table(results, columns, title="Query Results", intro="📋 Structured summary of the matching records")

    columns = [(key.replace("_", " ").title(), key) for key in first_row.keys() if key != "error"]
    return _build_markdown_table(results, columns, title="Query Results", intro="📋 Structured summary of the matching records")


def get_dashboard_stats(conn) -> dict:
    """Get key stats for the dashboard overview"""
    c = conn.cursor()
    stats = {}

    queries = {
        "total_cases": "SELECT COUNT(*) FROM fir_cases",
        "pending_cases": "SELECT COUNT(*) FROM fir_cases WHERE status = 'Pending Investigation'",
        "total_accused": "SELECT COUNT(*) FROM accused",
        "wanted_accused": "SELECT COUNT(*) FROM accused WHERE arrest_status IN ('Wanted', 'Absconding')",
        "total_victims": "SELECT COUNT(*) FROM victims",
        "solved_cases": "SELECT COUNT(*) FROM fir_cases WHERE status IN ('Convicted','Case Closed','Chargesheet Filed')",
        "total_stations": "SELECT COUNT(*) FROM police_stations",
        "total_districts": "SELECT COUNT(*) FROM districts",
    }

    for key, sql in queries.items():
        c.execute(sql)
        stats[key] = c.fetchone()[0]

    stats["clearance_rate"] = round(stats["solved_cases"] / max(stats["total_cases"], 1) * 100, 1)

    # Top crime type
    c.execute("SELECT crime_type, COUNT(*) as cnt FROM fir_cases GROUP BY crime_type ORDER BY cnt DESC LIMIT 1")
    row = c.fetchone()
    stats["top_crime"] = row[0] if row else "N/A"

    # Recent cases (last 30 days of data)
    c.execute("""SELECT COUNT(*) FROM fir_cases WHERE date_of_fir >= date('now', '-30 days')
                 OR date_of_fir >= (SELECT date(MAX(date_of_fir), '-30 days') FROM fir_cases)""")
    stats["recent_cases"] = c.fetchone()[0]

    return stats
