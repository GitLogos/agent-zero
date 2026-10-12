"""Deterministic component-profile names for noncolliding experimental tags."""

import json
import os
from pathlib import Path


FEATURES = ("desktop", "office", "whisper", "kokoro", "chromium", "searxng")


def profile_suffix(features: dict[str, bool]) -> str:
    if set(features) != set(FEATURES) or any(type(value) is not bool for value in features.values()):
        raise ValueError("Profile must specify six boolean feature selections.")
    if all(features.values()):
        return ""
    return "-" + "-".join(name[0] + str(int(features[name])) for name in FEATURES)


if __name__ == "__main__":
    features = {}
    for feature in FEATURES:
        value = os.environ["INCLUDE_" + feature.upper()]
        if value not in ("true", "false"):
            raise ValueError("Workflow feature inputs must be true or false.")
        features[feature] = value == "true"
    base = f"{os.environ['IMAGE_REPOSITORY']}:experimental-{os.environ['GITHUB_SHA']}{profile_suffix(features)}"
    with Path(os.environ["GITHUB_ENV"]).open("a") as env:
        env.write(f"IMAGE={base}-{os.environ['ARCHITECTURE']}\n")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"image_base={base}\n")
    print(json.dumps({"image": base, "features": features}, indent=2))
