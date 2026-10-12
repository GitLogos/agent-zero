"""Read-only filesystem inventory, run inside the image without its entrypoint."""

import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def disk_usage(path):
    if not Path(path).exists():
        return None
    return int(command("du", "-sx", "-B1", str(path)).split()[0])


def distributions(site_packages):
    result = []
    for distribution in importlib.metadata.distributions(path=[site_packages]):
        seen = set()
        logical_bytes = 0
        allocated_bytes = 0
        for file in distribution.files or []:
            path = distribution.locate_file(file)
            if not path.is_file() or path.is_symlink():
                continue
            stat = path.stat()
            inode = (stat.st_dev, stat.st_ino)
            if inode in seen:
                continue
            seen.add(inode)
            logical_bytes += stat.st_size
            allocated_bytes += stat.st_blocks * 512
        result.append({
            "name": distribution.metadata["Name"],
            "version": distribution.version,
            "logical_bytes": logical_bytes,
            "allocated_bytes": allocated_bytes,
            "requires": distribution.requires or [],
        })
    return sorted(result, key=lambda item: item["logical_bytes"], reverse=True)


def cache_inventory(path):
    inodes = {}
    for directory, _dirs, names in os.walk(path):
        for name in names:
            file = Path(directory, name)
            if file.is_symlink() or not file.is_file():
                continue
            stat = file.stat()
            key = (stat.st_dev, stat.st_ino)
            entry = inodes.setdefault(key, {
                "logical_bytes": stat.st_size,
                "allocated_bytes": stat.st_blocks * 512,
                "total_links": stat.st_nlink,
                "cache_links": 0,
            })
            entry["cache_links"] += 1
    exclusive = [entry for entry in inodes.values() if entry["cache_links"] == entry["total_links"]]
    shared = [entry for entry in inodes.values() if entry["cache_links"] < entry["total_links"]]
    return {
        "exclusive_logical_bytes": sum(entry["logical_bytes"] for entry in exclusive),
        "exclusive_allocated_bytes": sum(entry["allocated_bytes"] for entry in exclusive),
        "externally_hardlinked_logical_bytes": sum(entry["logical_bytes"] for entry in shared),
        "externally_hardlinked_allocated_bytes": sum(entry["allocated_bytes"] for entry in shared),
    }


def elf_inventory(roots):
    if not shutil.which("readelf"):
        return {"unavailable": "readelf is not installed"}
    result = []
    seen = set()
    for root in roots:
        for directory, _dirs, names in os.walk(root):
            for name in names:
                file = Path(directory, name)
                if file.is_symlink() or not file.is_file():
                    continue
                stat = file.stat()
                key = (stat.st_dev, stat.st_ino)
                if key in seen or stat.st_size < 20_000_000:
                    continue
                seen.add(key)
                with file.open("rb") as handle:
                    if handle.read(4) != b"\x7fELF":
                        continue
                sections = command("readelf", "-SW", str(file))
                debug_bytes = 0
                symbol_bytes = 0
                for match in re.finditer(
                    r"\[\s*\d+\]\s+(\S+)\s+\S+\s+[0-9a-fA-F]+\s+[0-9a-fA-F]+\s+([0-9a-fA-F]+)",
                    sections,
                ):
                    section, size = match.groups()
                    if section.startswith((".debug", ".zdebug")):
                        debug_bytes += int(size, 16)
                    elif section in (".symtab", ".strtab"):
                        symbol_bytes += int(size, 16)
                result.append({
                    "path": str(file), "logical_bytes": stat.st_size,
                    "debug_section_bytes": debug_bytes,
                    "static_symbol_section_bytes": symbol_bytes,
                })
    return sorted(result, key=lambda item: item["debug_section_bytes"], reverse=True)


def main():
    roots = (
        "/opt", "/usr", "/root", "/git", "/a0", "/var",
        "/opt/venv", "/opt/venv-a0", "/opt/pyenv",
        "/root/.cache", "/root/.cache/uv", "/root/.cache/pip",
        "/root/.cache/huggingface", "/var/cache/apt", "/var/lib/apt/lists",
        "/usr/local/searxng/searxng-src", "/usr/local/searxng/searx-pyenv",
    )
    apt = []
    for line in command(
        "dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${Installed-Size}\n"
    ).splitlines():
        name, version, size = line.split("\t")
        apt.append({"name": name, "version": version, "installed_bytes": int(size or 0) * 1024})
    python = {}
    for root in ("/opt/venv", "/opt/venv-a0", "/usr/local/searxng/searx-pyenv"):
        for site in Path(root).glob("lib/python*/site-packages"):
            python[str(site)] = distributions(str(site))
    directories = []
    for root in ("/opt", "/usr/local", "/root", "/git", "/a0", "/var"):
        if not Path(root).exists():
            continue
        for line in command("du", "-x", "-B1", "-d", "3", root).splitlines():
            size, path = line.split("\t", 1)
            directories.append({"path": path, "allocated_bytes": int(size)})
    report = {
        "merged_filesystem_allocated_bytes": disk_usage("/"),
        "paths": {path: disk_usage(path) for path in roots},
        "largest_directories": sorted(
            directories, key=lambda item: item["allocated_bytes"], reverse=True
        )[:150],
        "apt_packages": sorted(apt, key=lambda item: item["installed_bytes"], reverse=True),
        "python_distributions": python,
        "uv_cache": cache_inventory("/root/.cache/uv"),
        "large_elf_files": elf_inventory(("/opt", "/usr")),
        "notes": [
            "Docker image inspect Size is the uncompressed sum of immutable layers.",
            "Merged du usage excludes overwritten/deleted lower-layer files.",
            "du deduplicates hardlinks within each invocation, not across separate path totals.",
            "Distribution sizes deduplicate inodes within a distribution, not across distributions.",
            "APT Installed-Size is package metadata, not the Docker layer size.",
        ],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
