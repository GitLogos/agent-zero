from __future__ import annotations

import asyncio
from pathlib import Path

from plugins._kokoro_tts.helpers import runtime


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_config_keeps_legacy_voice_and_normalizes_weighted_blends() -> None:
    legacy = runtime.normalize_config(
        {"voice": "custom/voice.pt", "speed": 2.2}
    )
    assert legacy == {
        **runtime.DEFAULT_CONFIG,
        "voice": "custom/voice.pt",
        "voice_weights": {},
        "speed": 2.2,
    }

    weighted = runtime.normalize_config(
        {
            "voice": "ignored_when_weights_are_present",
            "voice_weights": {
                "af_heart": "3",
                "am_puck": 1,
                "../bad.pt": 5,
                "am_onyx": float("nan"),
                "am_echo": 0,
            },
            "speed": float("inf"),
        }
    )
    assert weighted == {
        **runtime.DEFAULT_CONFIG,
        "voice": "af_heart,am_puck",
        "voice_weights": {"af_heart": 3.0, "am_puck": 1.0},
        "speed": 1.1,
    }


def test_weighted_blend_reuses_the_existing_pipeline() -> None:
    class FakePipeline:
        packs = {"af_heart": 2.0, "am_puck": 10.0}

        def __init__(self) -> None:
            self.loaded: list[str] = []

        def load_single_voice(self, voice: str) -> float:
            self.loaded.append(voice)
            return self.packs[voice]

    pipeline = FakePipeline()
    blend = runtime._resolve_voice(
        pipeline,
        "legacy",
        {"af_heart": 3.0, "am_puck": 1.0},
    )

    assert blend == 4.0
    assert pipeline.loaded == ["af_heart", "am_puck"]
    assert runtime._resolve_voice(pipeline, "am_puck,am_onyx", {}) == (
        "am_puck,am_onyx"
    )


def test_remote_invalid_speed_is_not_silently_replaced_by_local_default():
    from helpers import external_speech

    for speed in (-1, None, float("inf"), "invalid"):
        config = runtime.normalize_config({
            "backend": "openai", "external_base_url": "http://speech.example/v1",
            "external_model": "fixture", "external_voice": "fixture", "speed": speed,
        })
        assert "speed" in external_speech.configuration_error(config, tts=True)


def test_synthesis_forwards_normalized_weights(monkeypatch) -> None:
    captured: dict = {}

    async def fake_synthesize(sentences, **kwargs):
        captured.update({"sentences": sentences, **kwargs})
        return "audio"

    monkeypatch.setattr(runtime, "_synthesize_sentences", fake_synthesize)

    result = asyncio.run(
        runtime.synthesize_sentences(
            ["Hello"],
            {
                "voice": "legacy",
                "voice_weights": {"af_heart": 2, "am_puck": 1},
                "speed": 1.4,
            },
        )
    )

    assert result == "audio"
    assert captured == {
        "sentences": ["Hello"],
        "voice": "af_heart,am_puck",
        "voice_weights": {"af_heart": 2.0, "am_puck": 1.0},
        "speed": 1.4,
    }


def test_settings_expose_catalog_weights_and_speed_without_disk_blends() -> None:
    config_ui = (
        PROJECT_ROOT / "plugins/_kokoro_tts/webui/config.html"
    ).read_text(encoding="utf-8")
    store = (
        PROJECT_ROOT / "plugins/_kokoro_tts/webui/kokoro-tts-store.js"
    ).read_text(encoding="utf-8")

    assert "af_heart" in config_ui
    assert "am_puck" in config_ui
    assert "am_onyx" in config_ui
    assert "config.voice_weights" in config_ui
    assert "Use equal weights" in config_ui
    assert 'type="range"' in config_ui
    assert 'min="0.5"' in config_ui
    assert 'max="3"' in config_ui
    assert "create_blend" not in config_ui
    assert "lang_code" not in config_ui
    assert "voiceSummary" in store
