import importlib.metadata

from helpers.api import ApiHandler, Request, Response
from helpers import external_speech
from plugins._kokoro_tts.helpers import migration, runtime


class Status(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        migration.ensure_migrated()

        package_version = ""
        package_error = ""
        try:
            package_version = importlib.metadata.version("kokoro")
        except Exception as e:
            package_error = str(e)

        config = runtime.get_config()
        error = external_speech.configuration_error(config)
        if not error and config["backend"] == "openai" and not config["external_voice"]:
            error = "External TTS voice is required."
        return {
            "plugin": "_kokoro_tts",
            "enabled": runtime.is_globally_enabled(),
            "config": external_speech.public_config(config),
            "configuration_error": error,
            "model": {
                "ready": False if error else await runtime.is_downloaded(),
                "loading": False if error else await runtime.is_downloading(),
            },
            "package": {
                "version": package_version,
                "error": package_error,
            },
            "fallback": "Browser-native speechSynthesis remains the fallback when Kokoro is disabled.",
        }
