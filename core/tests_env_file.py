from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from core.env_file import apply_env_updates, can_auto_apply_dotenv, merge_dotenv_file


@override_settings(ON_RAILWAY=False)
class EnvFileTests(SimpleTestCase):
    def test_merge_dotenv_preserves_comments_and_updates_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "# Stripe\nSTRIPE_SECRET_KEY=\nPORT=8000\n",
                encoding="utf-8",
            )
            keys = merge_dotenv_file(path, {"STRIPE_SECRET_KEY": "sk_test_abc", "STRIPE_PUBLISHABLE_KEY": "pk_test"})
            text = path.read_text(encoding="utf-8")

            self.assertIn("STRIPE_SECRET_KEY=sk_test_abc", text)
            self.assertIn("STRIPE_PUBLISHABLE_KEY=pk_test", text)
            self.assertIn("# Stripe", text)
            self.assertIn("PORT=8000", text)
            self.assertEqual(sorted(keys), ["STRIPE_PUBLISHABLE_KEY", "STRIPE_SECRET_KEY"])

    @override_settings(ON_RAILWAY=True)
    def test_auto_apply_disabled_on_railway_host(self):
        self.assertFalse(can_auto_apply_dotenv())

    @override_settings(ON_RAILWAY=False, STRIPE_SECRET_KEY="")
    def test_apply_env_updates_writes_and_reloads_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.env_file.dotenv_path", return_value=Path(tmp) / ".env"):
                result = apply_env_updates({"STRIPE_SECRET_KEY": "sk_live_reload"})
            self.assertTrue(result["applied"])
            self.assertEqual(result["keys"], ["STRIPE_SECRET_KEY"])

            from django.conf import settings

            self.assertEqual(settings.STRIPE_SECRET_KEY, "sk_live_reload")
