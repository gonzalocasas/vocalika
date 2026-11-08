from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from vocalika import __version__, about
from vocalika.api.app import create_app


def names() -> set[str]:
    return {package["name"].lower() for package in about.python_packages()}


def test_the_list_holds_what_vocalika_runs_on_and_not_the_developer_tools() -> None:
    listed = names()
    for needed in ("python", "numpy", "torch", "fastapi", "uroman", "av"):
        assert needed in listed, needed
    # Installed here for development, never shipped.
    for tool in ("pytest", "ruff", "mypy"):
        assert tool not in listed, tool


def test_every_package_names_a_license() -> None:
    for package in about.python_packages():
        assert package["license"], package["name"]


def test_license_texts_come_from_the_installed_package() -> None:
    [*texts] = about.license_texts("numpy")
    assert texts
    assert any("NumPy Developers" in text["text"] for text in texts)
    assert "Python Software Foundation" in about.license_texts("Python")[0]["text"]


def test_only_vocalika_dependencies_can_be_read() -> None:
    with pytest.raises(KeyError):
        about.license_texts("pytest")
    with pytest.raises(KeyError):
        about.license_texts("../../etc/passwd")


def test_the_launcher_list_is_read_when_the_launcher_provides_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notices = tmp_path / "launcher-notices.json"
    notices.write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "name": "tauri",
                        "version": "2.0.0",
                        "license": "Apache-2.0 OR MIT",
                        "url": "https://tauri.app",
                        "licenses": [{"file": "LICENSE_MIT", "text": "t1"}],
                    }
                ],
                "texts": {"t1": "MIT License text"},
            }
        )
    )
    about._launcher_file.cache_clear()
    monkeypatch.setenv("VOCALIKA_LAUNCHER_NOTICES", str(notices))
    try:
        assert about.launcher_packages() == [
            {
                "name": "tauri",
                "version": "2.0.0",
                "license": "Apache-2.0 OR MIT",
                "url": "https://tauri.app",
            }
        ]
        assert about.launcher_license_texts("tauri") == [
            {"file": "LICENSE_MIT", "text": "MIT License text"}
        ]
    finally:
        about._launcher_file.cache_clear()


@pytest.mark.anyio
async def test_the_about_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOCALIKA_DESKTOP", raising=False)
    about._launcher_file.cache_clear()
    app = create_app(None, library_directory=tmp_path / "analyses")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        summary = (await client.get("/api/about")).json()
        assert summary["version"] == __version__
        assert summary["desktop"] is False
        assert summary["launcher_packages"] is None

        texts = await client.get("/api/about/licenses/python/numpy")
        assert texts.status_code == 200 and texts.json()["texts"]
        assert (await client.get("/api/about/licenses/python/pytest")).status_code == 404
        assert (await client.get("/api/about/licenses/elsewhere/numpy")).status_code == 404

        # Only the desktop app opens links, and only web links.
        link = {"url": "https://vocalika.app"}
        assert (await client.post("/api/about/open", json=link)).status_code == 404
        monkeypatch.setenv("VOCALIKA_DESKTOP", "1")
        opened: list[str] = []
        monkeypatch.setattr("webbrowser.open", opened.append)
        for refused in ("file:///etc/passwd", "javascript:alert(1)", "http://example.com"):
            response = await client.post("/api/about/open", json={"url": refused})
            assert response.status_code == 422, refused
        assert (await client.post("/api/about/open", json=link)).status_code == 200
        assert opened == ["https://vocalika.app"]
