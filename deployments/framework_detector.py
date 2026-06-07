"""Deterministic framework detection from project file paths and dependencies."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DetectedFramework:
    framework: str
    runtime: str
    default_port: int
    confidence: int
    build_command: str | None = None
    start_command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": self.framework,
            "runtime": self.runtime,
            "defaultPort": self.default_port,
            "confidence": self.confidence,
            "buildCommand": self.build_command,
            "startCommand": self.start_command,
        }


@dataclass(frozen=True)
class _Signature:
    framework: str
    runtime: str
    default_port: int
    file_matchers: list[re.Pattern[str]]
    dependency_matchers: list[str] = field(default_factory=list)
    build_command: str | None = None
    start_command: str | None = None


def _rx(*patterns: str) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


SIGNATURES: list[_Signature] = [
    _Signature("nextjs", "node", 3000, _rx(r"next\.config\.(js|ts|mjs)$"), ["next"], "npm run build", "npm run start"),
    _Signature("nestjs", "node", 3000, _rx(r"nest-cli\.json$"), ["@nestjs/core"], "npm run build", "node dist/main.js"),
    _Signature("express", "node", 3000, _rx(r"server\.(js|ts)$", r"app\.(js|ts)$"), ["express"], "npm install", "node server.js"),
    _Signature("react", "static", 80, _rx(r"vite\.config\.(js|ts)$"), ["react", "vite"], "npm run build", None),
    _Signature("vue", "static", 80, _rx(r"vue\.config\.(js|ts)$"), ["vue"], "npm run build", None),
    _Signature("django", "python", 8000, _rx(r"manage\.py$"), [], "pip install -r requirements.txt", "gunicorn wsgi:application"),
    _Signature("fastapi", "python", 8000, _rx(r"main\.py$"), ["fastapi"], "pip install -r requirements.txt", "uvicorn main:app --host 0.0.0.0"),
    _Signature("flask", "python", 5000, _rx(r"app\.py$", r"wsgi\.py$"), [], "pip install -r requirements.txt", "gunicorn app:app"),
    _Signature("go", "go", 8080, _rx(r"go\.mod$", r"main\.go$"), [], "go build -o app", "./app"),
    _Signature("static", "static", 80, _rx(r"index\.html$"), [], None, None),
]


def _collect_dependencies(package_json: dict[str, Any] | None) -> set[str]:
    deps: set[str] = set()
    if not package_json:
        return deps
    for field_name in ("dependencies", "devDependencies"):
        section = package_json.get(field_name)
        if isinstance(section, dict):
            deps.update(section.keys())
    return deps


def detect_framework(files: list[str], package_json: dict[str, Any] | None = None) -> DetectedFramework:
    lowered = [f.lower() for f in files]
    deps = _collect_dependencies(package_json)

    best: tuple[_Signature, int] | None = None
    for signature in SIGNATURES:
        score = 0
        for matcher in signature.file_matchers:
            if any(matcher.search(f) for f in lowered):
                score += 2
        for dep in signature.dependency_matchers:
            if dep in deps:
                score += 3
        if score > 0 and (best is None or score > best[1]):
            best = (signature, score)

    if best is None:
        return DetectedFramework("unknown", "docker", 8080, 10)

    signature, score = best
    max_possible = len(signature.file_matchers) * 2 + len(signature.dependency_matchers) * 3
    confidence = min(99, round((score / max(1, max_possible)) * 100))
    return DetectedFramework(
        framework=signature.framework,
        runtime=signature.runtime,
        default_port=signature.default_port,
        confidence=confidence,
        build_command=signature.build_command,
        start_command=signature.start_command,
    )
