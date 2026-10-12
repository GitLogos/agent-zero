"""Filter only approved optional speech roots; resolve all remaining deps normally."""

import argparse
import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


OPTIONAL_ROOTS = {"openai-whisper": "whisper", "kokoro": "kokoro"}


def select_requirements(source: str, features: dict[str, bool]) -> str:
    lines = []
    for line in source.splitlines(keepends=True):
        requirement = line.partition(" #")[0].strip()
        if not requirement or requirement.startswith("#"):
            lines.append(line)
            continue
        name = canonicalize_name(Requirement(requirement).name)
        feature = OPTIONAL_ROOTS.get(name)
        if feature is None or features[feature]:
            lines.append(line)
    return "".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", type=Path, default=Path("/etc/a0-image-features.json"))
    options = parser.parse_args()
    features = json.loads(options.manifest.read_text())
    options.output.write_text(select_requirements(options.source.read_text(), features))
