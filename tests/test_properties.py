"""Optional generated properties. Stdlib-only runs report a clear skip."""
import unittest
from local_ai.config import FLAGS
from local_ai.redact import redact
from local_ai.route import route

try:
    from hypothesis import given, strategies as st
except ImportError:
    class OptionalProperties(unittest.TestCase):
        @unittest.skip("Install the dev extra for Hypothesis-generated properties")
        def test_hypothesis(self):
            pass
else:
    class GeneratedProperties(unittest.TestCase):
        @given(st.lists(st.sampled_from(["public", "personal", "confidential", "secret"]), min_size=1),
               st.fixed_dictionaries({name: st.booleans() for name in FLAGS}))
        def test_policy_permission(self, tiers, settings):
            verdict = route(tiers, settings)
            if verdict["path"] == "cloud_ai":
                self.assertTrue(settings["cloud_ai_enabled"])
                if verdict["max_tier"] != "public":
                    self.assertTrue(settings["send_" + verdict["max_tier"] + "_data_to_cloud"])

        @given(st.text(max_size=1000))
        def test_redaction_idempotent(self, text):
            once, _ = redact(text)
            self.assertEqual(redact(once)[0], once)
