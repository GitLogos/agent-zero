"""Persistent build capabilities, independent of mounted user/plugin settings."""

from functools import lru_cache
import json
from pathlib import Path


MANIFEST = Path("/etc/a0-image-features.json")
FEATURES = ("desktop", "office", "whisper", "kokoro", "chromium", "searxng")
PLUGIN_FEATURES = {"_desktop": "desktop", "_office": "office"}


@lru_cache(maxsize=1)
def get_features() -> dict[str, bool]:
    if not MANIFEST.exists():
        return dict.fromkeys(FEATURES, True)
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != set(FEATURES):
        raise ValueError("Image feature manifest must specify all six build capabilities.")
    if any(type(value) is not bool for value in data.values()):
        raise ValueError("Image feature manifest values must be booleans.")
    return data


def available(feature: str) -> bool:
    if feature not in FEATURES:
        raise ValueError(f"Unknown image feature: {feature}")
    return get_features()[feature]


def unavailable_reason(plugin_name: str) -> str:
    feature = PLUGIN_FEATURES.get(plugin_name)
    if feature is None or available(feature):
        return ""
    return missing_reason(feature)


def missing_reason(feature: str) -> str:
    if available(feature):
        return ""
    return (
        f"{feature.title()} is not included in this image. "
        f"Rebuild with A0_INCLUDE_{feature.upper()}=true to enable it."
    )


def require(feature: str) -> None:
    reason = missing_reason(feature)
    if reason:
        raise RuntimeError(reason)
