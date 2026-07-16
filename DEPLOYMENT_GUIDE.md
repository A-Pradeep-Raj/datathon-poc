# KSP Crime Intelligence AI – Deployment Guide
## Datathon 2026 · Challenge 1 · Zoho Catalyst

---

## 📁 Final Project Structure

```
ksp-crime-ai/
├── .catalystrc                            ← Catalyst auth (auto-generated)
├── catalyst.json                          ← Catalyst project config
├── .gitignore
├── DEPLOYMENT_GUIDE.md
│
├── client/                                ← Web client for Catalyst hosting
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── client-package.json               ← Required by Catalyst client deploy
│
├── public/                                ← Local dev static files (mirror of client/)
│   ├── index.html
│   ├── style.css
│   └── app.js
│
└── functions/
    └── crime-chat-function/               ← Advanced I/O Python function
        ├── index.py                       ← Flask app entry point
        ├── ai_engine.py                   ← NL→SQL + response generation
        ├── synthetic_data.py              ← DB seed (1500 FIR cases)
        ├── catalyst-config.json          ← Function config for Catalyst CLI
        ├── requirements.txt              ← Python deps
        └── ksp_crime.db                  ← SQLite DB (auto-created on first run)
```

---

## 🖥️ PART A – LOCAL DEVELOPMENT

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Run the Flask backend |
| pip | any | Install Python dependencies |

---

### A1 · Install Python (if not installed)

Download from https://www.python.org/downloads/ (v3.11 recommended).
During installation, **check "Add Python to PATH"**.

Verify in a new terminal:
```powershell
python --version   # should show Python 3.11.x
pip --version
```

If Python installed to `C:\Program Files\Python311`, add to PATH manually:
```powershell
$env:PATH = "C:\Program Files\Python311;C:\Program Files\Python311\Scripts;C:\Users\$env:USERNAME\AppData\Roaming\Python\Python311\Scripts;" + $env:PATH
```

---

### A2 · Install Flask

```powershell
pip install flask
```

---

### A3 · Generate the Synthetic Database

```powershell
cd "C:\pradeep\70B\Datathon\ksp-crime-ai\functions\crime-chat-function"
python synthetic_data.py
```

Expected output:
```
[✓] Synthetic database created at ksp_crime.db
    Districts: 20
    Police Stations: 85
    FIR Cases: 1500
```

---

### A4 · Start the Local Server

```powershell
cd "C:\pradeep\70B\Datathon\ksp-crime-ai\functions\crime-chat-function"
set PYTHONIOENCODING=utf-8
python index.py
```

Expected output:
```
 * Serving Flask app 'index'
 * Debug mode: on
 * Running on http://127.0.0.1:3000
```

**Open in browser:** http://localhost:3000

---

### A5 · Test API Endpoints Locally

```powershell
# Health check
Invoke-RestMethod -Uri http://localhost:3000/api/health

# Chat query
$body = '{"query":"How many total crimes?","language":"en"}'
Invoke-RestMethod -Uri http://localhost:3000/api/chat -Method POST -Body $body -ContentType "application/json"

# Dashboard KPIs
Invoke-RestMethod -Uri http://localhost:3000/api/dashboard
```

---

### A6 · Reinitialize Database (if needed)

Click **"🔄 Reload DB"** in the app sidebar, or:

```powershell
Invoke-RestMethod -Uri http://localhost:3000/api/init-db -Method POST
```

---

## ☁️ PART B – ZOHO CATALYST DEPLOYMENT

### Prerequisites

| Tool | Required | Purpose |
|------|----------|---------|
| Node.js v18+ | Yes | Catalyst CLI dependency |
| Zoho account (India DC) | Yes | console.catalyst.zoho.in |

---

### B1 · Install Node.js

Download from https://nodejs.org/ (LTS). After install, open a **new PowerShell**:

```powershell
# Allow PowerShell scripts (one-time)
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force

# Refresh PATH
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")

# Verify
node --version   # v18+ or v24+
npm --version
```

---

### B2 · Install Catalyst CLI

```powershell
npm install -g zcatalyst-cli

# Verify
catalyst --version   # should show 1.26.x
```

> ⚠️ In every new PowerShell terminal, run this PATH refresh before using catalyst:
> ```powershell
> $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
> Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
> ```

---

### B3 · Login to Zoho Catalyst (India Datacenter)

```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
catalyst login
```

Interactive prompts — answer each one:

| Prompt | Answer |
|--------|--------|
| `Allow Catalyst to collect CLI error reporting information?` | `Y` then Enter |
| `Select the datacenter to which you have access` | Use arrow keys → select **IN – India** → Enter |
| Browser opens | Sign in with your Zoho account credentials |
| `Your credentials does not match the DC opted!!! Do you wish to continue with login by making IN DC as active?` | `Y` then Enter |

Expected final output:
```
√ Success! Logged in as : your@email.com
```

