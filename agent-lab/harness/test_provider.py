from __future__ import annotations

import unittest

import provider as MODULE


class ProviderTests(unittest.TestCase):
    def test_local_provider_is_the_default_and_public_metadata_has_no_secret_field(self) -> None:
        config = MODULE.normalize_provider_config({"model": "local-model"})
        public = MODULE.public_provider(config, has_api_key=True)

        self.assertEqual(config["provider"], "local")
        self.assertEqual(public["provider"], "local")
        self.assertFalse(public["has_api_key"])
        self.assertNotIn("api_key", public)

    def test_remote_endpoint_rejects_embedded_credentials_and_query_parameters(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.normalize_endpoint("https://user:pass@example.test/chat")
        with self.assertRaises(ValueError):
            MODULE.normalize_endpoint("https://example.test/chat?api_key=secret")

    def test_remote_provider_requires_endpoint_and_model(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.normalize_provider_config({"provider": "openai_compatible", "model": "model"})
        with self.assertRaises(ValueError):
            MODULE.normalize_provider_config({"provider": "openai_compatible", "endpoint": MODULE.DEFAULT_REMOTE_ENDPOINT})

    def test_public_remote_metadata_reports_only_that_a_key_exists(self) -> None:
        config = MODULE.normalize_provider_config(
            {
                "provider": "openai-compatible",
                "endpoint": MODULE.DEFAULT_REMOTE_ENDPOINT,
                "model": "remote-model",
            }
        )
        public = MODULE.public_provider(config, has_api_key=True)

        self.assertEqual(public["provider"], "openai_compatible")
        self.assertTrue(public["has_api_key"])
        self.assertNotIn("secret", str(public))


if __name__ == "__main__":
    unittest.main()

