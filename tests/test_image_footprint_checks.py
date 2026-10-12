import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("image_inventory", ROOT / "docker" / "slim" / "inventory.py")
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


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
