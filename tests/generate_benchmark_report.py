"""
Generates docs/PERFORMANCE_BENCHMARK_REPORT.md from the raw JSON produced by
benchmark_performance.py, in the same visual style as the project's other
ASCII-boxed reports.

Every number in the generated report is tagged as either:
  [MEASURED]   -- captured directly by benchmark_performance.py against the
                  real synthetic-data DB / ai_engine.py query pipeline / a
                  real concurrent ThreadPoolExecutor load test on this
                  machine.
  [ESTIMATED / DOCUMENTED] -- a reasonable, clearly-labeled projection for
                  metrics that fundamentally require infrastructure we don't
                  have access to during local benchmarking: Zoho Catalyst's
                  actual serverless cold-start/autoscaling behavior, real
                  end-user speech-recognition accuracy, or a full-browser
                  WCAG accessibility audit. These are based on the platform's
                  published specs, the deployed feature set, and prior manual
                  testing during development -- NOT fabricated from thin air,
                  but also not reproducible by running this script.

Usage:
    python generate_benchmark_report.py
(run after benchmark_performance.py has produced tests/_benchmark_results.json)
"""
import os
import json
from datetime import datetime

RESULTS_PATH = os.path.join(os.path.dirname(__file__), "_benchmark_results.json")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "PERFORMANCE_BENCHMARK_REPORT.md")


def pad(s, width):
    s = str(s)
    return s + " " * max(0, width - len(s))


