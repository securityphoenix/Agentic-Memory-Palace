import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import scan_sensitive_data  # noqa: E402


class SensitiveScanTests(unittest.TestCase):
    def test_detects_sensitive_token_in_text(self):
        token = "github_pat_" + "A" * 24

        findings = scan_sensitive_data.scan_text(f"token={token}\n", source="session.md")

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].source, "session.md")
        self.assertEqual(findings[0].line_number, 1)
        self.assertEqual(findings[0].rule, "github_pat")
        self.assertNotIn(token, scan_sensitive_data.format_findings(findings))

    def test_allows_placeholder_secret_examples(self):
        findings = scan_sensitive_data.scan_text(
            "api_key=placeholder_abcdefghijklmnopqrstuvwxyz123456\n",
            source="docs.md",
        )

        self.assertEqual(findings, [])

    def test_assert_text_safe_fails_closed(self):
        token = "xoxb-" + "1" * 12

        with self.assertRaises(scan_sensitive_data.SensitiveDataError) as caught:
            scan_sensitive_data.assert_text_safe(f"slack={token}\n", source="flush-output.md")

        message = str(caught.exception)
        self.assertIn("flush-output.md:1 [slack_token]", message)
        self.assertNotIn(token, message)


if __name__ == "__main__":
    unittest.main()
