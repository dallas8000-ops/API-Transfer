import unittest

from migrationengine.providers import merge_service_env_vars


class MergeServiceEnvVarsTests(unittest.TestCase):
    def test_preserves_existing_secrets_when_incoming_value_empty(self):
        existing = {"STRIPE_SECRET_KEY": "sk_live_abc", "PORT": "8000"}
        incoming = {"PORT": "3000", "STRIPE_SECRET_KEY": "", "NODE_ENV": ""}

        merged = merge_service_env_vars(existing, incoming)

        self.assertEqual(merged["STRIPE_SECRET_KEY"], "sk_live_abc")
        self.assertEqual(merged["PORT"], "3000")
        self.assertNotIn("NODE_ENV", merged)

    def test_incoming_non_empty_values_win(self):
        existing = {"DATABASE_URL": "postgres://old", "API_KEY": "old-key"}
        incoming = {"DATABASE_URL": "postgres://new", "API_KEY": "new-key"}

        merged = merge_service_env_vars(existing, incoming)

        self.assertEqual(merged["DATABASE_URL"], "postgres://new")
        self.assertEqual(merged["API_KEY"], "new-key")

    def test_adds_new_keys_from_incoming(self):
        existing = {"PORT": "8000"}
        incoming = {"PORT": "8000", "JWT_SECRET": "secret-value"}

        merged = merge_service_env_vars(existing, incoming)

        self.assertEqual(merged["JWT_SECRET"], "secret-value")
