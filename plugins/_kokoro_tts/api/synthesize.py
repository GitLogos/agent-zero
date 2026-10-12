from helpers.api import ApiHandler, Request, Response
from helpers import image_features
from plugins._kokoro_tts.helpers import runtime


class Synthesize(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        if not runtime.is_globally_enabled():
            return Response(status=409, response="Kokoro TTS plugin is disabled")

        text = str(input.get("text") or "").strip()
        if not text:
            return Response(status=400, response="Missing text")

        config = runtime.get_config()
        allow_browser_fallback = config["backend"] == "local" and image_features.available("kokoro")
        try:
            audio = await runtime.synthesize_sentences([text], config)
            return {
                "success": True,
                "audio": audio,
                "mime_type": "audio/wav",
                "backend": config["backend"],
                "allow_browser_fallback": allow_browser_fallback,
            }
        except Exception as e:
            return {
                "success": False, "error": str(e), "backend": config["backend"],
                "allow_browser_fallback": allow_browser_fallback,
            }
