"""Public license and corresponding-source contract tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from api import index

ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40


def test_health_exposes_license_and_stable_source_without_revision(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SOURCE_COMMIT_SHA", raising=False)
    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)

    payload = TestClient(index.app).get("/health").json()

    assert payload["license"] == {
        "spdx": "AGPL-3.0-or-later",
        "url": f"{index.SOURCE_REPOSITORY_URL}/blob/master/LICENSE",
    }
    assert payload["source"] == {
        "repository": index.SOURCE_REPOSITORY_URL,
        "revision": None,
        "url": index.SOURCE_REPOSITORY_URL,
    }


def test_root_exposes_exact_deployed_revision(monkeypatch) -> None:
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", REVISION.upper())

    payload = TestClient(index.app).get("/").json()

    assert payload["source"]["revision"] == REVISION
    assert payload["source"]["url"] == (
        f"{index.SOURCE_REPOSITORY_URL}/tree/{REVISION}"
    )
    assert payload["license"]["url"] == (
        f"{index.SOURCE_REPOSITORY_URL}/blob/{REVISION}/LICENSE"
    )


def test_explicit_source_revision_precedes_vercel_revision(monkeypatch) -> None:
    explicit_revision = "b" * 40
    monkeypatch.setenv("SOURCE_COMMIT_SHA", explicit_revision)
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", REVISION)

    assert index._source_revision() == explicit_revision


def test_untrusted_revision_values_do_not_enter_source_urls(monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_COMMIT_SHA", "../unexpected")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "not-a-commit")

    payload = TestClient(index.app).get("/health").json()

    assert payload["source"]["revision"] is None
    assert payload["source"]["url"] == index.SOURCE_REPOSITORY_URL


def test_openapi_and_package_metadata_declare_agpl_source_offer() -> None:
    client = TestClient(index.app)
    schema = client.get("/openapi.json").json()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert schema["info"]["license"]["identifier"] == "AGPL-3.0-or-later"
    assert index.SOURCE_REPOSITORY_URL in schema["info"]["description"]
    assert project["license"] == "AGPL-3.0-or-later"
    assert project["urls"]["Source"] == index.SOURCE_REPOSITORY_URL
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "THIRD_PARTY_NOTICES.md").is_file()
