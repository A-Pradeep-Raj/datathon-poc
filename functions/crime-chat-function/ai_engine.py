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

# RAG (Retrieval-Augmented Generation) over the Knowledge Base -- lets
# officers query uploaded SOP/policy documents in natural language and get
# grounded answers with source citations.
_QUICKML_RAG_ENDPOINT = os.environ.get(
    "QUICKML_RAG_ENDPOINT",
    "https://console.catalyst.zoho.in/quickml/v1/project/51742000000028001/rag/answer",
)
_QUICKML_KB_DOC_IDS = [
    d.strip() for d in os.environ.get("QUICKML_KB_DOC_IDS", "").split(",") if d.strip()
]

# Custom QuickML pipeline endpoint for crime-hotspot anomaly/fraud detection
# (AutoML classification model trained on per-station case statistics).
_QUICKML_ANOMALY_ENDPOINT = os.environ.get(
    "QUICKML_ANOMALY_ENDPOINT",
    "https://api.catalyst.zoho.in/quickml/v1/project/51742000000028001/endpoints/predict",
)
_QUICKML_ANOMALY_ENDPOINT_KEY = os.environ.get("QUICKML_ANOMALY_ENDPOINT_KEY")

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


def generate_llm_insight(user_query: str, data_summary: str, language: str = "en") -> Optional[str]:
    """
    Call Catalyst QuickML's GLM-4.7-Flash LLM Serving endpoint to produce a
    short natural-language insight/summary grounded in the SQL results.
    Returns None if QuickML is not configured or the call fails (caller
    should gracefully fall back to the deterministic response).

    `language` ("en" or "kn") controls the language of the generated
    insight itself, so Kannada conversations get a fully Kannada reply
    instead of an English insight bolted onto a translated body.

    Note: the GLM endpoint's safety layer rejects requests that use the
    "system" role (treats it as a prompt-injection attempt), so instructions
    are folded into the "user" message instead.
    """
    token = _get_quickml_access_token()
    if not token:
        return None

    language_instruction = (
        "Write your ENTIRE reply in natural, fluent Kannada (ಕನ್ನಡ script). "
        "Do not use English words except for proper nouns/numbers that don't "
        "translate naturally. "
        if language == "kn" else ""
    )
    prompt = (
        "You are KRIME AI, a crime-intelligence assistant for Karnataka State Police. "
        "Based ONLY on the data below, write a concise (2-3 sentence) analytical insight "
        "for an investigating officer. Do not invent numbers not present in the data. "
        f"{language_instruction}"
        "IMPORTANT: Output ONLY the finished 2-3 sentence insight as plain prose. "
        "Do NOT show your thinking, drafts, numbered steps, or any text other than "
        "the finished insight itself. Start your reply directly with the insight text.\n\n"
        f"Officer's question: {user_query}\n\n"
        f"Query result data:\n{data_summary}\n\n"
        "ANSWER_ONLY>>>"
    )

    try:
        # See the matching NOTE in translate_response_to_kannada() -- Zoho
        # Advanced I/O functions have a hard 30-second execution limit, so
        # this call must leave enough headroom for the rest of the request
        # (and for a possible translation call afterwards for Kannada).
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
            timeout=20,
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


