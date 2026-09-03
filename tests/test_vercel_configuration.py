"""Deployment contract tests for Vercel's FastAPI framework routing."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_fastapi_entrypoint_is_explicit() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["tool"]["vercel"]["entrypoint"] == "api.index:app"


def test_pyproject_is_a_complete_runtime_dependency_source() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = {
        line
        for raw_line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    }

    assert config["project"]["name"] == "dashaflow-sidecar"
    assert set(config["project"]["dependencies"]) == requirements


def test_vercel_config_does_not_rewrite_root_into_the_asgi_app() -> None:
    path = ROOT / "vercel.json"
    if not path.exists():
        return

    config = json.loads(path.read_text(encoding="utf-8"))
    rewrites = config.get("rewrites", [])

    assert not any(
        rewrite.get("source") == "/(.*)"
        and rewrite.get("destination") in {"/api/index", "/api/index.py"}
        for rewrite in rewrites
    )
