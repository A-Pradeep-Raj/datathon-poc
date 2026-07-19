"""
Regression tests for response SHAPE correctness (see ai_engine.detect_response_shape).

These tests guard against the class of bug where a question's phrasing
("how many...") doesn't match the SHAPE of the answer returned (a raw
multi-row table instead of a single number, or vice versa), and against
answers drifting off-topic from what was actually asked (e.g. a "pending
cases" question silently answering with the total case count instead).

Each case is (query, expected_intent_prefix, expected_shape, expected_chart_type).
Run directly via build_sql_query() + execute_query() + generate_natural_response()
against a real synthetic database -- no HTTP server required.
"""
import os
import sys
import sqlite3
import unittest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "functions", "crime-chat-function"))

from synthetic_data import create_database
from ai_engine import (
    build_sql_query, execute_query, generate_natural_response,
    detect_intent, detect_response_shape,
)

DB_PATH = os.path.join(os.path.dirname(__file__), "_test_query_shapes.db")


class QueryShapeTests(unittest.TestCase):
    """Verifies that every (question) -> (intent, shape, chart_type, answer)
    mapping stays correct and on-topic across all intents."""

    @classmethod
    def setUpClass(cls):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        create_database(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

    def setUp(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()

    def _ask(self, query):
        """Run a query through the full pipeline and return
        (intents, shape, chart_type, results, response_text)."""
        intents = detect_intent(query)
        shape = detect_response_shape(query)
        sql, params, chart_type, resolved = build_sql_query(intents[0], query, self.conn, {})
        results = execute_query(self.conn, sql, params)
        response = generate_natural_response(query, intents, results, chart_type, resolved)
        return intents, shape, chart_type, results, response

    def _assert_count_answer(self, query, expected_intent=None):
        """A 'how many' question must resolve to shape=count, chart_type=number,
        exactly one row with a single numeric column, and the number must
        actually appear (formatted with thousands separators) in the response text."""
        intents, shape, chart_type, results, response = self._ask(query)
        self.assertEqual(shape, "count", f"{query!r} should be detected as a count-shaped question")
        self.assertEqual(chart_type, "number", f"{query!r} should produce chart_type='number', got {chart_type!r}")
        self.assertEqual(len(results), 1, f"{query!r} should return exactly one summary row, got {len(results)}")
        self.assertNotIn("error", results[0])
        row_values = list(results[0].values())
        self.assertEqual(len(row_values), 1, f"{query!r} count row should have exactly one column")
        count = row_values[0]
        self.assertIsInstance(count, int)
        self.assertIn(f"{count:,}", response, "the exact count must be echoed in the response text")
        if expected_intent:
            self.assertEqual(intents[0], expected_intent, f"{query!r} should map to intent {expected_intent!r}, got {intents[0]!r}")
        return count, response

    def _assert_detail_answer(self, query, expected_chart_types=None, expected_intent=None):
        """A 'show/list' question must resolve to shape=detail and NOT collapse
        to a single generic count row."""
        intents, shape, chart_type, results, response = self._ask(query)
        self.assertEqual(shape, "detail", f"{query!r} should be detected as a detail-shaped question")
        if expected_chart_types:
            self.assertIn(chart_type, expected_chart_types, f"{query!r} chart_type {chart_type!r} not in {expected_chart_types}")
        if expected_intent:
            self.assertEqual(intents[0], expected_intent, f"{query!r} should map to intent {expected_intent!r}, got {intents[0]!r}")
        return results, response

    # ── count_crimes ──────────────────────────────────────────────────────
    def test_total_crime_count(self):
        self._assert_count_answer("How many total crimes are there?", "count_crimes")

    def test_crime_count_in_named_district(self):
        count, response = self._assert_count_answer("How many crimes in Mysuru district?", "count_crimes")
        self.assertIn("Mysuru", response)

    # ── accused_search ────────────────────────────────────────────────────
    def test_wanted_accused_count_is_a_number_not_a_table(self):
        count, response = self._assert_count_answer("How many accused are still wanted?", "accused_search")
        self.assertIn("Wanted", response)

    def test_wanted_accused_list_is_a_detail_table(self):
        results, response = self._assert_detail_answer("Show me the wanted accused", ["table"], "accused_search")
        self.assertGreater(len(results), 0)
        # Every returned row must have real named columns (no flattened
        # field/value pairs) -- i.e. more than 2 keys per row for this query.
        self.assertGreater(len(results[0].keys()), 2)

    def test_gang_member_count(self):
        self._assert_count_answer("How many gang members are there?", "accused_search")

    # ── victim_stats ──────────────────────────────────────────────────────
    def test_victim_count(self):
        self._assert_count_answer("How many victims are there?", "victim_stats")

    def test_female_victim_count_is_filtered(self):
        count, response = self._assert_count_answer("How many female victims are there?", "victim_stats")
        self.assertIn("female", response.lower())

    def test_victim_breakdown_is_detail(self):
        self._assert_detail_answer("Show victim age and gender breakdown", ["bar"], "victim_stats")

    # ── case_status ───────────────────────────────────────────────────────
    def test_pending_cases_count_is_filtered_not_total(self):
        """Regression: 'how many cases are pending?' must NOT be answered as
        the unfiltered total case count (count_crimes intent hijacking)."""
        count, response = self._assert_count_answer("How many cases are pending?", "case_status")
        self.assertIn("Pending", response)

    def test_case_status_breakdown_is_detail(self):
        self._assert_detail_answer("Show case status breakdown", ["pie"], "case_status")

    # ── property_crime ────────────────────────────────────────────────────
    def test_specific_property_type_count(self):
        count, response = self._assert_count_answer("How many mobile phones were stolen?", "property_crime")
        self.assertIn("Mobile Phone", response)

    def test_property_breakdown_is_detail(self):
        self._assert_detail_answer("Show stolen property breakdown", ["bar"], "property_crime")

    # ── severity ──────────────────────────────────────────────────────────
    def test_severity_count(self):
        self._assert_count_answer("How many high severity cases are there?", "severity")

    def test_severity_detail_is_a_table(self):
        results, response = self._assert_detail_answer("Show me severe cases", ["table"], "severity")
        self.assertIn("High-Severity Cases", response)

    # ── crime_by_district ─────────────────────────────────────────────────
    def test_district_count(self):
        self._assert_count_answer("How many districts are there?", "crime_by_district")

    def test_district_breakdown_is_detail(self):
        self._assert_detail_answer("Show crimes by district", ["bar"], "crime_by_district")

    # ── hotspot ───────────────────────────────────────────────────────────
    def test_hotspot_count(self):
        self._assert_count_answer("How many hotspot stations are there?", "hotspot")

    def test_hotspot_detail_is_a_chart(self):
        self._assert_detail_answer("Show crime hotspots", ["bar"], "hotspot")

    # ── officer_stats (covers both officers and stations) ────────────────
    def test_officer_count(self):
        self._assert_count_answer("How many officers are there?", "officer_stats")

    def test_station_count_is_distinct_from_officer_count(self):
        """Regression: 'how many police stations?' and 'how many officers?'
        share the same intent but must count different tables/subjects."""
        officer_count, officer_resp = self._assert_count_answer("How many officers are there?", "officer_stats")
        station_count, station_resp = self._assert_count_answer("How many police stations are there?", "officer_stats")
        self.assertIn("officers", officer_resp.lower())
        self.assertIn("station", station_resp.lower())
        self.assertNotEqual(officer_count, station_count)

    def test_officer_detail_is_a_table(self):
        self._assert_detail_answer("Show officer performance", ["table"], "officer_stats")

    # ── universal guardrail ───────────────────────────────────────────────
    def test_no_count_question_ever_returns_a_multi_row_table(self):
        """Blanket regression check across every intent: any question whose
        shape is 'count' must always collapse to exactly one row, even for
        intents that don't have bespoke count-phrase handling yet."""
        count_questions = [
            "How many total crimes are there?",
            "How many crimes in Mysuru district?",
            "How many accused are still wanted?",
            "How many gang members are there?",
            "How many victims are there?",
            "How many female victims are there?",
            "How many cases are pending?",
            "How many mobile phones were stolen?",
            "How many high severity cases are there?",
            "How many districts are there?",
            "How many hotspot stations are there?",
            "How many officers are there?",
            "How many police stations are there?",
        ]
        for q in count_questions:
            intents, shape, chart_type, results, response = self._ask(q)
            self.assertEqual(shape, "count")
            self.assertEqual(chart_type, "number", f"{q!r} produced chart_type={chart_type!r} instead of 'number'")
            self.assertEqual(len(results), 1, f"{q!r} produced {len(results)} rows instead of exactly 1")


if __name__ == "__main__":
    unittest.main()
