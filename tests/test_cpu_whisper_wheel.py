import base64
import csv
from email.parser import BytesParser
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet


spec = importlib.util.spec_from_file_location(
    "cpu_whisper_wheel", Path(__file__).resolve().parents[1] / "docker/slim/prepare_cpu_whisper.py"
)
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)


def test_build_bootstrap_does_not_require_framework_site_packages():
    subprocess.run(
        [sys.executable, "-S", str(Path(recipe.__file__)), "--output", ".", "--help"],
        check=True, capture_output=True, text=True, timeout=30,
    )


def test_cpu_wheel_preserves_payload_and_moves_only_triton_to_cuda_extra(tmp_path):
    upstream = tmp_path / "openai_whisper-20250625-py3-none-any.whl"
    metadata = b"""Metadata-Version: 2.1
Name: openai-whisper
Version: 20250625
Requires-Dist: torch
Requires-Dist: numpy
Requires-Dist: triton>=2; (platform_machine == "x86_64" and sys_platform == "linux") or sys_platform == "linux2"

Upstream documentation retained.
"""
    with zipfile.ZipFile(upstream, "w") as archive:
        archive.writestr("whisper/transcribe.py", b"unchanged upstream code")
        archive.writestr("whisper/assets/model.bin", b"\x00\x01\xff")
        archive.writestr("openai_whisper-20250625.dist-info/METADATA", metadata)
        archive.writestr("openai_whisper-20250625.dist-info/WHEEL", b"Wheel-Version: 1.0\nTag: py3-none-any\n")
        archive.writestr("openai_whisper-20250625.dist-info/RECORD", b"")
    result = recipe.repackage(upstream, tmp_path / "output")
    assert recipe.CPU_VERSION in SpecifierSet("==20250625")
    with zipfile.ZipFile(result) as archive:
        prefix = "openai_whisper-" + recipe.CPU_VERSION + ".dist-info/"
        normalized = BytesParser().parsebytes(archive.read(prefix + "METADATA"))
        assert normalized["Version"] == recipe.CPU_VERSION
        assert archive.read("whisper/transcribe.py") == b"unchanged upstream code"
        assert archive.read("whisper/assets/model.bin") == b"\x00\x01\xff"
        requirements = [Requirement(raw) for raw in normalized.get_all("Requires-Dist")]
        assert {req.name for req in requirements if not req.marker} == {"torch", "numpy"}
        triton = next(req for req in requirements if req.name == "triton")
        assert not triton.marker.evaluate({"extra": "", "platform_machine": "x86_64", "sys_platform": "linux"})
        assert triton.marker.evaluate({"extra": "cuda", "platform_machine": "x86_64", "sys_platform": "linux"})
        assert not triton.marker.evaluate({"extra": "cuda", "platform_machine": "aarch64", "sys_platform": "linux"})
        provenance = json.loads(archive.read(prefix + "a0-cpu-provenance.json"))
        assert provenance["source_sha256"] == recipe.SOURCE_SHA256
        for name, digest in provenance["payload_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        records = csv.reader(io.StringIO(archive.read(prefix + "RECORD").decode()))
        for name, digest, size in records:
            if name.endswith("/RECORD"):
                assert not digest and not size
            else:
                content = archive.read(name)
                encoded = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
                assert digest == "sha256=" + encoded
                assert int(size) == len(content)
