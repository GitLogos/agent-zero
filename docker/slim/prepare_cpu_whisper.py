"""Build an auditable CPU-default Whisper wheel; leave upstream code unchanged."""

import argparse
import base64
import csv
from email import policy
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


UPSTREAM_VERSION = "20250625"
CPU_VERSION = UPSTREAM_VERSION + "+a0cpu.1"
SOURCE_URL = (
    "https://files.pythonhosted.org/packages/35/8e/"
    "d36f8880bcf18ec026a55807d02fe4c7357da9f25aebd92f85178000c0dc/"
    "openai_whisper-20250625.tar.gz"
)
SOURCE_SHA256 = "37a91a3921809d9f44748ffc73c0a55c9f366c85a3ef5c2ae0cc09540432eb96"


def repackage(wheel: Path, output_dir: Path) -> Path:
    from packaging.requirements import Requirement

    with zipfile.ZipFile(wheel) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    metadata_paths = [name for name in entries if name.endswith(".dist-info/METADATA")]
    if len(metadata_paths) != 1:
        raise ValueError("Expected exactly one upstream wheel metadata file.")
    metadata_path = metadata_paths[0]
    original_info = metadata_path.removesuffix("/METADATA")
    metadata = BytesParser(policy=policy.compat32).parsebytes(entries[metadata_path])
    if metadata["Name"] != "openai-whisper" or metadata["Version"] != UPSTREAM_VERSION:
        raise ValueError("Unexpected Whisper distribution or upstream version.")
    if any(name.endswith(("/RECORD.jws", "/RECORD.p7s")) for name in entries):
        raise ValueError("Cannot retain an upstream signature after changing metadata.")

    requirements = metadata.get_all("Requires-Dist", [])
    triton = [raw for raw in requirements if Requirement(raw).name.lower() == "triton"]
    if len(triton) != 1 or not Requirement(triton[0]).marker:
        raise ValueError("Expected one platform-conditional upstream Triton requirement.")
    metadata.replace_header("Version", CPU_VERSION)
    del metadata["Requires-Dist"]
    for raw in requirements:
        requirement = Requirement(raw)
        if requirement.name.lower() == "triton":
            metadata["Requires-Dist"] = (
                f"triton{requirement.specifier}; ({requirement.marker}) and extra == 'cuda'"
            )
        else:
            metadata["Requires-Dist"] = raw
    if "cuda" in metadata.get_all("Provides-Extra", []):
        raise ValueError("Upstream already defines a CUDA extra; review the packaging recipe.")
    metadata["Provides-Extra"] = "cuda"

    new_info = f"openai_whisper-{CPU_VERSION}.dist-info"
    rewritten = {
        (new_info + name[len(original_info):] if name.startswith(original_info + "/") else name): content
        for name, content in entries.items()
        if name != original_info + "/RECORD"
    }
    rewritten[new_info + "/METADATA"] = metadata.as_bytes(policy=policy.compat32.clone(max_line_length=0))
    payload = {name: content for name, content in entries.items() if not name.startswith(original_info + "/")}
    if payload != {name: content for name, content in rewritten.items() if not name.startswith(new_info + "/")}:
        raise ValueError("CPU packaging changed upstream code or assets.")
    provenance = {
        "upstream_version": UPSTREAM_VERSION,
        "cpu_version": CPU_VERSION,
        "source_url": SOURCE_URL,
        "source_sha256": SOURCE_SHA256,
        "recipe": "docker/slim/prepare_cpu_whisper.py",
        "recipe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "change": "Metadata only: Triton is optional under the cuda extra. Upstream code and assets are unchanged.",
        "upstream_wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "payload_sha256": {
            name: hashlib.sha256(content).hexdigest() for name, content in sorted(payload.items())
        },
    }
    rewritten[new_info + "/a0-cpu-provenance.json"] = json.dumps(provenance, indent=2).encode()
    records = io.StringIO(newline="")
    writer = csv.writer(records, lineterminator="\n")
    for name, content in sorted(rewritten.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + digest, len(content)))
    record_path = new_info + "/RECORD"
    writer.writerow((record_path, "", ""))
    rewritten[record_path] = records.getvalue().encode()

    parts = wheel.name.split("-")
    if len(parts) != 5 or parts[2:] != ["py3", "none", "any.whl"]:
        raise ValueError("Expected upstream's pure-Python wheel tags.")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"openai_whisper-{CPU_VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(rewritten.items()):
            entry = zipfile.ZipInfo(name, (2025, 6, 25, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, content)
    return output


def build(output_dir: Path, requirements: Path) -> Path:
    with tempfile.TemporaryDirectory(prefix="a0-whisper-build-") as directory:
        root = Path(directory)
        source = root / "openai_whisper.tar.gz"
        with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
            raise ValueError("Whisper source checksum mismatch.")
        source.write_bytes(data)
        builder = root / "builder"
        subprocess.run([sys.executable, "-m", "venv", str(builder)], check=True)
        python = builder / "bin" / "python"
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), "-r", str(requirements)],
            check=True,
        )
        wheels = root / "wheels"
        subprocess.run([
            str(python), "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
            "--wheel-dir", str(wheels), str(source),
        ], check=True)
        candidates = list(wheels.glob("openai_whisper-*.whl"))
        if len(candidates) != 1:
            raise ValueError("Expected exactly one built Whisper wheel.")
        subprocess.run([
            str(python), __file__, "--repackage", str(candidates[0]), "--output", str(output_dir),
        ], check=True)
        return output_dir / f"openai_whisper-{CPU_VERSION}-py3-none-any.whl"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requirements", type=Path)
    parser.add_argument("--repackage", type=Path)
    options = parser.parse_args()
    if options.repackage:
        print(repackage(options.repackage, options.output))
    elif options.requirements:
        print(build(options.output, options.requirements))
    else:
        parser.error("--requirements is required when building from source")