# --- English -> Kannada phrase dictionary for full-response translation ---
# NOTE: We intentionally do NOT use the QuickML GLM LLM to translate the
# full response body. That model is a "thinking" variant which emits a long
# internal reasoning trace before every answer -- measured at 20-30+ seconds
# PER CALL regardless of how short the input is, and growing further with
# table size. Zoho Catalyst Advanced I/O functions have a HARD 30-second
# execution limit for the entire request (platform-enforced, independent of
# the catalyst-config.json "timeout" value), so a single LLM translation
# call alone can exceed it -- and did in production, causing Catalyst's
# gateway to kill the function and return its own error shape (missing our
# "success"/"error" keys), which the frontend rendered as "Error: undefined".
#
# Instead we do a fast, deterministic phrase/word substitution translation
# (mirroring the existing KANNADA_KEYWORD_MAP used for the reverse
# direction). This has ZERO network latency and can never time out, while
# still ensuring the reply is genuinely in Kannada. Numbers, markdown
# formatting (**bold**, | tables |, emoji) and proper nouns (district/crime
# type names already shown in English data) are left untouched.
_ENGLISH_TO_KANNADA_PHRASES = [
    # NOTE: These are applied longest-phrase-first (see
    # translate_response_to_kannada), so exact list order here does not
    # matter -- a full sentence like "Structured summary of the matching
    # records" will always be matched/replaced before the short generic
    # words "of"/"in"/"cases" that also appear inside it. This avoids the
    # earlier bug where short words replaced first fragmented longer
    # phrases (e.g. "of" -> Kannada leaving "Structured summary ರಲ್ಲಿ the
    # matching records" instead of the full translated sentence).
    ("Continuing from earlier in this chat — using", "ಈ ಸಂಭಾಷಣೆಯಲ್ಲಿ ಮೊದಲೇ ಬಂದ ಮಾಹಿತಿಯನ್ನು ಬಳಸಿ —"),
    ("recorded in the KSP database", "KSP ಡೇಟಾಬೇಸ್‌ನಲ್ಲಿ ದಾಖಲಾಗಿದೆ"),
    ("in the KSP database", "KSP ಡೇಟಾಬೇಸ್‌ನಲ್ಲಿ"),
    ("There are", "ಇವೆ"),
    ("total number of", "ಒಟ್ಟು ಸಂಖ್ಯೆ"),
    ("Total across all districts", "ಎಲ್ಲಾ ಜಿಲ್ಲೆಗಳಲ್ಲಿ ಒಟ್ಟು"),
    ("total cases", "ಒಟ್ಟು ಪ್ರಕರಣಗಳು"),
    ("Showing first", "ಮೊದಲ"),
    ("in the dataset", "ಡೇಟಾದಲ್ಲಿ"),
    ("police stations", "ಪೊಲೀಸ್ ಠಾಣೆಗಳು"),
    ("hotspot stations", "ಹಾಟ್‌ಸ್ಪಾಟ್ ಠಾಣೆಗಳು"),
    ("high-severity cases", "ಹೆಚ್ಚಿನ ತೀವ್ರತೆಯ ಪ್ರಕರಣಗಳು"),
    ("severity score", "ತೀವ್ರತೆ ಅಂಕ"),
    ("gang/network affiliation", "ಗ್ಯಾಂಗ್/ನೆಟ್‌ವರ್ಕ್ ಸಂಬಂಧ"),
    ("gang affiliation", "ಗ್ಯಾಂಗ್ ಸಂಬಂಧ"),
    ("prior criminal history", "ಹಿಂದಿನ ಅಪರಾಧ ಇತಿಹಾಸ"),
    ("Wanted / Absconding", "ತಲೆಮರೆಸಿಕೊಂಡಿರುವ / ವಾಂಟೆಡ್"),
    ("with status", "ಸ್ಥಿತಿಯೊಂದಿಗೆ"),
    ("stolen-property items", "ಕಳ್ಳತನವಾದ ವಸ್ತುಗಳು"),
    ("rows", "ಸಾಲುಗಳು"),
    ("cases", "ಪ್ರಕರಣಗಳು"),
    ("Cases", "ಪ್ರಕರಣಗಳು"),
    ("districts", "ಜಿಲ್ಲೆಗಳು"),
    ("district", "ಜಿಲ್ಲೆ"),
    ("District", "ಜಿಲ್ಲೆ"),
    ("accused", "ಆರೋಪಿಗಳು"),
    ("officers", "ಅಧಿಕಾರಿಗಳು"),
    ("recorded", "ದಾಖಲಾದ"),
    ("stolen", "ಕಳ್ಳತನವಾದ"),
    ("items", "ವಸ್ತುಗಳು"),
    ("Hello!", "ನಮಸ್ಕಾರ!"),
    ("I’m KSP Crime Intelligence AI.", "ನಾನು KSP ಕ್ರೈಂ ಇಂಟೆಲಿಜೆನ್ಸ್ AI."),
    ("I can help you explore crime trends, district-wise patterns, suspect details, hotspots, and case status.",
     "ಅಪರಾಧ ಪ್ರವೃತ್ತಿಗಳು, ಜಿಲ್ಲಾವಾರು ಮಾದರಿಗಳು, ಆರೋಪಿಗಳ ವಿವರಗಳು, ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳು ಮತ್ತು ಪ್ರಕರಣದ ಸ್ಥಿತಿಯನ್ನು ಅನ್ವೇಷಿಸಲು ನಾನು ನಿಮಗೆ ಸಹಾಯ ಮಾಡಬಲ್ಲೆ."),
    ("What would you like to know today?", "ಇಂದು ನೀವು ಏನು ತಿಳಿದುಕೊಳ್ಳಲು ಬಯಸುತ್ತೀರಿ?"),
    ("I couldn't find any data matching your query. Please try a different question.",
     "ನಿಮ್ಮ ಪ್ರಶ್ನೆಗೆ ಹೊಂದುವ ಯಾವುದೇ ಡೇಟಾ ಸಿಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಬೇರೆ ಪ್ರಶ್ನೆಯನ್ನು ಪ್ರಯತ್ನಿಸಿ."),
    ("There was an error processing your query:", "ನಿಮ್ಮ ಪ್ರಶ್ನೆಯನ್ನು ಪ್ರಕ್ರಿಯೆಗೊಳಿಸುವಲ್ಲಿ ದೋಷ ಸಂಭವಿಸಿದೆ:"),
    ("Query Results", "ಪ್ರಶ್ನೆಯ ಫಲಿತಾಂಶಗಳು"),
    ("Structured summary of the matching records", "ಹೊಂದಾಣಿಕೆಯಾಗುವ ದಾಖಲೆಗಳ ಸಂಕ್ಷಿಪ್ತ ವಿವರ"),
    ("Crime Distribution by District", "ಜಿಲ್ಲಾವಾರು ಅಪರಾಧ ಹಂಚಿಕೆ"),
    ("Crime Type Breakdown", "ಅಪರಾಧ ಪ್ರಕಾರದ ವಿಭಜನೆ"),
    ("Top categories in the dataset", "ಡೇಟಾದಲ್ಲಿ ಪ್ರಮುಖ ವರ್ಗಗಳು"),
    ("Crime Trend Analysis", "ಅಪರಾಧ ಪ್ರವೃತ್ತಿ ವಿಶ್ಲೇಷಣೆ"),
    ("Yearly Trend", "ವಾರ್ಷಿಕ ಪ್ರವೃತ್ತಿ"),
    ("Year-wise incident count", "ವರ್ಷವಾರು ಘಟನೆಗಳ ಎಣಿಕೆ"),
    ("Crime Hotspot Analysis", "ಅಪರಾಧ ಹಾಟ್‌ಸ್ಪಾಟ್ ವಿಶ್ಲೇಷಣೆ"),
    ("High-volume stations with average severity", "ಸರಾಸರಿ ತೀವ್ರತೆಯೊಂದಿಗೆ ಹೆಚ್ಚಿನ-ಪ್ರಮಾಣದ ಠಾಣೆಗಳು"),
    ("Victim Demographics", "ಬಲಿಪಶುಗಳ ಜನಸಂಖ್ಯಾಶಾಸ್ತ್ರ"),
    ("Age-group and gender breakdown of recorded victims", "ದಾಖಲಾದ ಬಲಿಪಶುಗಳ ವಯೋಗುಂಪು ಮತ್ತು ಲಿಂಗ ವಿಭಜನೆ"),
    ("High-Severity Cases", "ಹೆಚ್ಚಿನ ತೀವ್ರತೆಯ ಪ್ರಕರಣಗಳು"),
    ("most severe first", "ಅತಿ ತೀವ್ರವಾದವು ಮೊದಲು"),
    ("Officer Performance", "ಅಧಿಕಾರಿ ಸಾಧನೆ"),
    ("Officers ranked by number of cases handled", "ನಿರ್ವಹಿಸಿದ ಪ್ರಕರಣಗಳ ಸಂಖ್ಯೆಯ ಆಧಾರದ ಮೇಲೆ ಅಧಿಕಾರಿಗಳ ಶ್ರೇಣಿ"),
    ("Case Status Summary", "ಪ್ರಕರಣದ ಸ್ಥಿತಿ ಸಾರಾಂಶ"),
    ("Current status of registered cases", "ದಾಖಲಾದ ಪ್ರಕರಣಗಳ ಪ್ರಸ್ತುತ ಸ್ಥಿತಿ"),
    ("Accused / Criminal Data", "ಆರೋಪಿ / ಅಪರಾಧಿ ಡೇಟಾ"),
    ("Matching records", "ಹೊಂದಾಣಿಕೆಯಾಗುವ ದಾಖಲೆಗಳು"),
    ("Predictive Crime Trend", "ಭವಿಷ್ಯಸೂಚಕ ಅಪರಾಧ ಪ್ರವೃತ್ತಿ"),
    ("Historical pattern summary", "ಐತಿಹಾಸಿಕ ಮಾದರಿ ಸಾರಾಂಶ"),
    ("Criminal Network Analysis", "ಅಪರಾಧಿ ನೆಟ್‌ವರ್ಕ್ ವಿಶ್ಲೇಷಣೆ"),
    ("Key suspects and gang affiliations", "ಪ್ರಮುಖ ಶಂಕಿತರು ಮತ್ತು ಗ್ಯಾಂಗ್ ಸಂಬಂಧಗಳು"),
    ("Stolen Property Analysis", "ಕಳ್ಳತನ ಆಸ್ತಿ ವಿಶ್ಲೇಷಣೆ"),
    ("loss and recovery summary", "ನಷ್ಟ ಮತ್ತು ವಸೂಲಿ ಸಾರಾಂಶ"),
    ("Property loss and recovery summary", "ಆಸ್ತಿ ನಷ್ಟ ಮತ್ತು ವಸೂಲಿ ಸಾರಾಂಶ"),
    ("Cases with severity score ≥ 8, most severe first", "ತೀವ್ರತೆ ಅಂಕ ≥ 8 ಇರುವ ಪ್ರಕರಣಗಳು, ಅತಿ ತೀವ್ರವಾದವು ಮೊದಲು"),

    # --- Markdown table column headers (see _build_markdown_table calls
    # and the key.replace("_"," ").title() dynamic-column builders) ---
    ("District Name", "ಜಿಲ್ಲೆಯ ಹೆಸರು"),
    ("Crime Type", "ಅಪರಾಧ ಪ್ರಕಾರ"),
    ("Year", "ವರ್ಷ"),
    ("Station", "ಠಾಣೆ"),
    ("Avg Severity", "ಸರಾಸರಿ ತೀವ್ರತೆ"),
    ("Avg Age", "ಸರಾಸರಿ ವಯಸ್ಸು"),
    ("Age Group", "ವಯೋಗುಂಪು"),
    ("Gender", "ಲಿಂಗ"),
    ("Victims", "ಬಲಿಪಶುಗಳು"),
    ("FIR Number", "FIR ಸಂಖ್ಯೆ"),
    ("Date", "ದಿನಾಂಕ"),
    ("Severity", "ತೀವ್ರತೆ"),
    ("Status", "ಸ್ಥಿತಿ"),
    ("Rank", "ಶ್ರೇಣಿ"),
    ("Cases Handled", "ನಿರ್ವಹಿಸಿದ ಪ್ರಕರಣಗಳು"),
    ("Gang Affiliation", "ಗ್ಯಾಂಗ್ ಸಂಬಂಧ"),
    ("Gang", "ಗ್ಯಾಂಗ್"),
    ("Crime Types", "ಅಪರಾಧ ಪ್ರಕಾರಗಳು"),
    ("Property Type", "ಆಸ್ತಿ ಪ್ರಕಾರ"),
    ("Items Stolen", "ಕಳ್ಳತನವಾದ ವಸ್ತುಗಳು"),
    ("Value", "ಮೌಲ್ಯ"),
    ("Recovered", "ವಸೂಲಿಯಾದ"),
    ("Name", "ಹೆಸರು"),
    ("Age", "ವಯಸ್ಸು"),
    ("Occupation", "ಉದ್ಯೋಗ"),
    ("Criminal History", "ಅಪರಾಧ ಇತಿಹಾಸ"),
    ("Arrest Status", "ಬಂಧನ ಸ್ಥಿತಿ"),
    ("Arrest Date", "ಬಂಧನ ದಿನಾಂಕ"),
    ("Prior Cases", "ಹಿಂದಿನ ಪ್ರಕರಣಗಳು"),
    ("Member Count", "ಸದಸ್ಯರ ಸಂಖ್ಯೆ"),
    ("Cases Involved", "ಒಳಗೊಂಡ ಪ್ರಕರಣಗಳು"),
    ("Count", "ಸಂಖ್ಯೆ"),
    ("Alias", "ಇತರ ಹೆಸರು"),
    ("Address", "ವಿಳಾಸ"),
    ("Contact Number", "ಸಂಪರ್ಕ ಸಂಖ್ಯೆ"),
    ("Aadhaar Number", "ಆಧಾರ್ ಸಂಖ್ಯೆ"),
    ("Nationality", "ರಾಷ್ಟ್ರೀಯತೆ"),

    # --- Crime type values (CRIME_TYPES in synthetic_data.py) -- these
    # appear as literal cell values in almost every table/count response,
    # so translating them (rather than just the column header) is what
    # makes the biggest visible difference for "still shows English" -- ---
    ("Attempt to Murder", "ಕೊಲೆ ಯತ್ನ"),
    ("Murder", "ಕೊಲೆ"),
    ("Robbery", "ದರೋಡೆ"),
    ("Dacoity", "ಡಕಾಯಿತಿ"),
    ("Theft", "ಕಳ್ಳತನ"),
    ("Burglary", "ಮನೆಗಳ್ಳತನ"),
    ("Vehicle Theft", "ವಾಹನ ಕಳ್ಳತನ"),
    ("Kidnapping", "ಅಪಹರಣ"),
    ("Sexual Assault", "ಲೈಂಗಿಕ ದೌರ್ಜನ್ಯ"),
    ("Rape", "ಅತ್ಯಾಚಾರ"),
    ("Dowry Death", "ವರದಕ್ಷಿಣೆ ಸಾವು"),
    ("Domestic Violence", "ಕೌಟುಂಬಿಕ ದೌರ್ಜನ್ಯ"),
    ("Cheating", "ವಂಚನೆ"),
    ("Forgery", "ನಕಲಿ ದಾಖಲೆ"),
    ("Cybercrime", "ಸೈಬರ್ ಅಪರಾಧ"),
    ("Drug Trafficking", "ಮಾದಕ ದ್ರವ್ಯ ಸಾಗಣೆ"),
    ("Arms Act Violation", "ಶಸ್ತ್ರಾಸ್ತ್ರ ಕಾಯ್ದೆ ಉಲ್ಲಂಘನೆ"),
    ("Rioting", "ಗಲಭೆ"),
    ("Arson", "ಬೆಂಕಿ ಹಚ್ಚುವಿಕೆ"),
    ("Hit and Run", "ಡಿಕ್ಕಿ ಹೊಡೆದು ಪರಾರಿ"),

    # --- Officer rank values (OFFICER_RANKS in synthetic_data.py) ---
    ("Deputy Superintendent", "ಉಪ ಅಧೀಕ್ಷಕ"),
    ("Circle Inspector", "ವೃತ್ತ ಇನ್ಸ್‌ಪೆಕ್ಟರ್"),
    ("Sub Inspector", "ಸಬ್ ಇನ್ಸ್‌ಪೆಕ್ಟರ್"),
    ("Head Constable", "ಹೆಡ್ ಕಾನ್ಸ್ಟೇಬಲ್"),
    ("Inspector", "ಇನ್ಸ್‌ಪೆಕ್ಟರ್"),
    ("Constable", "ಕಾನ್ಸ್ಟೇಬಲ್"),
    ("ASI", "ಎಎಸ್ಐ"),

    # --- Gang affiliation values (assigned in synthetic_data.py) ---
    ("Organized Gang", "ಸಂಘಟಿತ ಗ್ಯಾಂಗ್"),
    ("Rowdy Sheeter", "ರೌಡಿ ಶೀಟರ್"),
    ("Known Criminal", "ಪರಿಚಿತ ಅಪರಾಧಿ"),

    # --- Stolen-property type values (assigned in synthetic_data.py /
    # extract_property_type()) ---
    ("Mobile Phone", "ಮೊಬೈಲ್ ಫೋನ್"),
    ("Jewellery", "ಆಭರಣ"),
    ("Electronics", "ಎಲೆಕ್ಟ್ರಾನಿಕ್ಸ್"),
    ("Documents", "ದಾಖಲೆಗಳು"),
    ("Vehicle", "ವಾಹನ"),
    ("Cash", "ನಗದು"),

    # --- Data values that appear inside table cells / bolded status text
    # (fir_cases.status, accused.arrest_status, victims.gender, and the
    # literal age-group labels built in the victim_stats SQL CASE) ---
    ("Pending Investigation", "ತನಿಖೆ ಬಾಕಿ"),
    ("Under Investigation", "ತನಿಖೆಯಲ್ಲಿ"),
    ("Chargesheet Filed", "ಚಾರ್ಜ್‌ಶೀಟ್ ಸಲ್ಲಿಸಲಾಗಿದೆ"),
    ("Trial in Progress", "ವಿಚಾರಣೆ ನಡೆಯುತ್ತಿದೆ"),
    ("Convicted", "ಶಿಕ್ಷೆಯಾಗಿದೆ"),
    ("Acquitted", "ಬಿಡುಗಡೆಯಾಗಿದೆ"),
    ("Case Closed", "ಪ್ರಕರಣ ಮುಕ್ತಾಯ"),
    ("Absconding", "ತಲೆಮರೆಸಿಕೊಂಡಿರುವ"),
    ("Arrested", "ಬಂಧಿತ"),
    ("Wanted", "ವಾಂಟೆಡ್"),
    ("Male", "ಪುರುಷ"),
    ("Female", "ಮಹಿಳೆ"),
    ("Minor (<18)", "ಮಕ್ಕಳು (18ಕ್ಕಿಂತ ಕಡಿಮೆ)"),
    ("Youth (18-29)", "ಯುವಕರು (18-29)"),
    ("Adult (30-49)", "ವಯಸ್ಕರು (30-49)"),
    ("Senior (50+)", "ಹಿರಿಯರು (50+)"),

    # --- Victim-count subject phrases (see _extract_victim_filter) ---
    ("minor/child victims (under 18)", "18 ವರ್ಷದೊಳಗಿನ ಮಕ್ಕಳ ಬಲಿಪಶುಗಳು"),
    ("female victims", "ಮಹಿಳಾ ಬಲಿಪಶುಗಳು"),
    ("male victims", "ಪುರುಷ ಬಲಿಪಶುಗಳು"),
    ("victims", "ಬಲಿಪಶುಗಳು"),

    # --- Connector words/phrases used to assemble count-style sentences
    # (see _build_count_response) -- these are intentionally short/generic
    # but are always applied AFTER all longer phrases above (translation
    # sorts by descending phrase length), so they only ever affect
    # leftover connective English words instead of fragmenting a longer
    # phrase that was meant to be translated as a whole. ---
    ("who are still", "ಇನ್ನೂ"),
    ("with a recorded", "ದಾಖಲಾದ"),
    ("with a", "ಹೊಂದಿರುವ"),
    ("crime type", "ಅಪರಾಧ ಪ್ರಕಾರ"),
    ("year", "ವರ್ಷ"),
    ("of", "ದ"),
    ("in", "ನಲ್ಲಿ"),
]


