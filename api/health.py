from helpers.api import ApiHandler, Request, Response
from helpers import errors, git, image_features

class HealthCheck(ApiHandler):

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        gitinfo = None
        error = None
        try:
            gitinfo = git.get_git_info()
        except Exception as e:
            error = errors.error_text(e)

        return {"gitinfo": gitinfo, "error": error, "image_features": image_features.get_features()}
