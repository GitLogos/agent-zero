import importlib.metadata

from helpers.api import ApiHandler, Request, Response
from helpers import external_speech, image_features
from plugins._whisper_stt.helpers import migration, runtime


class Status(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        migration.ensure_config_seeded()

        package_version = ""
        package_error = ""
        try:
            package_version = importlib.metadata.version("openai-whisper")
        except importlib.metadata.PackageNotFoundError as e:
            package_error = str(e)

        config = runtime.get_config()
        error = runtime.configuration_error(config)
        return {
            "plugin": "_whisper_stt",
            "enabled": runtime.is_globally_enabled(),
            "config": external_speech.public_config(config),
            "configuration_error": error,
            "local_available": image_features.available("whisper"),
            "model": {
                "ready": False if error else await runtime.is_downloaded(),
                "loading": False if error else await runtime.is_downloading(),
                "loaded_model": "" if error else runtime.get_loaded_model_name(),
            },
            "package": {
                "version": package_version,
                "error": package_error,
            },
        }
