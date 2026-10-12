from pathlib import Path
from types import SimpleNamespace

from plugins._office.helpers import libreoffice


def test_headless_conversion_does_not_force_x11_backend(monkeypatch):
    monkeypatch.delenv("SAL_USE_VCLPLUGIN", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("HOME", "/home/runtime")
    calls = []

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(libreoffice.subprocess, "run", execute)

    libreoffice._run_soffice("soffice", ["--headless", "--safe-mode"], timeout=45)

    args, kwargs = calls[0]
    assert args == ["soffice", "--headless", "--safe-mode"]
    assert "SAL_USE_VCLPLUGIN" not in kwargs["env"]
    assert "DISPLAY" not in kwargs["env"]
    assert kwargs["env"]["HOME"] == "/home/runtime"
    assert kwargs["timeout"] == 45
    assert kwargs["capture_output"] is True


def test_headless_conversion_preserves_explicit_backend(monkeypatch):
    monkeypatch.setenv("SAL_USE_VCLPLUGIN", "svp")
    environments = []

    def execute(args, **kwargs):
        environments.append(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(libreoffice.subprocess, "run", execute)

    libreoffice._run_soffice("soffice", ["--headless"], timeout=45)

    assert environments[0]["SAL_USE_VCLPLUGIN"] == "svp"


def test_conversion_exit_success_without_output_preserves_native_error(tmp_path, monkeypatch):
    source = tmp_path / "input.odt"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(libreoffice, "find_soffice", lambda: "soffice")
    monkeypatch.setattr(libreoffice.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="", stderr="X11 error: Can't open display",
    ))

    result = libreoffice.convert_document(source, "docx")

    assert result["ok"] is False
    assert "without producing an output file" in result["error"]
    assert "X11 error: Can't open display" in result["error"]


def test_conversion_reports_exact_native_output_path(tmp_path, monkeypatch):
    source = tmp_path / "input.odt"
    source.write_bytes(b"fixture")
    monkeypatch.delenv("SAL_USE_VCLPLUGIN", raising=False)
    monkeypatch.setattr(libreoffice, "find_soffice", lambda: "soffice")

    def execute(args, **kwargs):
        assert "SAL_USE_VCLPLUGIN" not in kwargs["env"]
        output = Path(args[args.index("--outdir") + 1]) / "input.docx"
        output.write_bytes(b"converted")
        return SimpleNamespace(returncode=0, stdout="converted", stderr="")

    monkeypatch.setattr(libreoffice.subprocess, "run", execute)

    assert libreoffice.convert_document(source, "docx") == {
        "ok": True, "path": str(tmp_path / "input.docx"),
    }