---

### B4 · Create Project in Catalyst Console

1. Open **https://console.catalyst.zoho.in/**
2. Click **"Create New Project"**
3. Project name: `ksp-crime-ai` → Click **Create**
4. Note your **Project ID** (visible in the URL after creation)

---

### B5 · Link Local Folder to the Catalyst Project

```powershell
cd "C:\pradeep\70B\Datathon\ksp-crime-ai"
catalyst init
```

Interactive prompts:

| Prompt | Answer |
|--------|--------|
| `Select a default Catalyst project` | Use arrow keys/type to select **ksp-crime-ai** → Enter |
| `Which are the features you want to setup?` | Press Enter (skip — already configured) |

Then explicitly set it as the active project:
```powershell
catalyst project:use "ksp-crime-ai"
```

Verify:
```powershell
catalyst project:list
# ksp-crime-ai should show as (active) (base)
```

---

### B6 · Verify Configuration Files

**`catalyst.json`** (project root):
```json
{
  "project_name": "ksp-crime-ai",
  "project_directory": ".",
  "project_id": "51742000000017001",
  "project_key": "ksp-crime-ai",
  "org_id": "60078097690",
  "functions": {
    "source": "functions",
    "targets": ["crime-chat-function"]
  },
  "client": {
    "source": "client"
  }
}
```

**`functions/crime-chat-function/catalyst-config.json`**:
```json
{
  "deployment": {
    "name": "crime-chat-function",
    "stack": "python_3_11",
    "type": "advancedio",
    "memory": 256,
    "timeout": 60,
    "env_variables": {}
  },
  "execution": {
    "main": "index.py"
  }
}
```

**`client/client-package.json`**:
```json
{
  "name": "ksp-crime-ai",
  "version": "0.0.1",
  "homepage": "index.html",
  "description": "KSP Crime Intelligence AI - Datathon 2026"
}
```

---

### B7 · Deploy to Catalyst

```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
cd "C:\pradeep\70B\Datathon\ksp-crime-ai"
catalyst deploy
```

Expected output:
```
√ Web_Client uploaded in 0 seconds

 >>>>>>>>>>>>> Web Client <<<<<<<<<<<<
√ DEPLOYMENT SUCCESSFUL: ksp-crime-ai
i ACCESS URL : https://ksp-crime-ai-60078097690.development.catalystserverless.in/app/index.html

 >>>>>>>>>>>>>> Functions <<<<<<<<<<<<
  ==> Advanced I/O
    √ DEPLOYMENT SUCCESSFUL: crime-chat-function
    i FUNCTION URL : https://ksp-crime-ai-60078097690.development.catalystserverless.in/server/crime-chat-function/

√ Catalyst deploy complete!
```

---

### B8 · Initialize Database on Catalyst (First Time Only)

Click **"🔄 Reload DB"** in the app sidebar on the live URL, or run:

```powershell
Invoke-RestMethod -Uri "https://ksp-crime-ai-60078097690.development.catalystserverless.in/server/crime-chat-function/api/init-db" -Method POST
```

---

### B9 · Your Live App URLs

| Resource | URL |
|----------|-----|
| 🌐 **Live App** | https://ksp-crime-ai-60078097690.development.catalystserverless.in/app/index.html |
| ⚡ **API Base** | https://ksp-crime-ai-60078097690.development.catalystserverless.in/server/crime-chat-function |
| 📊 **Catalyst Console** | https://console.catalyst.zoho.in/baas/60078097690/project/51742000000017001/Development |

---

## 🔄 REDEPLOYMENT (after code changes)

### Full redeploy (client + function):
```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
cd "C:\pradeep\70B\Datathon\ksp-crime-ai"

# Sync public/ changes to client/ first
Copy-Item "public\*" "client\" -Force

catalyst deploy
```

### Frontend only:
```powershell
Copy-Item "public\*" "client\" -Force
catalyst deploy --only client
```

### Backend function only:
```powershell
catalyst deploy --only functions
```

---

