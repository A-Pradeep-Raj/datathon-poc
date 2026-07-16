# 🚔 KSP Crime Intelligence AI

> **Datathon 2026 · Challenge 1 · Zoho Catalyst**
> A conversational AI platform for exploring Karnataka State Police (KSP) crime data — supporting natural language queries in **English** and **Kannada**.

---

## 📖 Overview

KSP Crime Intelligence AI lets police officers and analysts ask questions about crime data in plain language (English or Kannada) and get instant answers backed by SQL queries, charts, heatmaps, and criminal network graphs. Built for the Datathon 2026 challenge on Zoho Catalyst.

**Key capabilities:**
- 💬 Natural language chat interface (English + ಕನ್ನಡ)
- 🔎 NL → SQL translation with explainable, auditable queries
- 📊 Interactive dashboards (crime trends, district-wise stats, case status)
- 🗺️ Crime heatmaps by location and severity
- 🕸️ Criminal network graph (gang affiliations, co-accused links)
- 📄 Exportable investigation reports (PDF)

---

## 🏗️ Project Structure

```
ksp-crime-ai/
├── catalyst.json                          ← Catalyst project config
├── DEPLOYMENT_GUIDE.md                    ← Full local + Catalyst deployment steps
│
├── client/                                ← Web client for Catalyst hosting
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── client-package.json
│
├── public/                                ← Local dev static files (mirror of client/)
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── functions/
│   └── crime-chat-function/               ← Advanced I/O Python (Flask) function
│       ├── index.py                       ← Flask app entry point / API routes
│       ├── ai_engine.py                   ← NL→SQL translation + response generation
│       ├── synthetic_data.py              ← Synthetic DB seed (1500 FIR cases)
│       ├── catalyst-config.json           ← Function config for Catalyst CLI
│       └── requirements.txt               ← Python dependencies
│
└── tests/
    └── test_greeting.py                   ← Unit tests
```

---

## 🚀 Quick Start (Local Development)

### Prerequisites
- Python 3.11+
- pip

### Setup

```powershell
cd ksp-crime-ai/functions/crime-chat-function
pip install -r requirements.txt

# Generate the synthetic database (first run only)
python synthetic_data.py

# Start the server
$env:PYTHONIOENCODING="utf-8"
python index.py
```

Open your browser at **http://localhost:3000**

Full instructions (including Zoho Catalyst cloud deployment) are in [`DEPLOYMENT_GUIDE.md`](./DEPLOYMENT_GUIDE.md).

---

## 🔌 API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Health check |
| `/api/chat` | POST | Main conversational AI endpoint |
| `/api/dashboard` | GET | Key performance indicators |
| `/api/chart-data` | POST | Chart-ready aggregated data |
| `/api/network` | GET | Criminal network graph data |
| `/api/heatmap` | GET | Crime location heatmap points |
| `/api/suggest` | POST | Contextual follow-up query suggestions |
| `/api/export-pdf` | POST | Export conversation as report |

---

## 🧪 Running Tests

```powershell
pip install pytest
pytest tests/
```

---

## 🛠️ Tech Stack

- **Backend:** Python, Flask
- **Database:** SQLite (synthetic FIR/crime dataset)
- **Frontend:** HTML, CSS, vanilla JavaScript
- **Cloud:** Zoho Catalyst (Advanced I/O Functions + Client Hosting)
- **Languages supported:** English, Kannada (ಕನ್ನಡ)

---

## 📄 License

Built for Datathon 2026 · Challenge 1 · Zoho Catalyst. For educational/competition purposes.