def translate_response_to_kannada(text: str) -> str:
    """
    Translate a finished English response (deterministic data summary,
    tables, etc.) into Kannada using a fast, deterministic phrase-dictionary
    substitution -- NOT an LLM call (see comment above
    _ENGLISH_TO_KANNADA_PHRASES for why). This guarantees the translation
    step has zero network latency and can never cause a request timeout,
    while still ensuring the reply reads in Kannada. Markdown formatting,
    numbers, and emoji are preserved as-is; only known English phrases are
    substituted for their Kannada equivalents.
    """
    if not text:
        return text
    translated = text
    # Always apply the LONGEST phrases first, regardless of dict order --
    # this guarantees a full sentence like "Structured summary of the
    # matching records" gets matched/replaced whole before the short
    # generic word "of" (which also appears standalone in the dict) can
    # fragment it into a partial translation.
    ordered_phrases = sorted(_ENGLISH_TO_KANNADA_PHRASES, key=lambda pair: len(pair[0]), reverse=True)
    for english, kannada in ordered_phrases:
        # Word-boundary-safe replace for short/common single words (e.g.
        # "cases", "district") to avoid mangling substrings inside other
        # words or markdown table separators; longer phrases (multi-word)
        # are replaced as plain substrings since they're specific enough.
        if len(english.split()) == 1 and len(english) <= 10:
            translated = re.sub(rf"(?<![^\W_]){re.escape(english)}(?![^\W_])", kannada, translated)
        else:
            translated = translated.replace(english, kannada)
    return translated


