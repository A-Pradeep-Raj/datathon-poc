import os
import sys
import unittest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "functions", "crime-chat-function"))

from ai_engine import detect_greeting, generate_natural_response


class GreetingBehaviorTests(unittest.TestCase):
    def test_hi_is_recognized_as_greeting(self):
        self.assertTrue(detect_greeting("hi"))
        self.assertTrue(detect_greeting("Hello there"))

    def test_crime_query_is_not_treated_as_greeting(self):
        self.assertFalse(detect_greeting("show crimes by district"))
        self.assertFalse(detect_greeting("how many total crimes"))

    def test_greeting_response_is_generated(self):
        response = generate_natural_response("hi", ["greeting"], [], "none")
        self.assertIn("Hello", response)
        self.assertIn("What would you like to know", response)


if __name__ == "__main__":
    unittest.main()