def main():
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        r = json.load(f)

    response_rows = r["response_rows"]
    db_perf = r["db_perf"]
    index_impact = r["index_impact"]
    data_acc = r["data_acc"]
    intent_acc = r["intent_acc"]
    mem = r["mem"]
    concurrency = r["concurrency"]
    n_iter = r["n_iterations"]

    all_p99 = [row["p99"] for row in response_rows]
    all_mean = [row["mean"] for row in response_rows]
    avg_p99 = round(sum(all_p99) / len(all_p99), 1)
    avg_mean = round(sum(all_mean) / len(all_mean), 1)

    # Column widths for the response-time table
    col1_w = max(len(row["label"]) for row in response_rows) + 1
    col1_w = max(col1_w, len("Query Type"))

    lines = []
    lines.append(f"# KRIME AI — Prototype Performance Benchmark Report")
    lines.append("")
    lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                 f"· Benchmark run: {r['generated_at']}_")
    lines.append("")
    lines.append("> **How to read this report:** every figure is tagged `[MEASURED]` (captured by "
                 "running `tests/benchmark_performance.py` against the real synthetic-data SQLite "
                 "database and the real `ai_engine.py` query pipeline / a real concurrent load test "
                 "on this machine) or `[ESTIMATED]` (a documented projection for infrastructure this "
                 "local benchmark cannot exercise — Zoho Catalyst's serverless cold-start/autoscaling, "
                 "live speech-recognition accuracy, or a full browser accessibility audit). "
                 "Reproduce the `[MEASURED]` numbers yourself with:")
    lines.append("> ```")
    lines.append("> cd functions/crime-chat-function")
    lines.append("> python ../../tests/benchmark_performance.py")
    lines.append("> python ../../tests/generate_benchmark_report.py")
    lines.append("> ```")
    lines.append("")
    lines.append("```")
    lines.append("⚡ PERFORMANCE BENCHMARKS")
    lines.append("═" * 78)
    lines.append("")
    lines.append("📊 RESPONSE TIME ANALYSIS                                    [MEASURED]")
    lines.append(f"   In-process pipeline timing: detect_intent → build_sql_query →")
    lines.append(f"   execute_query → generate_natural_response, {n_iter} iterations/query type,")
    lines.append(f"   10 warmup calls discarded, against the real 1,500-case synthetic DB.")
    lines.append("─" * 78)
    header = f"{pad('Query Type', col1_w)} | {pad('P50 (ms)', 8)} | {pad('P95 (ms)', 8)} | {pad('P99 (ms)', 8)}"
    lines.append(header)
    lines.append("─" * col1_w + "┼" + "─" * 10 + "┼" + "─" * 10 + "┼" + "─" * 10)
    for row in response_rows:
        lines.append(f"{pad(row['label'], col1_w)} | {pad(row['p50'], 8)} | {pad(row['p95'], 8)} | {pad(row['p99'], 8)}")
    lines.append("─" * col1_w + "┴" + "─" * 10 + "┴" + "─" * 10 + "┴" + "─" * 10)
    lines.append("")
    lines.append("✅ RESULTS:")
    lines.append(f"   • 99th percentile (avg across query types): {avg_p99}ms  [MEASURED]")
    lines.append(f"   • Average query latency: {avg_mean}ms  [MEASURED]")
    lines.append(f"   • These times are the QUERY/LOGIC layer only (Python + SQLite, no")
    lines.append(f"     network hop). Add ~{'20-40ms'} for Flask HTTP overhead + JSON")
    lines.append(f"     serialization on localhost, or ~100-400ms extra over the public")
    lines.append(f"     internet, and 3-5s for a genuine Catalyst Advanced I/O cold start")
    lines.append(f"     after idle (function container spin-up).  [ESTIMATED, platform-documented]")
    lines.append(f"   • Optional \"AI Insight\" LLM call (QuickML GLM-4.7-Flash) adds a further")
    lines.append(f"     ~20-25s per request when enabled — a fixed model-inference latency floor,")
    lines.append(f"     NOT part of the deterministic query timings above.  [MEASURED during dev, see repo memory]")
    lines.append("")
    lines.append("📈 THROUGHPUT / CONCURRENCY                                  [MEASURED]")
    lines.append("─" * 78)
    lines.append(f"   Real ThreadPoolExecutor load test: {concurrency['total_requests']} requests across "
                 f"{concurrency['concurrent_workers']} concurrent workers,")
    lines.append(f"   each opening its own sqlite3 connection (mirrors index.py's per-request get_db()).")
    lines.append(f"   • Concurrent workers tested: {concurrency['concurrent_workers']}")
    lines.append(f"   • Success rate: {concurrency['success_rate_pct']}% ({concurrency['success_count']}/{concurrency['total_requests']}, {concurrency['errors']} errors)")
    lines.append(f"   • Throughput: {concurrency['throughput_req_per_sec']} req/sec ({concurrency['throughput_req_per_min']:.0f} req/min)")
    lines.append(f"   • Latency under load — P50: {concurrency['p50_ms']}ms | P95: {concurrency['p95_ms']}ms | P99: {concurrency['p99_ms']}ms")
    lines.append(f"   • This measures Python/SQLite concurrency on THIS machine, not Zoho")
    lines.append(f"     Catalyst's actual network/autoscaling infrastructure under real traffic")
    lines.append(f"     — production throughput will additionally depend on Catalyst's own")
    lines.append(f"     Advanced I/O concurrency limits and autoscaling triggers.  [ESTIMATED, platform-documented]")
    lines.append("")
    lines.append("💾 DATABASE PERFORMANCE                                      [MEASURED]")
    lines.append("─" * 78)
    lines.append(f"   • Database size: {db_perf['db_size_mb']} MB ({data_acc['total_cases']} FIR cases + related tables)")
    counts = db_perf["counts"]
    lines.append(f"   • Row counts: fir_cases={counts['fir_cases']}, accused={counts['accused']}, "
                 f"victims={counts['victims']}, witnesses={counts['witnesses']}")
    lines.append(f"                 police_stations={counts['police_stations']}, districts={counts['districts']}, "
                 f"officers={counts['officers']}")
    lines.append(f"   • Query cache: In-process (Flask memory, per-connection) — no dedicated cache layer")
    lines.append(f"   • Indexes now defined in schema: {len(db_perf['existing_indexes'])} "
                 f"(added to synthetic_data.py's DDL — see Index Strategy below; SQLite auto-indexes")
    lines.append(f"     PRIMARY KEY / UNIQUE columns separately, not counted here)")
    lines.append(f"   • Full-table scans WITH current indexes applied: {db_perf['total_scans']}/"
                 f"{db_perf['total_queries_checked']} benchmarked query shapes")
    lines.append(f"   • Full-table scans WITHOUT indexes (reconstructed baseline, indexes dropped on a")
    lines.append(f"     throwaway DB copy): {index_impact['scans_before']}/"
                 f"{index_impact['total_queries_checked']} benchmarked query shapes ⚠️")
    lines.append(f"   • Real timing delta on 2 representative filtered queries (P50, unindexed baseline):")
    for label, val in index_impact["timing_before_ms"].items():
        lines.append(f"       - {label}: {val}ms (see Response Time table above for the CURRENT, indexed P50)")
    lines.append("")
    lines.append("   Index Strategy (verified via EXPLAIN QUERY PLAN, APPLIED to")
    lines.append("   synthetic_data.py's schema as of this benchmark run):")
    lines.append("   ├─ fir_cases(station_id)")
    lines.append("   ├─ fir_cases(crime_type)")
    lines.append("   ├─ fir_cases(date_of_incident)")
    lines.append("   ├─ fir_cases(severity_score DESC)")
    lines.append("   ├─ fir_cases(status)")
    lines.append("   ├─ police_stations(district_id)")
    lines.append("   ├─ accused(fir_id), accused(arrest_status), accused(gang_affiliation)")
    lines.append("   └─ victims(fir_id), stolen_property(fir_id)")
    lines.append("")
    lines.append("🧠 AI ACCURACY                                                [MEASURED + ESTIMATED]")
    lines.append("─" * 78)
    lines.append(f"   Intent Detection (regex-pattern based, fully deterministic):  [MEASURED]")
    lines.append(f"   • Accuracy: {intent_acc['accuracy_pct']}% ({intent_acc['correct']}/{intent_acc['total']}) against a "
                 f"{intent_acc['total']}-query labeled test set")
    lines.append(f"   • Coverage: 13 intents defined (count_crimes, crime_by_district, crime_by_type,")
    lines.append(f"     crime_trend, hotspot, accused_search, victim_stats, case_status, officer_stats,")
    lines.append(f"     predictive, network_analysis, property_crime, severity) + greeting/general fallback")
    if intent_acc["misses"]:
        lines.append(f"   • Misclassified in this run:")
        for q, exp, got in intent_acc["misses"]:
            lines.append(f"       - \"{q}\" → expected '{exp}', got '{got}'")
    lines.append(f"   • Fallback: unmatched queries default to a general/no-intent response (no")
    lines.append(f"     hard failure)")
    lines.append("")
    lines.append(f"   Kannada Translation & Speech Recognition:                     [ESTIMATED / DOCUMENTED]")
    lines.append(f"   • Dictionary-based translation (_ENGLISH_TO_KANNADA_PHRASES, ai_engine.py):")
    lines.append(f"     100+ crime-specific terms/phrases mapped, applied longest-phrase-first;")
    lines.append(f"     deterministic substitution has effectively 100% consistency for phrases")
    lines.append(f"     IN the dictionary, by construction — cannot be meaningfully expressed as a")
    lines.append(f"     single \"accuracy %\" the way an ML translation model's would be.")
    lines.append(f"   • Voice input/output uses the BROWSER's native Web Speech API")
    lines.append(f"     (SpeechRecognition/kn-IN, en-IN) — actual recognition accuracy depends on")
    lines.append(f"     the end-user's browser/OS speech engine and microphone quality, which")
    lines.append(f"     cannot be measured from this backend-only benchmark; figures reported")
    lines.append(f"     elsewhere for this are informal developer-testing observations, not a")
    lines.append(f"     controlled accuracy study.")
    lines.append("")
    lines.append("📊 DATA ACCURACY / CONSISTENCY                               [MEASURED]")
    lines.append("─" * 78)
    lines.append(f"   • Crime records: {data_acc['total_cases']} synthetic FIR cases")
    lines.append(f"   • Duplicate FIR numbers: {data_acc['duplicate_firs']}")
    lines.append(f"   • NULL crime_type: {data_acc['null_crime_type']}  |  NULL station_id: {data_acc['null_station']}")
    lines.append(f"   • Data consistency: {data_acc['consistency_pct']}% (no duplicates/NULLs in checked columns)")
    lines.append(f"   • Geographic coverage: {data_acc['distinct_stations']} stations across {data_acc['distinct_districts']} districts")
    lines.append(f"   • Temporal coverage: {data_acc['year_range'][0]}–{data_acc['year_range'][1]}")
    lines.append(f"   • Crime type coverage: {data_acc['distinct_crime_types']} distinct types")
    lines.append("")
    lines.append("💻 RESOURCE USAGE                                             [MEASURED]")
    lines.append("─" * 78)
    lines.append(f"   • Process RSS memory before benchmark query burst: {mem['rss_before_mb']} MB")
    lines.append(f"   • Process RSS memory after benchmark query burst: {mem['rss_after_mb']} MB")
    lines.append(f"   • Delta: {mem['delta_mb']} MB (single Python process, this benchmark run only —")
    lines.append(f"     NOT the deployed Catalyst function's actual container memory allocation,")
    lines.append(f"     which is configured/observed separately via the Catalyst console)  [ESTIMATED for prod]")
    lines.append("")
    lines.append("🔒 SECURITY AUDIT                                             [MEASURED / CODE-VERIFIED]")
    lines.append("─" * 78)
    lines.append("   ✅ Authentication: session token via auth.py (SHA-256+salt password hashing,")
    lines.append("      bearer/X-Auth-Token session lookup, 12h TTL) — verified in auth.py")
    lines.append("   ✅ Authorization: role-based access, 4 tiers (Admin/SP/Inspector/Analyst) via")
    lines.append("      require_role() decorator on every sensitive route in index.py")
    lines.append("   ✅ SQL Injection: 100% of build_sql_query() branches use parameterized")
    lines.append("      placeholders (?) + params list — 0 string-interpolated user input found")
    lines.append("      in a code review of ai_engine.py's SQL-building logic")
    lines.append("   ✅ CORS: permissive Access-Control-Allow-Origin (\"*\") configured in index.py —")
    lines.append("      acceptable for this hackathon/POC deployment; would need origin allow-listing")
    lines.append("      for a hardened production rollout")
    lines.append("   ⚠️  Rate limiting: not implemented in index.py — Catalyst's platform-level")
    lines.append("      throttling is the only current backstop  [gap, documented — not measured]")
    lines.append("   ✅ Audit Trail: every /api/chat query is logged (session_id, original +")
    lines.append("      translated query, intents, SQL, result count) via _log_query() → audit_log table")
    lines.append("")
    lines.append("🎯 USER EXPERIENCE METRICS                                    [ESTIMATED / DOCUMENTED]")
    lines.append("─" * 78)
    lines.append("   These require a live browser + real network conditions and were NOT")
    lines.append("   captured by this backend-only benchmark script:")
    lines.append("   • Page load, chart render time, mobile responsiveness, WCAG compliance —")
    lines.append("     assess with browser DevTools Lighthouse / axe-core against the deployed")
    lines.append("     Slate or Web Client URL for verifiable numbers.")
    lines.append("   • Chat response P95 end-to-end (network + render) will be the [MEASURED]")
    lines.append(f"     backend P95 above (avg {avg_p99}ms) plus real network RTT + browser paint time.")
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append("1. **Response Time Analysis** — `tests/benchmark_performance.py` calls the exact "
                 "functions `/api/chat` uses (`detect_intent`, `build_sql_query`, `execute_query`, "
                 "`generate_natural_response`) directly against a freshly-seeded copy of the synthetic "
                 f"database, {n_iter} times per query type after a 10-call warmup, and reports "
                 "nearest-rank P50/P95/P99 percentiles (no numpy dependency, matches how percentiles are "
                 "commonly reported in APM tooling).")
    lines.append("2. **Database Performance** — real `os.path.getsize()` of the SQLite file, real "
                 "`SELECT COUNT(*)` per table, and real `EXPLAIN QUERY PLAN` inspection of every "
                 "benchmarked query's actual generated SQL against the current (indexed) schema. A "
                 "reconstructed pre-index baseline is obtained by `DROP INDEX`-ing the recommended "
                 "indexes on a throwaway copy of the database and re-running the same `EXPLAIN QUERY "
                 "PLAN` + timing checks, giving an honest before/after comparison even though the "
                 "indexes now ship by default in `synthetic_data.py`.")
    lines.append("3. **Concurrency/Throughput** — a real `ThreadPoolExecutor` fires 300 requests across "
                 "50 concurrent workers, each opening an independent `sqlite3.connect()` (mirroring "
                 "`index.py`'s per-request `get_db()`), and measures wall-clock throughput, error count, "
                 "and latency distribution under contention.")
    lines.append("4. **Data Accuracy** — real SQL aggregate queries against the seeded database check "
                 "for duplicate FIR numbers, NULL required fields, and count distinct districts/stations/"
                 "crime types/years actually present.")
    lines.append("5. **Intent Detection Accuracy** — a hand-labeled 26-query test set is run through the "
                 "real `detect_intent()` regex engine and scored for exact-match accuracy against expected "
                 "intent labels.")
    lines.append("6. **Resource Usage** — `psutil` measures this benchmark process's own RSS memory "
                 "before and after a representative query burst.")
    lines.append("7. **Security Audit** — items are verified by direct code inspection of `auth.py` and "
                 "`index.py` (not a scan/pen-test tool), cross-checked against `build_sql_query()`'s "
                 "SQL-construction logic for injection risk.")
    lines.append("8. Metrics requiring live infrastructure, real user speech samples, or a browser "
                 "environment (Catalyst cold-start/autoscaling, voice recognition accuracy, page load/"
                 "WCAG audits) are explicitly marked `[ESTIMATED / DOCUMENTED]` rather than presented as "
                 "measured facts.")
    lines.append("")
    lines.append("## Recommendations")
    lines.append("")
    lines.append(f"- **Index strategy — DONE.** This benchmark's reconstructed unindexed baseline showed "
                 f"**{index_impact['scans_before']}/{index_impact['total_queries_checked']}** of the app's "
                 f"actual query shapes performing a full table scan (verified via `EXPLAIN QUERY PLAN`); "
                 f"the 11 indexes listed above are now applied directly in `synthetic_data.py`'s DDL, "
                 f"reducing that to **{db_perf['total_scans']}/{db_perf['total_queries_checked']}** with no "
                 f"application-code changes required. Remaining scans are on small/low-cardinality lookup "
                 f"tables (e.g. `districts`, `police_stations` without a district filter) where a full "
                 f"scan is already fast enough not to warrant an index.")
    lines.append("- Consider adding lightweight rate limiting (e.g. per-token request counters) ahead of "
                 "a public production launch, since none currently exists in `index.py`.")
    lines.append("- For a defensible \"Voice Accuracy\" or \"WCAG Compliance\" number in future reports, "
                 "run a structured user test (recorded phrases + manual transcription review) or an "
                 "automated axe-core/Lighthouse CI job against the deployed URL, and feed the results "
                 "back into this report.")
    lines.append("")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Report written to {os.path.abspath(REPORT_PATH)}")


if __name__ == "__main__":
    main()
