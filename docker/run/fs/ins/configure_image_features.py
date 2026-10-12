"""Record build capabilities and configure the inherited search service."""

import argparse
import configparser
import json
import os
from pathlib import Path
import shutil


FEATURES = ("desktop", "office", "whisper", "kokoro", "chromium", "searxng")
MANIFEST = Path("/etc/a0-image-features.json")
SUPERVISOR_CONFIGS = (
    Path("/etc/supervisor/conf.d/supervisord.conf"),
    Path("/per/etc/supervisor/conf.d/supervisord.conf"),
)


def from_environment() -> dict[str, bool]:
    features = {}
    for name in FEATURES:
        value = os.environ.get("A0_INCLUDE_" + name.upper(), "true")
        if value not in ("true", "false"):
            raise ValueError(f"A0_INCLUDE_{name.upper()} must be true or false.")
        features[name] = value == "true"
    return features


def configure_supervisor(path: Path, features: dict[str, bool]) -> None:
    if features["searxng"] or not path.exists():
        return
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(path.read_text())
    if config.remove_section("program:run_searxng"):
        with path.open("w") as stream:
            config.write(stream)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    options = parser.parse_args()
    if options.write:
        features = from_environment()
        MANIFEST.write_text(json.dumps(features) + "\n")
        MANIFEST.chmod(0o444)
    else:
        features = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else dict.fromkeys(FEATURES, True)
        if set(features) != set(FEATURES) or any(type(value) is not bool for value in features.values()):
            raise ValueError("Invalid image feature manifest.")
    for path in SUPERVISOR_CONFIGS:
        configure_supervisor(path, features)
    if options.finalize and not features["searxng"]:
        for path in (Path("/usr/local/searxng"), Path("/per/usr/local/searxng")):
            if path.exists():
                shutil.rmtree(path)


if __name__ == "__main__":
    main()
