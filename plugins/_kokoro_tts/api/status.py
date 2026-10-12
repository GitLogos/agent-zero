import importlib.metadata

from helpers.api import ApiHandler, Request, Response
from helpers import external_speech, image_features
from plugins._kokoro_tts.helpers import migration, runtime


class Status(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        migration.ensure_migrated()

        package_version = ""
        package_error = ""
        try:
            package_version = importlib.metadata.version("kokoro")
        except importlib.metadata.PackageNotFoundError as e:
            package_error = str(e)

        config = runtime.get_config()
        error = runtime.configuration_error(config)
        return {
            "plugin": "_kokoro_tts",
            "enabled": runtime.is_globally_enabled(),
            "config": external_speech.public_config(config),
            "configuration_error": error,
            "local_available": image_features.available("kokoro"),
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
