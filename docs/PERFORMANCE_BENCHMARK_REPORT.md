# KRIME AI — Prototype Performance Benchmark Report

_Generated: 2026-07-26 15:46:40 · Benchmark run: 2026-07-26T15:46:17.422455_

> **How to read this report:** every figure is tagged `[MEASURED]` (captured by running `tests/benchmark_performance.py` against the real synthetic-data SQLite database and the real `ai_engine.py` query pipeline / a real concurrent load test on this machine) or `[ESTIMATED]` (a documented projection for infrastructure this local benchmark cannot exercise — Zoho Catalyst's serverless cold-start/autoscaling, live speech-recognition accuracy, or a full browser accessibility audit). Reproduce the `[MEASURED]` numbers yourself with:
> ```
> cd functions/crime-chat-function
> python ../../tests/benchmark_performance.py
> python ../../tests/generate_benchmark_report.py
> ```

```
⚡ PERFORMANCE BENCHMARKS
══════════════════════════════════════════════════════════════════════════════

📊 RESPONSE TIME ANALYSIS                                    [MEASURED]
   In-process pipeline timing: detect_intent → build_sql_query →
   execute_query → generate_natural_response, 200 iterations/query type,
   10 warmup calls discarded, against the real 1,500-case synthetic DB.
──────────────────────────────────────────────────────────────────────────────
Query Type                     | P50 (ms) | P95 (ms) | P99 (ms)
──────────────────────────────┼──────────┼──────────┼──────────
Simple Count Query             | 0.1      | 0.2      | 0.4     
District-Level Aggregation     | 0.3      | 0.6      | 0.8     
Crime Type Breakdown           | 0.1      | 0.4      | 0.8     
Crime Trend (multi-year)       | 0.5      | 1.0      | 1.3     
Hotspot Detection (Top 10)     | 0.5      | 1.0      | 1.0     
Accused / Criminal Search      | 0.9      | 2.3      | 3.6     
Victim Statistics              | 1.2      | 2.8      | 3.7     
Case Status Breakdown          | 0.1      | 0.1      | 0.2     
Officer / Station Performance  | 0.1      | 0.3      | 0.3     
Property Crime / Recovery      | 0.3      | 0.5      | 1.0     
Severity Analysis              | 0.1      | 0.5      | 0.7     
──────────────────────────────┴──────────┴──────────┴──────────

✅ RESULTS:
   • 99th percentile (avg across query types): 1.3ms  [MEASURED]
   • Average query latency: 0.5ms  [MEASURED]
   • These times are the QUERY/LOGIC layer only (Python + SQLite, no
     network hop). Add ~20-40ms for Flask HTTP overhead + JSON
     serialization on localhost, or ~100-400ms extra over the public
     internet, and 3-5s for a genuine Catalyst Advanced I/O cold start
     after idle (function container spin-up).  [ESTIMATED, platform-documented]
   • Optional "AI Insight" LLM call (QuickML GLM-4.7-Flash) adds a further
     ~20-25s per request when enabled — a fixed model-inference latency floor,
     NOT part of the deterministic query timings above.  [MEASURED during dev, see repo memory]

📈 THROUGHPUT / CONCURRENCY                                  [MEASURED]
──────────────────────────────────────────────────────────────────────────────
   Real ThreadPoolExecutor load test: 300 requests across 50 concurrent workers,
   each opening its own sqlite3 connection (mirrors index.py's per-request get_db()).
   • Concurrent workers tested: 50
   • Success rate: 100.0% (300/300, 0 errors)
   • Throughput: 1163.3 req/sec (69798 req/min)
   • Latency under load — P50: 20.6ms | P95: 62.3ms | P99: 92.7ms
   • This measures Python/SQLite concurrency on THIS machine, not Zoho
     Catalyst's actual network/autoscaling infrastructure under real traffic
     — production throughput will additionally depend on Catalyst's own
     Advanced I/O concurrency limits and autoscaling triggers.  [ESTIMATED, platform-documented]

💾 DATABASE PERFORMANCE                                      [MEASURED]
──────────────────────────────────────────────────────────────────────────────
   • Database size: 1.41 MB (1500 FIR cases + related tables)
   • Row counts: fir_cases=1500, accused=2530, victims=2785, witnesses=0
                 police_stations=85, districts=20, officers=373
   • Query cache: In-process (Flask memory, per-connection) — no dedicated cache layer
   • Indexes now defined in schema: 11 (added to synthetic_data.py's DDL — see Index Strategy below; SQLite auto-indexes
     PRIMARY KEY / UNIQUE columns separately, not counted here)
   • Full-table scans WITH current indexes applied: 4/11 benchmarked query shapes
   • Full-table scans WITHOUT indexes (reconstructed baseline, indexes dropped on a
     throwaway DB copy): 10/11 benchmarked query shapes ⚠️
   • Real timing delta on 2 representative filtered queries (P50, unindexed baseline):
       - crime_by_type (filtered): 0.1ms (see Response Time table above for the CURRENT, indexed P50)
       - accused wanted (filtered): 0.6ms (see Response Time table above for the CURRENT, indexed P50)

   Index Strategy (verified via EXPLAIN QUERY PLAN, APPLIED to
   synthetic_data.py's schema as of this benchmark run):
   ├─ fir_cases(station_id)
   ├─ fir_cases(crime_type)
   ├─ fir_cases(date_of_incident)
   ├─ fir_cases(severity_score DESC)
   ├─ fir_cases(status)
   ├─ police_stations(district_id)
   ├─ accused(fir_id), accused(arrest_status), accused(gang_affiliation)
   └─ victims(fir_id), stolen_property(fir_id)

🧠 AI ACCURACY                                                [MEASURED + ESTIMATED]
──────────────────────────────────────────────────────────────────────────────
   Intent Detection (regex-pattern based, fully deterministic):  [MEASURED]
   • Accuracy: 88.5% (23/26) against a 26-query labeled test set
   • Coverage: 13 intents defined (count_crimes, crime_by_district, crime_by_type,
     crime_trend, hotspot, accused_search, victim_stats, case_status, officer_stats,
     predictive, network_analysis, property_crime, severity) + greeting/general fallback
   • Misclassified in this run:
       - "predict crime trend next month" → expected 'predictive', got 'crime_trend'
       - "criminal network gang connections" → expected 'network_analysis', got 'accused_search'
       - "linked associates of accused" → expected 'network_analysis', got 'accused_search'
   • Fallback: unmatched queries default to a general/no-intent response (no
     hard failure)

   Kannada Translation & Speech Recognition:                     [ESTIMATED / DOCUMENTED]
   • Dictionary-based translation (_ENGLISH_TO_KANNADA_PHRASES, ai_engine.py):
     100+ crime-specific terms/phrases mapped, applied longest-phrase-first;
     deterministic substitution has effectively 100% consistency for phrases
     IN the dictionary, by construction — cannot be meaningfully expressed as a
     single "accuracy %" the way an ML translation model's would be.
   • Voice input/output uses the BROWSER's native Web Speech API
     (SpeechRecognition/kn-IN, en-IN) — actual recognition accuracy depends on
     the end-user's browser/OS speech engine and microphone quality, which
     cannot be measured from this backend-only benchmark; figures reported
     elsewhere for this are informal developer-testing observations, not a
     controlled accuracy study.

📊 DATA ACCURACY / CONSISTENCY                               [MEASURED]
──────────────────────────────────────────────────────────────────────────────
   • Crime records: 1500 synthetic FIR cases
   • Duplicate FIR numbers: 0
   • NULL crime_type: 0  |  NULL station_id: 0
   • Data consistency: 100.0% (no duplicates/NULLs in checked columns)
   • Geographic coverage: 85 stations across 20 districts
   • Temporal coverage: 2019–2025
   • Crime type coverage: 20 distinct types

💻 RESOURCE USAGE                                             [MEASURED]
──────────────────────────────────────────────────────────────────────────────
   • Process RSS memory before benchmark query burst: 34.5 MB
   • Process RSS memory after benchmark query burst: 34.4 MB
   • Delta: -0.1 MB (single Python process, this benchmark run only —
     NOT the deployed Catalyst function's actual container memory allocation,
     which is configured/observed separately via the Catalyst console)  [ESTIMATED for prod]

🔒 SECURITY AUDIT                                             [MEASURED / CODE-VERIFIED]
──────────────────────────────────────────────────────────────────────────────
   ✅ Authentication: session token via auth.py (SHA-256+salt password hashing,
      bearer/X-Auth-Token session lookup, 12h TTL) — verified in auth.py
   ✅ Authorization: role-based access, 4 tiers (Admin/SP/Inspector/Analyst) via
      require_role() decorator on every sensitive route in index.py
   ✅ SQL Injection: 100% of build_sql_query() branches use parameterized
      placeholders (?) + params list — 0 string-interpolated user input found
      in a code review of ai_engine.py's SQL-building logic
   ✅ CORS: permissive Access-Control-Allow-Origin ("*") configured in index.py —
      acceptable for this hackathon/POC deployment; would need origin allow-listing
      for a hardened production rollout
   ⚠️  Rate limiting: not implemented in index.py — Catalyst's platform-level
      throttling is the only current backstop  [gap, documented — not measured]
   ✅ Audit Trail: every /api/chat query is logged (session_id, original +
      translated query, intents, SQL, result count) via _log_query() → audit_log table

🎯 USER EXPERIENCE METRICS                                    [ESTIMATED / DOCUMENTED]
──────────────────────────────────────────────────────────────────────────────
   These require a live browser + real network conditions and were NOT
   captured by this backend-only benchmark script:
   • Page load, chart render time, mobile responsiveness, WCAG compliance —
     assess with browser DevTools Lighthouse / axe-core against the deployed
     Slate or Web Client URL for verifiable numbers.
   • Chat response P95 end-to-end (network + render) will be the [MEASURED]
     backend P95 above (avg 1.3ms) plus real network RTT + browser paint time.
```

---

## Methodology

1. **Response Time Analysis** — `tests/benchmark_performance.py` calls the exact functions `/api/chat` uses (`detect_intent`, `build_sql_query`, `execute_query`, `generate_natural_response`) directly against a freshly-seeded copy of the synthetic database, 200 times per query type after a 10-call warmup, and reports nearest-rank P50/P95/P99 percentiles (no numpy dependency, matches how percentiles are commonly reported in APM tooling).
2. **Database Performance** — real `os.path.getsize()` of the SQLite file, real `SELECT COUNT(*)` per table, and real `EXPLAIN QUERY PLAN` inspection of every benchmarked query's actual generated SQL against the current (indexed) schema. A reconstructed pre-index baseline is obtained by `DROP INDEX`-ing the recommended indexes on a throwaway copy of the database and re-running the same `EXPLAIN QUERY PLAN` + timing checks, giving an honest before/after comparison even though the indexes now ship by default in `synthetic_data.py`.
3. **Concurrency/Throughput** — a real `ThreadPoolExecutor` fires 300 requests across 50 concurrent workers, each opening an independent `sqlite3.connect()` (mirroring `index.py`'s per-request `get_db()`), and measures wall-clock throughput, error count, and latency distribution under contention.
4. **Data Accuracy** — real SQL aggregate queries against the seeded database check for duplicate FIR numbers, NULL required fields, and count distinct districts/stations/crime types/years actually present.
5. **Intent Detection Accuracy** — a hand-labeled 26-query test set is run through the real `detect_intent()` regex engine and scored for exact-match accuracy against expected intent labels.
6. **Resource Usage** — `psutil` measures this benchmark process's own RSS memory before and after a representative query burst.
7. **Security Audit** — items are verified by direct code inspection of `auth.py` and `index.py` (not a scan/pen-test tool), cross-checked against `build_sql_query()`'s SQL-construction logic for injection risk.
8. Metrics requiring live infrastructure, real user speech samples, or a browser environment (Catalyst cold-start/autoscaling, voice recognition accuracy, page load/WCAG audits) are explicitly marked `[ESTIMATED / DOCUMENTED]` rather than presented as measured facts.

## Recommendations

- **Index strategy — DONE.** This benchmark's reconstructed unindexed baseline showed **10/11** of the app's actual query shapes performing a full table scan (verified via `EXPLAIN QUERY PLAN`); the 11 indexes listed above are now applied directly in `synthetic_data.py`'s DDL, reducing that to **4/11** with no application-code changes required. Remaining scans are on small/low-cardinality lookup tables (e.g. `districts`, `police_stations` without a district filter) where a full scan is already fast enough not to warrant an index.
- Consider adding lightweight rate limiting (e.g. per-token request counters) ahead of a public production launch, since none currently exists in `index.py`.
- For a defensible "Voice Accuracy" or "WCAG Compliance" number in future reports, run a structured user test (recorded phrases + manual transcription review) or an automated axe-core/Lighthouse CI job against the deployed URL, and feed the results back into this report.
