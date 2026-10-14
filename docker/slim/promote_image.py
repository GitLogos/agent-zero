"""Copy a checked multi-platform index to the mutable image-rebuild alias."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from image_profile import FEATURES, profile_suffix


REPOSITORY = "GitLogos/agent-zero"
PACKAGE = "gitlogos/agent-zero-slim"
IMAGE = "ghcr.io/" + PACKAGE
DIGEST = r"sha256:[0-9a-f]{64}"
ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/json",
))


class RegistryRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        redirected = super().redirect_request(request, response, code, message, headers, new_url)
        if redirected is not None and urlsplit(request.full_url).netloc != urlsplit(new_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


OPEN = build_opener(RegistryRedirect()).open


def api(path: str, *, raw: bool = False):
    result = subprocess.run(
        ["gh", "api", "--allow-escape-sequences", f"repos/{REPOSITORY}/{path}"],
        check=True, capture_output=True, text=True, timeout=120,
    )
    return (
        re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stdout)
        if raw else json.loads(result.stdout)
    )


def jobs(run_id: int) -> list[dict]:
    result = []
    page = 1
    while True:
        batch = api(f"actions/runs/{run_id}/jobs?per_page=100&page={page}")["jobs"]
        result.extend(batch)
        if len(batch) < 100:
            return result
        page += 1


def published_index(run: dict) -> dict:
    if (
        run["head_branch"] != "image-rebuild"
        or run["event"] != "workflow_dispatch"
        or run["path"] != ".github/workflows/image-footprint.yml"
        or not re.fullmatch(r"[0-9a-f]{40}", run["head_sha"])
    ):
        raise ValueError("Promotion requires a manually published image-rebuild run.")
    source_jobs = jobs(run["id"])
    required = {
        "candidate (amd64, ubuntu-24.04)",
        "candidate (arm64, ubuntu-24.04-arm)",
        "publish-index",
    }
    selected = [job for job in source_jobs if job["name"] in required]
    if {job["name"] for job in selected} != required or any(
        job["conclusion"] != "success" for job in selected
    ):
        raise ValueError("Both native checks and index publication must have succeeded.")
    return next(job for job in selected if job["name"] == "publish-index")


def index_provenance(log: str, source_sha: str) -> tuple[str, str]:
    prefix = r"^(?:\d{4}-\S+Z )?"
    names = re.findall(prefix + r"Name:\s+(" + re.escape(IMAGE) + r":experimental-[^\s@]+)\s*$", log, re.M)
    digests = re.findall(prefix + r"Digest:\s+(" + DIGEST + r")\s*$", log, re.M)
    if len(names) != 1 or len(digests) != 1:
        raise ValueError("Publication logs must identify one exact index tag and digest.")
    prefix = IMAGE + ":experimental-" + source_sha
    if not names[0].startswith(prefix) or not re.fullmatch(
        r"(?:-d[01]-o[01]-w[01]-k[01]-c[01]-s[01])?", names[0][len(prefix):]
    ):
        raise ValueError("Published index tag does not match the validated source.")
    return names[0], digests[0]


def newer_publication(source_run: dict) -> int | None:
    page = 1
    while True:
        runs = api(
            "actions/workflows/image-footprint.yml/runs"
            f"?branch=image-rebuild&event=workflow_dispatch&per_page=100&page={page}"
        )["workflow_runs"]
        for run in runs:
            if run["id"] > source_run["id"] and any(
                job["name"] == "publish-index" and job["conclusion"] == "success"
                for job in jobs(run["id"])
            ):
                return run["id"]
        if len(runs) < 100 or any(run["id"] <= source_run["id"] for run in runs):
            return None
        page += 1


class Registry:
    def __init__(self):
        credential = base64.b64encode(
            (os.environ["GITHUB_ACTOR"] + ":" + os.environ["GITHUB_TOKEN"]).encode()
        ).decode()
        query = urlencode({"service": "ghcr.io", "scope": f"repository:{PACKAGE}:pull,push"})
        request = Request("https://ghcr.io/token?" + query, headers={"Authorization": "Basic " + credential})
        with OPEN(request, timeout=60) as response:
            self.token = json.load(response)["token"]

    def read(self, resource: str) -> tuple[bytes, str]:
        request = Request(
            f"https://ghcr.io/v2/{PACKAGE}/{resource}",
            headers={"Authorization": "Bearer " + self.token, "Accept": ACCEPT},
        )
        with OPEN(request, timeout=90) as response:
            payload = response.read()
            digest = "sha256:" + hashlib.sha256(payload).hexdigest()
            if response.headers.get("Docker-Content-Digest", digest) != digest:
                raise ValueError("Registry content digest mismatch.")
        return payload, digest

    def copy_alias(self, payload: bytes, media_type: str, digest: str) -> None:
        request = Request(
            f"https://ghcr.io/v2/{PACKAGE}/manifests/image-rebuild",
            data=payload, method="PUT",
            headers={"Authorization": "Bearer " + self.token, "Content-Type": media_type},
        )
        with OPEN(request, timeout=90) as response:
            if response.status != 201 or response.headers.get("Docker-Content-Digest") != digest:
                raise ValueError("Registry did not preserve the promoted index digest.")
        target, actual = self.read("manifests/image-rebuild")
        if actual != digest or target != payload:
            raise ValueError("Rolling alias verification failed.")


def verified_profile(registry: Registry, payload: bytes, tag: str, sha: str) -> dict[str, bool]:
    index = json.loads(payload)
    if index.get("mediaType") not in ACCEPT.split(", ")[:2]:
        raise ValueError("Promotion requires a multi-platform OCI/Docker index.")
    descriptors = index["manifests"]
    if len(descriptors) != 2 or {
        (item["platform"]["os"], item["platform"]["architecture"]) for item in descriptors
    } != {("linux", "amd64"), ("linux", "arm64")}:
        raise ValueError("Index must retain exactly the two checked native platforms.")
    profiles = []
    for item in descriptors:
        manifest_data, actual = registry.read("manifests/" + item["digest"])
        if actual != item["digest"]:
            raise ValueError("Platform manifest digest mismatch.")
        manifest = json.loads(manifest_data)
        config_data, actual = registry.read("blobs/" + manifest["config"]["digest"])
        if actual != manifest["config"]["digest"]:
            raise ValueError("Platform configuration digest mismatch.")
        config = json.loads(config_data)
        if (config["os"], config["architecture"]) != (
            item["platform"]["os"], item["platform"]["architecture"]
        ):
            raise ValueError("Platform descriptor/configuration mismatch.")
        labels = config["config"]["Labels"]
        if (
            labels["org.opencontainers.image.revision"] != sha
            or labels["org.opencontainers.image.source"] != f"https://github.com/{REPOSITORY}.git"
        ):
            raise ValueError("Image source provenance mismatch.")
        values = {name: labels["io.agent-zero.include-" + name] for name in FEATURES}
        if any(value not in ("true", "false") for value in values.values()):
            raise ValueError("Invalid image capability labels.")
        profiles.append({name: value == "true" for name, value in values.items()})
    if profiles[0] != profiles[1] or tag != IMAGE + ":experimental-" + sha + profile_suffix(profiles[0]):
        raise ValueError("Native platforms and published profile tag must agree.")
    return profiles[0]


def main() -> None:
    run_id = int(os.environ["SOURCE_RUN_ID"])
    run = api(f"actions/runs/{run_id}")
    expected = os.environ.get("EXPECTED_DIGEST", "")
    registry = Registry()
    for _ in range(3):
        publication = published_index(run)
        log = api(f"actions/jobs/{publication['id']}/logs", raw=True)
        tag, digest = index_provenance(log, run["head_sha"])
        if expected and expected != digest:
            raise ValueError("Requested fixed digest differs from validated publication.")
        payload, actual = registry.read("manifests/" + digest)
        if actual != digest:
            raise ValueError("Source index digest mismatch.")
        features = verified_profile(registry, payload, tag, run["head_sha"])
        newer = newer_publication(run)
        if newer:
            if expected:
                raise RuntimeError("Explicit promotion would overwrite a newer checked selection.")
            # Job concurrency can replace pending alias jobs. Reconcile the newest
            # checked selection even if this job was triggered by an older build.
            run = api(f"actions/runs/{newer}")
            continue
        registry.copy_alias(payload, json.loads(payload)["mediaType"], digest)
        break
    else:
        raise RuntimeError("Publications changed repeatedly; retry rolling tag reconciliation.")
    print(json.dumps({"alias": IMAGE + ":image-rebuild", "source_tag": tag, "digest": digest, "features": features}))
    summary = Path(os.environ["GITHUB_STEP_SUMMARY"])
    with summary.open("a") as output:
        output.write(
            f"### Rolling image-rebuild tag\n\n`{IMAGE}:image-rebuild`\n\n"
            f"Exact index: `{digest}`\n\nRetained source tag: `{tag}`\n\n"
            f"[Validated build](https://github.com/{REPOSITORY}/actions/runs/{run['id']})\n\n"
            "| Included capability | Value |\n| --- | --- |\n"
            + "".join(f"| {name} | {str(value).lower()} |\n" for name, value in features.items())
            + "\nThis mutable alias follows the selected successfully published profile, not always all-on. "
            "Both native platforms are retained; other stable tags are unchanged.\n"
        )


if __name__ == "__main__":
    main()