def query_rag(question: str, document_ids: Optional[List[str]] = None) -> dict:
    """
    Query Catalyst QuickML's RAG (Retrieval-Augmented Generation) service
    over documents uploaded to the Knowledge Base (e.g. SOP manuals, policy
    guidelines). Returns a dict with the grounded answer plus source
    citations so officers can verify where the information came from.

    Returns: {"success": bool, "answer": str, "sources": [ {title, snippet,
    document_id}, ... ], "error": str|None}
    """
    token = _get_quickml_access_token()
    if not token:
        return {
            "success": False,
            "answer": None,
            "sources": [],
            "error": "QuickML RAG is not configured on this deployment.",
        }

    doc_ids = document_ids if document_ids else _QUICKML_KB_DOC_IDS

    try:
        resp = _requests.post(
            _QUICKML_RAG_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Zoho-oauthtoken {token}",
                "CATALYST-ORG": _QUICKML_ORG_ID,
            },
            json={"query": question, "documents": doc_ids} if doc_ids else {"query": question},
            # Zoho Advanced I/O functions have a hard 30-second execution
            # limit for the WHOLE request -- leave headroom below that so a
            # slow RAG call fails gracefully (caught below) instead of the
            # platform killing the function and returning a mismatched
            # error shape to the frontend.
            timeout=22,
        )
        data = resp.json()
        if data.get("status") != "success":
            return {
                "success": False,
                "answer": None,
                "sources": [],
                "error": data.get("message") or "RAG query failed.",
            }

        sources = []
        for node in data.get("retrieved_nodes", [])[:5]:
            content = (node.get("content") or "").strip()
            sources.append({
                "title": node.get("document_title") or "Untitled document",
                "document_id": node.get("document_id"),
                "snippet": (content[:280] + "…") if len(content) > 280 else content,
            })

        return {
            "success": True,
            "answer": (data.get("response") or "").strip(),
            "sources": sources,
            "error": None,
        }
    except Exception as e:
        return {"success": False, "answer": None, "sources": [], "error": str(e)}


def predict_station_anomaly(station_stats: dict) -> dict:
    """
    Call the custom QuickML pipeline endpoint (AutoML classification model) to
    predict whether a police station's crime statistics indicate an anomalous
    hotspot (potential under-reporting, resource strain, or unusual activity
    spike) requiring investigative/administrative attention.

    station_stats must contain: station_id, station_name, district_name,
    case_count, avg_severity, pending_count, high_severity_count.

    Returns: {"success": bool, "is_anomaly": bool|None, "error": str|None}
    """
    token = _get_quickml_access_token()
    if not token or not _QUICKML_ANOMALY_ENDPOINT_KEY:
        return {"success": False, "is_anomaly": None, "error": "Anomaly detection endpoint is not configured."}

    required = ["station_id", "station_name", "district_name", "case_count",
                "avg_severity", "pending_count", "high_severity_count"]
    missing = [k for k in required if k not in station_stats]
    if missing:
        return {"success": False, "is_anomaly": None, "error": f"Missing fields: {', '.join(missing)}"}

    try:
        resp = _requests.post(
            _QUICKML_ANOMALY_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "X-QUICKML-ENDPOINT-KEY": _QUICKML_ANOMALY_ENDPOINT_KEY,
                "Authorization": f"Zoho-oauthtoken {token}",
                "CATALYST-ORG": _QUICKML_ORG_ID,
                "Environment": "Development",
            },
            json={"data": {k: station_stats[k] for k in required}},
            timeout=20,
        )
        data = resp.json()
        if data.get("status") != "success":
            return {"success": False, "is_anomaly": None, "error": data.get("message") or "Prediction failed."}
        result = data.get("result", [None])[0]
        return {"success": True, "is_anomaly": bool(result), "error": None}
    except Exception as e:
        return {"success": False, "is_anomaly": None, "error": str(e)}


