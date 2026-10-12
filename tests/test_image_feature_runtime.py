import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers import image_features, plugins, searxng
from plugins._browser import hooks as browser_hooks
from plugins._browser.helpers import playwright
from plugins._desktop import hooks as desktop_hooks
from plugins._desktop.helpers import desktop_session
from plugins._office import hooks as office_hooks
from plugins._whisper_stt.helpers import runtime as stt
from plugins._kokoro_tts.helpers import runtime as tts


@pytest.fixture(autouse=True)
def controlled_features(monkeypatch):
    features = dict.fromkeys(image_features.FEATURES, True)
    monkeypatch.setattr(image_features, "get_features", lambda: features)
    return features


def test_user_scoped_rules_cannot_enable_excluded_plugins(monkeypatch, controlled_features):
    controlled_features.update(desktop=False, office=False)
    monkeypatch.setattr(plugins.cache, "get", lambda *args: None)
    monkeypatch.setattr(plugins.cache, "add", lambda *args: None)
    monkeypatch.setattr(plugins, "get_plugins_list", lambda: ["_desktop", "_office", "_browser"])
    monkeypatch.setattr(plugins, "get_plugin_meta", lambda name: SimpleNamespace(always_enabled=True))
    assert plugins.get_enabled_plugins(None) == ["_browser"]
    for name in ("_desktop", "_office"):
        assert plugins.get_toggle_state(name) == "disabled"
        with pytest.raises(ValueError, match="not included"):
            plugins.toggle_plugin.__wrapped__(name, True, project_name="example")


def test_excluded_prepare_hooks_cannot_install_any_packages(monkeypatch, controlled_features):
    controlled_features.update(desktop=False, office=False, chromium=False)
    def unexpected(*args, **kwargs):
        raise AssertionError("Excluded feature attempted runtime repair/download")
    monkeypatch.setattr(desktop_hooks, "_ensure_runtime_dependencies", unexpected)
    monkeypatch.setattr(office_hooks, "_ensure_runtime_dependencies", unexpected)
    monkeypatch.setattr(browser_hooks, "_ensure_patchright_dependency", unexpected)
    assert desktop_hooks.cleanup_stale_runtime_state(force=True)["skipped"]
    assert office_hooks.cleanup_stale_runtime_state(force=True)["skipped"]
    assert browser_hooks.prepare_playwright_cache()["included"] is False
    with pytest.raises(RuntimeError, match="not included"):
        playwright.ensure_playwright_binary()
    with pytest.raises(RuntimeError, match="not included"):
        desktop_session.DesktopSessionManager()._ensure_system_desktop_locked()


def test_desktop_repair_does_not_reinstall_excluded_office(monkeypatch, controlled_features):
    controlled_features["office"] = False
    seen = []
    monkeypatch.setattr(desktop_hooks.os, "geteuid", lambda: 0)
    monkeypatch.setattr(desktop_hooks.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(desktop_hooks, "_package_installed", lambda name: seen.append(name) or True)
    desktop_hooks._ensure_runtime_dependencies([], [])
    assert seen and not set(seen).intersection(office_hooks.LIBREOFFICE_RUNTIME_PACKAGES)


def test_office_free_desktop_uses_editor_text_association(tmp_path, controlled_features):
    controlled_features["office"] = False
    path = tmp_path / "mimeapps.list"
    desktop_session._write_mimeapps_defaults(path, "browser.desktop", "editor.desktop")
    assert "text/plain=editor.desktop" in path.read_text()
    assert "libreoffice-writer.desktop" not in path.read_text()


def test_headless_office_cannot_advertise_a_live_desktop(controlled_features):
    from plugins._office.api.office_session import OfficeSession

    controlled_features["desktop"] = False
    status = desktop_session.collect_desktop_status()
    assert status["state"] == "excluded" and not status["installing"]
    assert status["office_available"]
    handler = object.__new__(OfficeSession)
    result = asyncio.run(handler._open_document(
        {"extension": "odt", "path": "/tmp/fixture.odt", "file_id": "fixture"}, {}, None,
    ))
    assert not result["ok"] and "not included" in result["error"]


@pytest.mark.parametrize("feature,runtime", [("whisper", stt), ("kokoro", tts)])
def test_excluded_local_speech_has_explicit_errors_without_affecting_external(feature, runtime, controlled_features):
    controlled_features[feature] = False
    local = runtime.normalize_config({"backend": "local"})
    assert "not included" in runtime.configuration_error(local)
    external = runtime.normalize_config({
        "backend": "openai", "external_base_url": "http://fixture.example/v1",
        "external_model": "fixture", "external_voice": "fixture",
    })
    assert runtime.configuration_error(external) == ""
    operation = runtime._preload("base") if feature == "whisper" else runtime._preload()
    with pytest.raises(RuntimeError, match="not included"):
        asyncio.run(operation)


def test_unconfigured_search_is_explicit_and_external_endpoint_is_used(monkeypatch, controlled_features):
    controlled_features["searxng"] = False
    monkeypatch.delenv("A0_SEARXNG_URL", raising=False)
    with pytest.raises(RuntimeError, match="A0_SEARXNG_URL"):
        searxng.search_url()
    monkeypatch.setenv("A0_SEARXNG_URL", "http://fixture.example/search")
    assert searxng.search_url() == "http://fixture.example/search"
    monkeypatch.setenv("A0_SEARXNG_URL", "https://secret:password@fixture.example/search")
    with pytest.raises(ValueError, match="without embedded credentials"):
        searxng.search_url()
