import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("image_inventory", ROOT / "docker" / "slim" / "inventory.py")
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def test_desktop_gate_registers_sessions_in_live_server_not_check_process(monkeypatch, tmp_path, smoke_module):
    profile = tmp_path / "profiles" / "fixture-session" / "Desktop"
    profile.mkdir(parents=True)
    (profile / "Terminal.desktop").touch()
    monkeypatch.setitem(sys.modules, "plugins._desktop.helpers.desktop_session", SimpleNamespace(
        PROFILE_DIR=tmp_path / "profiles", SYSTEM_SESSION_ID="fixture-session",
    ))
    actions = []

    class Client:
        def open(self, request, timeout):
            if isinstance(request, str):
                assert request == "http://127.0.0.1/desktop/fixture/"
                payload = b"<html>fixture viewer</html>"
            elif request.full_url.endswith("/api/csrf_token"):
                payload = json.dumps({"token": "fixture-token"}).encode()
            else:
                assert request.full_url.endswith("/api/plugins/_desktop/desktop_session")
                assert request.get_header("X-csrf-token") == "fixture-token"
                action = json.loads(request.data)["action"]
                actions.append(action)
                result = {
                    "desktop": {"ok": True, "desktop": {"available": True, "url": "/desktop/fixture/"}},
                    "status": {"healthy": True},
                    "shutdown": {"ok": True},
                }[action]
                payload = json.dumps(result).encode()
            response = io.BytesIO(payload)
            response.status = 200
            return response

    monkeypatch.setattr(smoke_module.urllib.request, "build_opener", lambda *args: Client())
    smoke_module.desktop()
    assert actions == ["desktop", "status", "shutdown"]


def fake_file(inode, size, links=1):
    return SimpleNamespace(
        is_file=lambda: True,
        is_symlink=lambda: False,
        stat=lambda: SimpleNamespace(
            st_dev=1, st_ino=inode, st_size=size,
            st_blocks=(size + 511) // 512, st_nlink=links,
        ),
    )


def test_cache_inventory_does_not_claim_shared_hardlinks_as_reclaimable(monkeypatch):
    files = {
        "a": fake_file(1, 1000, links=3),
        "b": fake_file(1, 1000, links=3),
        "exclusive": fake_file(2, 500),
    }
    monkeypatch.setattr(inventory.os, "walk", lambda path: [("/cache", [], list(files))])
    monkeypatch.setattr(inventory, "Path", lambda directory, name: files[name])

    result = inventory.cache_inventory("/cache")

    assert result["exclusive_logical_bytes"] == 500
    assert result["exclusive_allocated_bytes"] == 512
    assert result["externally_hardlinked_logical_bytes"] == 1000
    assert result["externally_hardlinked_allocated_bytes"] == 1024


def test_distribution_inventory_deduplicates_inodes(monkeypatch):
    files = {"a": fake_file(1, 1000), "b": fake_file(1, 1000), "c": fake_file(2, 500)}
    distribution = SimpleNamespace(
        files=list(files), locate_file=files.__getitem__,
        metadata={"Name": "example"}, version="1.2.3", requires=["shared>=1"],
    )
    monkeypatch.setattr(
        inventory.importlib.metadata, "distributions", lambda path: [distribution]
    )

    result = inventory.distributions("/packages")

    assert result == [{
        "name": "example", "version": "1.2.3", "logical_bytes": 1500,
        "allocated_bytes": 1536, "requires": ["shared>=1"],
    }]


def test_elf_inventory_distinguishes_debug_from_static_and_dynamic_symbols(tmp_path, monkeypatch):
    binary = tmp_path / "library.so"
    with binary.open("wb") as handle:
        handle.write(b"\x7fELF")
        handle.truncate(20_000_001)
    monkeypatch.setattr(inventory.shutil, "which", lambda name: "/usr/bin/readelf")
    monkeypatch.setattr(inventory, "command", lambda *args: """
  [ 1] .debug_info PROGBITS 0000000000000000 000040 000100 00 0 0 1
  [ 2] .symtab SYMTAB 0000000000000000 000140 000200 18 4 1 8
  [ 3] .strtab STRTAB 0000000000000000 000340 000080 00 0 0 1
  [ 4] .dynsym DYNSYM 0000000000000000 0003c0 000400 18 5 1 8
""")

    result = inventory.elf_inventory([str(tmp_path)])

    assert len(result) == 1
    assert result[0]["debug_section_bytes"] == 256
    assert result[0]["static_symbol_section_bytes"] == 640
    assert result[0]["logical_bytes"] == 20_000_001


def test_smoke_directory_does_not_shadow_stdlib_profile():
    directory = ROOT / "docker" / "slim"
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import cProfile, runpy; assert callable(cProfile.run); "
        "runpy.run_path(sys.argv[2], run_name='image_checks')"
    )

    subprocess.run(
        [sys.executable, "-c", script, str(directory), str(directory / "smoke.py")],
        check=True, timeout=30,
    )


@pytest.fixture
def smoke_module():
    spec = importlib.util.spec_from_file_location("image_smoke", ROOT / "docker" / "slim" / "smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    return smoke


def test_baseline_checks_do_not_skip_independent_features_after_office_failure(monkeypatch, smoke_module):
    smoke = smoke_module
    monkeypatch.setitem(sys.modules, "helpers", SimpleNamespace(
        runtime=SimpleNamespace(initialize=lambda: None),
    ))
    monkeypatch.setattr(sys, "argv", ["smoke.py", "--baseline"])
    reached = []
    results = {}

    def check(name):
        def execute():
            reached.append(name)
            if name == "office_exports":
                raise RuntimeError("Office failed")
        return execute

    names = ["runtimes", "offline_memory", "office_exports", "document_parsing", "ocr", "ffmpeg"]
    for name in names:
        monkeypatch.setattr(smoke, name, check(name))
    monkeypatch.setattr(smoke, "Path", lambda _: SimpleNamespace(
        write_text=lambda content: results.update(json.loads(content)),
    ))

    with pytest.raises(AssertionError):
        smoke.main()

    assert reached == names
    assert results["office_exports"] == {"passed": False, "error": "Office failed"}
    assert all(results[name]["passed"] for name in names if name != "office_exports")


def test_office_diagnostics_isolate_safe_mode_vcl_and_profile(tmp_path, monkeypatch, smoke_module, capsys):
    source = tmp_path / "source.odt"
    source.write_bytes(b"fixture")
    calls = []

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        output = Path(args[args.index("--outdir") + 1]) / "source.docx"
        output.write_bytes(b"converted")
        return SimpleNamespace(returncode=0, stdout="converted", stderr="")

    monkeypatch.setattr(smoke_module.subprocess, "run", execute)

    smoke_module.diagnose_office_conversion("soffice", source, "docx", tmp_path)

    assert len(calls) == 8
    assert {
        ("--safe-mode" in args, kwargs["env"].get("SAL_USE_VCLPLUGIN"),
         any(arg.startswith("-env:UserInstallation=") for arg in args))
        for args, kwargs in calls
    } == {(safe, vcl, isolated) for safe in (True, False) for vcl in ("gen", None) for isolated in (False, True)}
    assert capsys.readouterr().out.count('"output_exists": true') == 8