def scan_stations_for_anomalies(conn) -> list:
    """
    Compute per-station crime statistics from the live database and run each
    station through the QuickML anomaly-detection endpoint, returning the
    list of stations flagged as anomalous hotspots.
    """
    c = conn.cursor()
    c.execute("""
        SELECT ps.station_id, ps.station_name, d.district_name,
               COUNT(*) as case_count,
               AVG(f.severity_score) as avg_severity,
               SUM(CASE WHEN f.status='Pending Investigation' THEN 1 ELSE 0 END) as pending_count,
               SUM(CASE WHEN f.severity_score >= 8 THEN 1 ELSE 0 END) as high_severity_count
        FROM fir_cases f
        JOIN police_stations ps ON f.station_id = ps.station_id
        JOIN districts d ON ps.district_id = d.district_id
        GROUP BY ps.station_id
        ORDER BY case_count DESC
    """)
    cols = [d[0] for d in c.description]
    rows = [dict(zip(cols, r)) for r in c.fetchall()]

    flagged = []
    for row in rows:
        row["avg_severity"] = round(row["avg_severity"] or 0, 2)
        result = predict_station_anomaly(row)
        if result["success"] and result["is_anomaly"]:
            flagged.append(row)
    return flagged


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
        r"how many districts?",
        r"number of districts?",
    ],
    "crime_by_type": [
        r"(murder|theft|robbery|rape|cybercrime|drug|dacoity|kidnapping|arson|burglary)(\s+(cases?|crimes?|statistics))?",
        r"what about (murder|theft|robbery|rape|cybercrime|drug|dacoity|kidnapping|arson|burglary)",
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

    if not detected:
        return ["general"]

    # "count_crimes" only recognizes the generic phrasing "how many
    # crimes/cases" -- it says nothing about *which* cases. If a more
    # specific topic intent (case_status, property_crime, severity,
    # accused_search, victim_stats, hotspot, officer_stats) ALSO matched,
    # that one carries the actual filter (e.g. "pending", "mobile phone",
    # "wanted") and must win as intents[0] -- otherwise e.g. "how many
    # cases are pending?" would be answered as "how many cases total" and
    # silently drop the "pending" filter.
    #
    # "crime_by_district" is handled separately: it should only outrank
    # count_crimes when the query has NO specific district name (e.g. "how
    # many districts are there?") -- count_crimes already resolves a named
    # district (e.g. "crimes in Mysuru?") correctly via extract_district(),
    # so demoting it there would wrongly switch to counting districts.
    if "count_crimes" in detected and len(detected) > 1:
        demotable = {"case_status", "property_crime", "severity", "accused_search",
                     "victim_stats", "hotspot", "officer_stats", "network_analysis"}
        more_specific = [i for i in detected if i in demotable]
        if "crime_by_district" in detected and extract_district(query) is None:
            more_specific.append("crime_by_district")
        if more_specific:
            remaining = [i for i in detected if i not in more_specific and i != "count_crimes"]
            detected = more_specific + remaining + ["count_crimes"]

    return detected


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


def extract_case_status(query: str) -> Optional[str]:
    """Map phrasing like 'pending', 'chargesheet', 'convicted' to the exact
    status value stored in fir_cases.status, so status-specific questions
    (e.g. 'how many cases are pending?') filter correctly instead of
    silently returning a full breakdown or an unfiltered total."""
    status_map = {
        "pending investigation": "Pending Investigation",
        "pending": "Pending Investigation",
        "under investigation": "Under Investigation",
        "chargesheet": "Chargesheet Filed",
        "charge sheet": "Chargesheet Filed",
        "trial": "Trial in Progress",
        "convicted": "Convicted",
        "conviction": "Convicted",
        "acquitted": "Acquitted",
        "case closed": "Case Closed",
        "closed": "Case Closed",
        "solved": "Case Closed",
    }
    query_lower = query.lower()
    for keyword, status in status_map.items():
        if keyword in query_lower:
            return status
    return None


def extract_property_type(query: str) -> Optional[str]:
    """Detect a specific stolen-property category mentioned in the query."""
    property_map = {
        "mobile phone": "Mobile Phone", "mobile": "Mobile Phone", "phone": "Mobile Phone",
        "cash": "Cash", "jewellery": "Jewellery", "jewelry": "Jewellery",
        "vehicle": "Vehicle", "electronics": "Electronics", "documents": "Documents",
    }
    query_lower = query.lower()
    for keyword, ptype in property_map.items():
        if keyword in query_lower:
            return ptype
    return None


def _extract_victim_filter(query: str) -> Tuple[Optional[str], str]:
    """Return (sql_where_fragment, human_subject) for victim-count queries
    that mention a specific demographic (female/male/child)."""
    query_lower = query.lower()
    if "female" in query_lower:
        return "v.gender = 'Female'", "female victims"
    if "male" in query_lower:
        return "v.gender = 'Male'", "male victims"
    if "child" in query_lower or "minor" in query_lower:
        return "v.age < 18", "minor/child victims (under 18)"
    return None, "victims"


def detect_response_shape(query: str) -> str:
    """
    Classify what SHAPE of answer the user expects, independent of the topic
    `intent`. This is what lets "How many accused are wanted?" return a
    single number while "List the wanted accused" returns a table, even
    though both trigger the exact same `accused_search` intent -- without
    this, every intent branch has to guess and often defaults to whichever
    shape was hardcoded, producing answers that don't match the question.

    Returns "count" for how-many/total/number-of style questions, else
    "detail" (list/breakdown -- each intent already renders these as a
    properly-columned markdown table or chart).
    """
    if re.search(r"how many|how much|total number|number of|count of|what'?s the (total|count)", query.lower()):
        return "count"
    return "detail"


# --- Context-aware conversation helpers ---

# Phrases that signal the user wants to start a fresh topic, so any
# carried-over district/year/crime_type from the previous turn should be
# discarded instead of bleeding into an unrelated question.
_RESET_PHRASES = [
    "start over", "new question", "never mind", "nevermind", "forget that",
    "forget it", "reset", "different topic", "new topic", "change topic",
    "unrelated question", "clear context",
]

# Which resolved entities are actually consumed by build_sql_query for a
# given intent -- used to decide whether it's worth telling the user that
# context was carried over from earlier in the conversation.
_INTENT_RELEVANT_ENTITIES = {
    "count_crimes": {"district", "crime_type", "year"},
    "crime_by_district": {"year"},
    "crime_by_type": {"district"},
    "crime_trend": {"crime_type", "district"},
}


def _is_context_reset_request(query: str) -> bool:
    """True if the user explicitly signals they want to drop prior context."""
    q = query.lower()
    return any(phrase in q for phrase in _RESET_PHRASES)


def resolve_context_entities(query: str, session_context: Optional[dict] = None) -> Tuple[Optional[str], Optional[int], Optional[str], dict]:
    """
    Extract district/year/crime_type from the CURRENT query, falling back to
    the last-known values from the conversation's session context whenever
    the current query doesn't explicitly mention them. This is what powers
    multi-turn, context-aware follow-up questions, e.g.:
        "How many crimes in Mysuru?"        -> district=Mysuru (fresh)
        "What about theft there?"           -> district=Mysuru (carried over), crime_type=Theft (fresh)
        "Show me the trend"                 -> district=Mysuru, crime_type=Theft (both carried over)

    Returns (district, year, crime_type, context_used) where context_used is
    a dict of {entity_name: True} for every entity that came from session
    context rather than the current query text.
    """
    session_context = session_context or {}

    district = extract_district(query)
    year = extract_year(query)
    crime_type = extract_crime_type(query)

    context_used = {}

    if district is None and session_context.get("district"):
        district = session_context["district"]
        context_used["district"] = True

    if year is None and session_context.get("year"):
        year = session_context["year"]
        context_used["year"] = True

    if crime_type is None and session_context.get("crime_type"):
        crime_type = session_context["crime_type"]
        context_used["crime_type"] = True

    return district, year, crime_type, context_used


def build_sql_query(intent: str, query: str, db_conn, session_context: Optional[dict] = None) -> Tuple[str, list, str, dict]:
    """
    Resolve entities (current query + carried-over session context), then
    build the SQL for the given intent.

    Returns (sql, params, chart_type, resolved) where `resolved` is
    {"district", "year", "crime_type", "context_used"} describing exactly
    what values were used and which of them were carried over from earlier
    in the conversation -- this feeds both the response text (for
    transparency/explainability) and the updated session context to persist.
    """
    if _is_context_reset_request(query):
        session_context = {}

    district, year, crime_type, context_used = resolve_context_entities(query, session_context)

    sql, params, chart_type = _build_sql_query_core(intent, query, db_conn, district, year, crime_type)

    # Guardrail: every intent branch above is expected to explicitly handle
    # the "count" shape (see detect_response_shape) by returning a single
    # COUNT(*) row with chart_type="number". If a branch is ever missed --
    # or a new intent is added later without this check -- this safety net
    # wraps whatever detail SQL was produced into a COUNT(*) subquery, so a
    # "how many ...?" question can NEVER surface as a raw multi-row table.
    # This keeps the answer's shape correct even when the specific wording
    # wasn't anticipated by any individual branch.
    if detect_response_shape(query) == "count" and chart_type != "number":
        sql = f"SELECT COUNT(*) as total_matches FROM ({sql}) AS _shape_guard"
        chart_type = "number"

    # Only surface "used earlier context" for entities this intent actually
    # consumes, so we don't tell the user we "remembered" something that had
    # no bearing on the answer.
    relevant = _INTENT_RELEVANT_ENTITIES.get(intent, set())
    context_used = {k: v for k, v in context_used.items() if k in relevant}

    resolved = {"district": district, "year": year, "crime_type": crime_type, "context_used": context_used}
    return sql, params, chart_type, resolved


def _build_sql_query_core(intent: str, query: str, db_conn, district: Optional[str], year: Optional[int], crime_type: Optional[str]) -> Tuple[str, list, str]:
    """Returns (sql, params, chart_type) given already-resolved entities.

    Every branch below first checks `shape` (count vs. detail) so that a
    "how many ..." question always returns a single COUNT(*) row/"number"
    chart_type, and a "show/list/breakdown ..." question always returns the
    full detail table/chart -- regardless of which topic-level `intent` was
    detected. This keeps every answer's SHAPE aligned with what was actually
    asked, on top of the existing entity (district/year/crime_type) filtering.
    """
    shape = detect_response_shape(query)

    if intent == "count_crimes":
        # Combine ALL resolved entities (district AND/OR crime_type AND/OR
        # year) into a single filtered COUNT, instead of only honoring one
        # at a time. This matters for context-aware follow-ups where one
        # entity comes from the current query and another is carried over
        # from earlier in the conversation (e.g. "what about theft?" after
        # "crimes in Mysuru?" should count Theft cases IN Mysuru, not just Theft).
        if district or crime_type or year:
            sql = """SELECT COUNT(*) as total_cases FROM fir_cases f
                     JOIN police_stations ps ON f.station_id = ps.station_id
                     JOIN districts d ON ps.district_id = d.district_id
                     WHERE 1=1"""
            params = []
            if district:
                sql += " AND LOWER(d.district_name) LIKE ?"
                params.append(f"%{district.lower()}%")
            if crime_type:
                sql += " AND f.crime_type = ?"
                params.append(crime_type)
            if year:
                sql += " AND strftime('%Y', f.date_of_incident) = ?"
                params.append(str(year))
            return sql, params, "number"
        else:
            return "SELECT COUNT(*) as total_cases FROM fir_cases", [], "number"

    elif intent == "crime_by_district":
        if shape == "count":
            # "How many districts have registered crimes?" / "how many
            # districts are there?" -- answer with a count of districts,
            # not a full per-district breakdown chart.
            sql = "SELECT COUNT(DISTINCT district_id) as total_districts FROM districts"
            return sql, [], "number"
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
        # If a specific crime type is resolved (fresh or carried over from
        # context), filter down to just that type instead of always showing
        # the full breakdown -- e.g. a follow-up "what about theft?" should
        # answer about Theft specifically, optionally still scoped to a
        # carried-over district.
        if crime_type:
            sql = """SELECT COUNT(*) as total_cases
                     FROM fir_cases f
                     JOIN police_stations ps ON f.station_id = ps.station_id
                     JOIN districts d ON ps.district_id = d.district_id
                     WHERE f.crime_type = ?"""
            params = [crime_type]
            if district:
                sql += " AND LOWER(d.district_name) LIKE ?"
                params.append(f"%{district.lower()}%")
            return sql, params, "number"
        elif district:
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
        if shape == "count":
            # "How many hotspot stations are there?" -- count stations above
            # a meaningful case-volume threshold rather than dumping the
            # top-15 bar chart.
            sql = """SELECT COUNT(*) as total_hotspots FROM (
                        SELECT ps.station_id, COUNT(*) as case_count
                        FROM fir_cases f
                        JOIN police_stations ps ON f.station_id = ps.station_id
                        GROUP BY ps.station_id
                        HAVING case_count >= 20
                     )"""
            return sql, [], "number"
        sql = """SELECT ps.station_name, d.district_name, COUNT(*) as case_count,
                        AVG(f.severity_score) as avg_severity
                 FROM fir_cases f
                 JOIN police_stations ps ON f.station_id = ps.station_id
                 JOIN districts d ON ps.district_id = d.district_id
                 GROUP BY ps.station_id ORDER BY case_count DESC LIMIT 15"""
        return sql, [], "bar"

    elif intent == "accused_search":
        query_lower = query.lower()
        # "How many / total / number of ..." should answer with a single
        # count, not dump a full list/table -- e.g. "How many accused are
        # still wanted?" should say "There are N wanted accused", not show
        # a 30-row table flattened into 40+ field/value pairs.
        is_count_query = bool(re.search(r"how many|how much|total number|number of|count of", query_lower))

        if "repeat" in query_lower or "history" in query_lower:
            if is_count_query:
                sql = """SELECT COUNT(DISTINCT a.accused_id) as repeat_offender_count
                         FROM accused a WHERE a.criminal_history > 0"""
                return sql, [], "number"
            sql = """SELECT a.name, a.age, a.occupation, a.criminal_history, a.arrest_status,
                            COUNT(cr.record_id) as prior_cases
                     FROM accused a
                     LEFT JOIN criminal_records cr ON a.accused_id = cr.accused_id
                     WHERE a.criminal_history > 0
                     GROUP BY a.accused_id ORDER BY prior_cases DESC LIMIT 20"""
            return sql, [], "table"
        elif "gang" in query_lower:
            if is_count_query:
                sql = """SELECT COUNT(*) as gang_affiliated_count FROM accused
                         WHERE gang_affiliation IS NOT NULL AND gang_affiliation != ''"""
                return sql, [], "number"
            sql = """SELECT gang_affiliation, COUNT(*) as member_count,
                            AVG(age) as avg_age, COUNT(DISTINCT fir_id) as cases_involved
                     FROM accused WHERE gang_affiliation IS NOT NULL AND gang_affiliation != ''
                     GROUP BY gang_affiliation ORDER BY member_count DESC"""
            return sql, [], "table"
        elif "wanted" in query_lower or "absconding" in query_lower:
            if is_count_query:
                sql = """SELECT COUNT(*) as wanted_or_absconding_count FROM accused
                         WHERE arrest_status IN ('Wanted','Absconding')"""
                return sql, [], "number"
            sql = """SELECT a.name, a.age, a.occupation, f.crime_type, d.district_name, a.gang_affiliation
                     FROM accused a
                     JOIN fir_cases f ON a.fir_id = f.fir_id
                     JOIN police_stations ps ON f.station_id = ps.station_id
                     JOIN districts d ON ps.district_id = d.district_id
                     WHERE a.arrest_status IN ('Wanted','Absconding')
                     ORDER BY f.severity_score DESC LIMIT 30"""
            return sql, [], "table"
        elif is_count_query:
            sql = "SELECT COUNT(*) as total_accused FROM accused"
            return sql, [], "number"
        else:
            sql = """SELECT arrest_status, COUNT(*) as count FROM accused
                     GROUP BY arrest_status ORDER BY count DESC"""
            return sql, [], "pie"

    elif intent == "victim_stats":
        if shape == "count":
            # "How many victims are there?" (optionally "female"/"male"/
            # "child" victims) -- a single count, not the full age/gender
            # breakdown chart.
            where_clause, _subject = _extract_victim_filter(query)
            sql = "SELECT COUNT(*) as total_victims FROM victims v"
            if where_clause:
                sql += f" WHERE {where_clause}"
            return sql, [], "number"
        sql = """SELECT
                   CASE WHEN v.age < 18 THEN 'Minor (<18)'
                        WHEN v.age < 30 THEN 'Youth (18-29)'
                        WHEN v.age < 50 THEN 'Adult (30-49)'
                        ELSE 'Senior (50+)' END as age_group,
                   v.gender, COUNT(*) as victim_count
                 FROM victims v GROUP BY age_group, v.gender ORDER BY victim_count DESC"""
        return sql, [], "bar"

    elif intent == "case_status":
        status = extract_case_status(query)
        if shape == "count":
            # "How many cases are pending/closed/etc?" -- filter to the
            # mentioned status (if any) and answer with a single count,
            # instead of the full status-breakdown pie chart.
            sql = "SELECT COUNT(*) as total_cases FROM fir_cases"
            if status:
                sql += " WHERE status = ?"
                return sql, [status], "number"
            return sql, [], "number"
        if status:
            sql = "SELECT status, COUNT(*) as case_count FROM fir_cases WHERE status = ? GROUP BY status"
            return sql, [status], "pie"
        sql = """SELECT status, COUNT(*) as case_count FROM fir_cases
                 GROUP BY status ORDER BY case_count DESC"""
        return sql, [], "pie"

    elif intent == "property_crime":
        ptype = extract_property_type(query)
        if shape == "count":
            # "How many mobile phones were stolen?" / "how many items were
            # stolen?" -- a single count of items, not the value/recovery
            # breakdown bar chart.
            sql = "SELECT COUNT(*) as total_items FROM stolen_property"
            if ptype:
                sql += " WHERE property_type = ?"
                return sql, [ptype], "number"
            return sql, [], "number"
        if ptype:
            sql = """SELECT property_type, COUNT(*) as items_stolen,
                            SUM(estimated_value) as total_value,
                            SUM(recovered) as recovered_count
                     FROM stolen_property WHERE property_type = ? GROUP BY property_type"""
            return sql, [ptype], "table"
        sql = """SELECT property_type, COUNT(*) as items_stolen,
                        SUM(estimated_value) as total_value,
                        SUM(recovered) as recovered_count
                 FROM stolen_property GROUP BY property_type ORDER BY total_value DESC"""
        return sql, [], "bar"

    elif intent == "severity":
        if shape == "count":
            # "How many severe/high-severity cases are there?" -- count
            # rather than list all 25 rows.
            sql = """SELECT COUNT(*) as total_cases FROM fir_cases
                     WHERE severity_score >= 8"""
            return sql, [], "number"
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
        if shape == "count":
            # "How many gang members / criminal network members are there?"
            sql = """SELECT COUNT(DISTINCT accused_id) as total_members
                     FROM accused WHERE gang_affiliation IS NOT NULL AND gang_affiliation != ''"""
            return sql, [], "number"
        sql = """SELECT a.name, a.gang_affiliation, COUNT(DISTINCT a.fir_id) as cases,
                        GROUP_CONCAT(DISTINCT f.crime_type) as crime_types,
                        a.criminal_history
                 FROM accused a
                 JOIN fir_cases f ON a.fir_id = f.fir_id
                 WHERE a.gang_affiliation IS NOT NULL
                 GROUP BY a.accused_id ORDER BY cases DESC LIMIT 30"""
        return sql, [], "network"

    elif intent == "officer_stats":
        if shape == "count":
            # This intent covers both "how many officers?" and "how many
            # (police) stations?" (the pattern list includes both keywords)
            # -- check which noun the query actually used so the count
            # matches the right table.
            if re.search(r"stations?\b", query.lower()) and "officer" not in query.lower():
                sql = "SELECT COUNT(*) as total_stations FROM police_stations"
            else:
                sql = "SELECT COUNT(*) as total_officers FROM officers"
            return sql, [], "number"
        sql = """SELECT o.name, o.rank, ps.station_name, d.district_name, o.cases_handled
                 FROM officers o
                 JOIN police_stations ps ON o.station_id = ps.station_id
                 JOIN districts d ON ps.district_id = d.district_id
                 ORDER BY o.cases_handled DESC LIMIT 20"""
        return sql, [], "table"

    else:
        # General fallback -- if the question was clearly a count question
        # but didn't match a more specific intent, answer with an overall
        # case count instead of the generic "top crime types" bar chart,
        # which would otherwise be an unrelated non-answer.
        if shape == "count":
            sql = "SELECT COUNT(*) as total_cases FROM fir_cases"
            return sql, [], "number"
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


def generate_natural_response(query: str, intents: list, results: list, chart_type: str, resolved: Optional[dict] = None, language: str = "en") -> str:
    """
    Generate a human-readable response from query results.
    Builds the deterministic, explainable (SQL-backed) response first, then
    layers an optional AI-generated insight from Catalyst QuickML's
    GLM-4.7-Flash LLM on top -- giving investigators both the auditable data
    table AND a natural-language analytical summary.

    `resolved` (optional) is the dict returned by build_sql_query() --
    {"district", "year", "crime_type", "context_used"} -- describing which
    entities (if any) were carried over from earlier in the conversation.
    When present, a short "remembered from earlier" note is prepended so the
    user can see exactly what context was applied (explainable AI).

    `language` ("en" or "kn") controls the language of the FULL response --
    when "kn", the deterministic body is translated into Kannada (via a
    fast, non-LLM phrase dictionary -- see translate_response_to_kannada)
    so a Kannada question always gets a Kannada answer instead of a mix of
    languages.

    NOTE on latency: Zoho Catalyst Advanced I/O functions have a hard
    30-second execution limit, and each QuickML LLM call to the "thinking"
    GLM model can itself take 20-30+ seconds regardless of input size.
    Using the LLM to translate the whole response body (instead of the
    dictionary-based approach used here) reliably exceeded that limit on
    its own, causing Catalyst's gateway to kill the function mid-flight and
    return its own error shape -- which the frontend then rendered as
    "Error: undefined". Since translation is now instant (no network call),
    the single remaining LLM call budget (the AI insight) is safe to keep
    for BOTH languages.
    """
    base_response = _generate_deterministic_response(query, intents, results, chart_type, resolved)
    if language == "kn":
        base_response = translate_response_to_kannada(base_response)

    intent = intents[0] if intents else "general"
    if intent == "greeting" or not results or "error" in results[0]:
        return base_response

    # Summarize just enough data for the LLM prompt (keep payload small)
    data_summary = json.dumps(results[:15], default=str, ensure_ascii=False)
    insight = generate_llm_insight(query, data_summary, language=language)
    if insight:
        insight_label = "AI ಒಳನೋಟ" if language == "kn" else "AI Insight"
        return f"{base_response}\n\n---\n🧠 **{insight_label} (QuickML · GLM-4.7-Flash):** {insight}"
    return base_response


def _context_note(context_used: dict, district: Optional[str], year: Optional[int], crime_type: Optional[str]) -> str:
    """Build a short, transparent note about which entities were carried
    over from earlier in the conversation (explainable AI)."""
    if not context_used:
        return ""
    parts = []
    if context_used.get("district") and district:
        parts.append(f"district **{district.title()}**")
    if context_used.get("crime_type") and crime_type:
        parts.append(f"crime type **{crime_type}**")
    if context_used.get("year") and year:
        parts.append(f"year **{year}**")
    if not parts:
        return ""
    return f"🧭 _Continuing from earlier in this chat — using {', '.join(parts)}._\n\n"


def _generate_deterministic_response(query: str, intents: list, results: list, chart_type: str, resolved: Optional[dict] = None) -> str:
    """Rule-based, explainable response builder. Wraps the core builder so a
    single 'continuing from earlier in this chat' note (when applicable) is
    prepended to whichever branch produced the final response."""
    if intents and intents[0] == "greeting":
        return "Hello! 👋 I’m KSP Crime Intelligence AI. I can help you explore crime trends, district-wise patterns, suspect details, hotspots, and case status. What would you like to know today?"

    if not results:
        return "I couldn't find any data matching your query. Please try a different question."

    if "error" in results[0]:
        return f"There was an error processing your query: {results[0]['error']}"

    # Fall back to re-extracting from the raw query text if no resolved
    # entities were passed in (keeps this function usable standalone / by tests).
    if resolved:
        context_used = resolved.get("context_used", {})
        district = resolved.get("district")
        year = resolved.get("year")
        crime_type = resolved.get("crime_type")
    else:
        context_used = {}
        district = extract_district(query)
        year = extract_year(query)
        crime_type = extract_crime_type(query)

    note = _context_note(context_used, district, year, crime_type)
    body = _build_deterministic_body(query, intents, results, chart_type, district, year, crime_type)
    return f"{note}{body}"


def _build_count_response(query: str, intent: str, results: list, district: Optional[str], year: Optional[int], crime_type: Optional[str]) -> str:
    """Single shared phrase-builder for every 'count' shaped answer, so
    wording stays consistent across intents instead of being hand-written
    (and easy to get subtly wrong/mismatched) in each branch separately."""
    count = list(results[0].values())[0]
    query_lower = query.lower()

    if intent == "accused_search":
        # Describe *who* is being counted (wanted/gang/repeat offenders)
        # instead of the generic "cases" phrasing used for crime counts.
        if "wanted" in query_lower or "absconding" in query_lower:
            subject = "accused who are still **Wanted / Absconding**"
        elif "gang" in query_lower:
            subject = "accused with a recorded **gang affiliation**"
        elif "repeat" in query_lower or "history" in query_lower:
            subject = "accused with a **prior criminal history**"
        else:
            subject = "accused"
        return f"📊 There are **{count:,}** {subject} in the KSP database."

    if intent == "victim_stats":
        _where, subject = _extract_victim_filter(query)
        return f"📊 There are **{count:,}** {subject} recorded in the KSP database."

    if intent == "case_status":
        status = extract_case_status(query)
        subject = f"cases with status **{status}**" if status else "total cases"
        return f"📊 There are **{count:,}** {subject} in the KSP database."

    if intent == "property_crime":
        ptype = extract_property_type(query)
        subject = f"stolen **{ptype}** items" if ptype else "stolen-property items"
        return f"📊 There are **{count:,}** {subject} recorded in the KSP database."

    if intent == "severity":
        return f"📊 There are **{count:,}** high-severity cases (severity score ≥ 8) in the KSP database."

    if intent == "network_analysis":
        return f"📊 There are **{count:,}** accused with a recorded gang/network affiliation in the KSP database."

    if intent == "officer_stats":
        if re.search(r"stations?\b", query_lower) and "officer" not in query_lower:
            return f"📊 There are **{count:,}** police stations recorded in the KSP database."
        return f"📊 There are **{count:,}** officers recorded in the KSP database."

    if intent == "crime_by_district":
        return f"📊 There are **{count:,}** districts in the KSP database."

    if intent == "hotspot":
        return f"📊 There are **{count:,}** hotspot stations (20+ recorded cases) in the KSP database."

    parts = []
    if crime_type:
        parts.append(f"of **{crime_type}**")
    if district:
        parts.append(f"in **{district.title()}**")
    if year:
        parts.append(f"in **{year}**")
    context = f" {' '.join(parts)}" if parts else ""
    return f"📊 There are **{count:,}** total cases{context} in the KSP database."


def _build_deterministic_body(query: str, intents: list, results: list, chart_type: str, district: Optional[str], year: Optional[int], crime_type: Optional[str]) -> str:
    intent = intents[0] if intents else "general"

    if chart_type == "number":
        return _build_count_response(query, intent, results, district, year, crime_type)

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

    if intent == "victim_stats":
        intro = "🧍 Age-group and gender breakdown of recorded victims"
        return _build_markdown_table(
            results,
            [("Age Group", "age_group"), ("Gender", "gender"), ("Victims", "victim_count")],
            title="Victim Demographics",
            intro=intro,
        )

    if intent == "severity":
        intro = "🚨 Cases with severity score ≥ 8, most severe first"
        return _build_markdown_table(
            results,
            [("FIR Number", "fir_number"), ("Crime Type", "crime_type"), ("Date", "date_of_incident"),
             ("District", "district_name"), ("Severity", "severity_score"), ("Status", "status")],
            title="High-Severity Cases",
            intro=intro,
        )

    if intent == "officer_stats":
        intro = "👮 Officers ranked by number of cases handled"
        return _build_markdown_table(
            results,
            [("Name", "name"), ("Rank", "rank"), ("Station", "station_name"),
             ("District", "district_name"), ("Cases Handled", "cases_handled")],
            title="Officer Performance",
            intro=intro,
        )

    if intent == "case_status":
        status = extract_case_status(query)
        intro = f"📋 Cases with status **{status}**" if status else "📋 Current status of registered cases"
        return _build_markdown_table(
            results,
            [("Status", "status"), ("Cases", "case_count")],
            title="Case Status Summary",
            intro=intro,
        )

    if intent == "accused_search":
        if results and "error" not in results[0]:
            # Build a normal one-row-per-record table using whichever columns
            # this particular sub-query actually returned (name/age/... for
            # wanted/repeat-offender lists, gang_affiliation/member_count for
            # gang summaries, arrest_status/count for the general breakdown)
            # instead of flattening every field into its own row -- that
            # made row counts (and "showing first N of M") meaningless.
            columns = [(key.replace("_", " ").title(), key) for key in results[0].keys()]
            return _build_markdown_table(
                results,
                columns,
                title="Accused / Criminal Data",
                intro="📋 Matching records",
                max_rows=15,
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
        ptype = extract_property_type(query)
        intro = f"💰 **{ptype}** loss and recovery summary" if ptype else "💰 Property loss and recovery summary"
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
