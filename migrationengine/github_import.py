from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

from deployments.framework_detector import detect_framework


class GitHubImportError(Exception):
    pass


@dataclass(frozen=True)
class GitHubRepoRef:
    owner: str
    repo: str


GITHUB_URL_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:)?(?P<owner>[^/\s:]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


def parse_repo(value: str) -> GitHubRepoRef:
    text = value.strip()
    match = GITHUB_URL_RE.match(text)
    if not match:
        raise GitHubImportError("Enter a GitHub URL such as https://github.com/owner/repo.")
    return GitHubRepoRef(owner=match.group("owner"), repo=match.group("repo"))


def import_repository(repo_url: str, branch: str = "", access_token: str = "") -> dict[str, Any]:
    ref = parse_repo(repo_url)
    token = access_token.strip() or settings.GITHUB_TOKEN
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    repo = _get_json(session, f"/repos/{ref.owner}/{ref.repo}")
    default_branch = branch.strip() or repo.get("default_branch") or "main"
    branch_data = _get_json(session, f"/repos/{ref.owner}/{ref.repo}/branches/{default_branch}")
    tree_sha = branch_data.get("commit", {}).get("commit", {}).get("tree", {}).get("sha")
    if not tree_sha:
        raise GitHubImportError("GitHub did not return a tree SHA for that branch.")

    tree = _get_json(session, f"/repos/{ref.owner}/{ref.repo}/git/trees/{tree_sha}?recursive=1")
    files = sorted(
        item["path"]
        for item in tree.get("tree", [])
        if item.get("type") == "blob" and isinstance(item.get("path"), str)
    )
    package_json = _load_package_json(session, ref, default_branch, files)
    framework = detect_framework(files, package_json)

    return {
        "repository": {
            "owner": ref.owner,
            "name": ref.repo,
            "fullName": repo.get("full_name") or f"{ref.owner}/{ref.repo}",
            "url": repo.get("html_url") or f"https://github.com/{ref.owner}/{ref.repo}",
            "branch": default_branch,
            "private": bool(repo.get("private")),
            "defaultBranch": repo.get("default_branch"),
        },
        "files": files,
        "packageJson": package_json,
        "framework": framework.to_dict(),
        "project": {
            "appName": _safe_app_name(ref.repo),
            "repoUrl": repo.get("html_url") or f"https://github.com/{ref.owner}/{ref.repo}",
            "branch": default_branch,
            "files": files,
            "packageJson": package_json,
            "environment": {},
            "secrets": [],
        },
        "limits": {
            "fileCount": len(files),
            "packageJsonFound": package_json is not None,
        },
    }


def _get_json(session: requests.Session, path: str) -> dict[str, Any]:
    base = settings.GITHUB_API_BASE_URL.rstrip("/")
    try:
        response = session.get(f"{base}{path}", timeout=20)
    except requests.RequestException as exc:
        raise GitHubImportError("Could not reach GitHub.") from exc
    if response.status_code == 404:
        raise GitHubImportError("GitHub repository or branch was not found.")
    if response.status_code in {401, 403}:
        raise GitHubImportError("GitHub access denied. Connect a token for private repos or higher rate limits.")
    if response.status_code >= 400:
        raise GitHubImportError(f"GitHub returned HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise GitHubImportError("GitHub returned an invalid JSON response.") from exc


def _load_package_json(
    session: requests.Session, ref: GitHubRepoRef, branch: str, files: list[str]
) -> dict[str, Any] | None:
    candidates = [path for path in files if path.lower().endswith("package.json")]
    preferred = "package.json" if "package.json" in candidates else (candidates[0] if candidates else "")
    if not preferred:
        return None
    data = _get_json(session, f"/repos/{ref.owner}/{ref.repo}/contents/{preferred}?ref={branch}")
    encoded = data.get("content")
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded).decode("utf-8")
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _safe_app_name(repo_name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", repo_name.lower()).strip("-") or "github-app"


ENV_TEMPLATE_CANDIDATES = (
    ".env.example",
    "env.example",
    ".env.template",
    "env.template",
    ".env.sample",
)


def _github_session(access_token: str = "") -> requests.Session:
    token = access_token.strip() or settings.GITHUB_TOKEN
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def fetch_repo_text_file(repo_url: str, file_path: str, branch: str = "", access_token: str = "") -> str | None:
    """Return decoded text for a single file in a GitHub repo, or None if missing."""
    ref = parse_repo(repo_url)
    session = _github_session(access_token)
    repo = _get_json(session, f"/repos/{ref.owner}/{ref.repo}")
    ref_name = branch.strip() or repo.get("default_branch") or "main"
    try:
        data = _get_json(session, f"/repos/{ref.owner}/{ref.repo}/contents/{file_path}?ref={ref_name}")
    except GitHubImportError:
        return None
    encoded = data.get("content")
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def scan_stripe_env_keys_from_github(repo_url: str, branch: str = "", access_token: str = "") -> dict[str, Any]:
    """List STRIPE_* variable names declared in env template files (never secret values)."""
    keys: list[str] = []
    matched_file = ""
    for candidate in ENV_TEMPLATE_CANDIDATES:
        text = fetch_repo_text_file(repo_url, candidate, branch=branch, access_token=access_token)
        if not text:
            continue
        matched_file = candidate
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if key.startswith("STRIPE_"):
                keys.append(key)
        if keys:
            break
    return {
        "repoUrl": repo_url,
        "envTemplateFile": matched_file or None,
        "stripeKeys": sorted(set(keys)),
    }
