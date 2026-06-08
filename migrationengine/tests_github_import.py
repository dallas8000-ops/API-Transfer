from __future__ import annotations

import base64
import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from .github_import import GitHubImportError, import_repository, parse_repo


class GitHubImportTests(SimpleTestCase):
    def test_parse_repo_accepts_https_and_git_urls(self):
        https_ref = parse_repo("https://github.com/example/api-transfer")
        git_ref = parse_repo("git@github.com:example/api-transfer.git")

        self.assertEqual(https_ref.owner, "example")
        self.assertEqual(https_ref.repo, "api-transfer")
        self.assertEqual(git_ref.owner, "example")
        self.assertEqual(git_ref.repo, "api-transfer")

    def test_parse_repo_rejects_non_github_urls(self):
        with self.assertRaises(GitHubImportError):
            parse_repo("https://gitlab.com/example/api-transfer")

    @override_settings(GITHUB_API_BASE_URL="https://api.github.test", GITHUB_TOKEN="")
    def test_import_repository_extracts_files_package_json_and_framework(self):
        package_json = {
            "dependencies": {"next": "^14.0.0", "react": "^18.0.0"},
            "scripts": {"build": "next build", "start": "next start"},
        }
        encoded_package = base64.b64encode(json.dumps(package_json).encode("utf-8")).decode("ascii")
        responses = [
            _response({"full_name": "example/web", "html_url": "https://github.com/example/web", "default_branch": "main", "private": False}),
            _response({"commit": {"commit": {"tree": {"sha": "tree-sha"}}}}),
            _response({"tree": [{"type": "blob", "path": "package.json"}, {"type": "blob", "path": "next.config.js"}]}),
            _response({"content": encoded_package}),
        ]

        with patch("requests.Session.get", side_effect=responses):
            result = import_repository("https://github.com/example/web")

        self.assertEqual(result["repository"]["fullName"], "example/web")
        self.assertEqual(result["project"]["appName"], "web")
        self.assertEqual(result["packageJson"]["dependencies"]["next"], "^14.0.0")
        self.assertEqual(result["framework"]["framework"], "nextjs")
        self.assertTrue(result["limits"]["packageJsonFound"])


def _response(payload: dict, status_code: int = 200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    return response