## 🔑 KEY API ENDPOINTS

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/dashboard` | KPI statistics |
| POST | `/api/chat` | **Main AI chat** |
| POST | `/api/chart-data` | Chart data by chart ID |
| GET | `/api/network` | Criminal network graph |
| GET | `/api/heatmap?crime_type=Murder&year=2024` | Crime heatmap |
| POST | `/api/suggest` | Follow-up query suggestions |
| POST | `/api/export-pdf` | Generate PDF report |
| POST | `/api/init-db` | Initialize/reseed database |

### Chat API request:
```json
POST /api/chat
{
  "query": "How many murder cases in Bengaluru?",
  "language": "en",
  "session_id": "optional-session-id"
}
```

**Available chart IDs:** `crimes_by_district`, `crimes_by_type`, `yearly_trend`, `monthly_trend`, `case_status`, `severity_distribution`, `top_hotspots`, `gender_accused`, `arrest_status`, `property_recovery`

---

## 💬 SAMPLE QUERIES

### English
| Category | Query |
|----------|-------|
| Count | `How many total crimes are registered in Karnataka?` |
| District | `Show crimes by district` |
| Trend | `Show crime trend from 2019 to 2025` |
| Hotspot | `Top crime hotspot stations` |
| Accused | `How many accused are still wanted?` |
| Status | `Show case status breakdown` |
| Predict | `Predict crime trend for next months` |
| Network | `Show criminal gang network analysis` |
| Severity | `Show the most severe cases` |

### ಕನ್ನಡ (Kannada)
| Query | Meaning |
|-------|---------|
| `ಬೆಂಗಳೂರಿನಲ್ಲಿ ಕೊಲೆ ಪ್ರಕರಣ` | Murder cases in Bengaluru |
| `ಕಳ್ಳತನ ಪ್ರಕರಣಗಳ ಪ್ರವೃತ್ತಿ ತೋರಿಸು` | Show theft case trend |
| `ಯಾವ ಜಿಲ್ಲೆಯಲ್ಲಿ ಅತಿ ಹೆಚ್ಚು ಅಪರಾಧ` | Which district has most crimes |
| `ಮಾದಕ ದ್ರವ್ಯ ಪ್ರಕರಣ ಎಷ್ಟು` | How many drug cases |
| `ಅಪರಾಧ ಹಾಟ್‌ಸ್ಪಾಟ್ ತೋರಿಸು` | Show crime hotspots |

---

## 🛠️ TROUBLESHOOTING

### `npm is not recognized`
Node.js not installed or PATH not refreshed. Fix:
```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
npm --version
```

### `catalyst is not recognized`
Same PATH issue. Run the PATH refresh above, then try again.

### `Your credentials does not match the DC opted!!!`
Expected when Zoho account is on India DC. Answer **Y** to switch to IN DC automatically.

### `deployment.stack is unknown`
Stack name must be exactly `python_3_11`. Valid values: `python_3_9`, `python_3_10`, `python_3_11`, `python_3_12`, `python_3_13`.

### `functions: targets was found to be empty`
Ensure `catalyst.json` uses this exact format:
```json
"functions": { "source": "functions", "targets": ["crime-chat-function"] }
```

### `client-package.json file was not found`
Create `client/client-package.json` — see B6 above for content.

### Function first request is slow (10-30 sec)
Normal cold-start behaviour for serverless functions. Subsequent calls are fast.

### Database is empty after deployment
Call `POST /api/init-db` once after deployment to seed the database.

---

## 🏆 HACKATHON FEATURE CHECKLIST

| Feature | Status | How |
|---------|--------|-----|
| ✅ NL Chatbot – English | Done | 15-intent pattern matching → SQL |
| ✅ NL Chatbot – Kannada | Done | Keyword map in `ai_engine.py` |
| ✅ Voice input | Done | Web Speech API (`kn-IN` + `en-IN`) |
| ✅ Context-aware chat | Done | Conversation history in `app.js` |
| ✅ PDF export | Done | jsPDF client-side + `/api/export-pdf` |
| ✅ Criminal network viz | Done | vis-network.js |
| ✅ Trend & hotspot detection | Done | Dashboard + Analytics tabs |
| ✅ Predictive analytics | Done | 24-month trend analysis |
| ✅ Explainable AI / Audit Trail | Done | SQL shown per query + Audit tab |
| ✅ Role-based UI | Done | Officer badge in header |
| ✅ 1500+ synthetic FIR records | Done | `synthetic_data.py` |
| ✅ Crime heatmap | Done | Canvas-based Karnataka map |
| ✅ Multi-chart visualizations | Done | Chart.js |
| ✅ Zoho Catalyst deployment | Done | Advanced I/O + Web Client |

---

## 🎯 5-MINUTE DEMO SCRIPT

1. **Open** https://ksp-crime-ai-60078097690.development.catalystserverless.in/app/index.html
2. **Chat:** *"Show crimes by district"* → Bar chart with Bengaluru Urban leading at 181 cases
3. **Kannada:** Type `ಬೆಂಗಳೂರಿನಲ್ಲಿ ಕೊಲೆ ಪ್ರಕರಣ` → Translation shown + results
4. **Voice:** Click 🎤 → speak *"Show crime hotspots"*
5. **Dashboard tab** → KPI cards + 6 live charts
6. **Analytics tab** → Monthly trend + predictive insights
7. **Heatmap tab** → Select "Murder" → geographic density on Karnataka map
8. **Network tab** → Click a node → see criminal details panel
9. **Audit Trail tab** → Show every SQL query for AI explainability
10. **Export PDF** → Click 📄 → download investigation report

---

*Built for Datathon 2026 · Karnataka State Police SCRB*
*Deployed on Zoho Catalyst India · Project: ksp-crime-ai (51742000000017001)*
