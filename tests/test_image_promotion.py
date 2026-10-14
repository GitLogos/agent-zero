import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


@pytest.fixture
def promotion(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "docker" / "slim"))
    spec = importlib.util.spec_from_file_location("image_promotion", ROOT / "docker/slim/promote_image.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_timestamped_index_logs_lock_source_tag_and_digest(promotion):
    tag = promotion.IMAGE + ":experimental-" + SHA + "-d1-o0-w0-k0-c0-s0"
    log = f"2026-10-13T10:19:44Z Name: {tag}\n2026-10-13T10:19:44Z Digest: {DIGEST}\n"
    assert promotion.index_provenance(log, SHA) == (tag, DIGEST)
    for invalid in (log.replace(SHA, "c" * 40), log + log, log.replace("Digest:", "Unknown:")):
        with pytest.raises(ValueError):
            promotion.index_provenance(invalid, SHA)


def test_requires_successful_manual_native_publication(promotion, monkeypatch):
    run = {
        "id": 2, "head_branch": "image-rebuild", "event": "workflow_dispatch",
        "path": ".github/workflows/image-footprint.yml", "head_sha": SHA,
    }
    jobs = [
        {"name": "candidate (amd64, ubuntu-24.04)", "conclusion": "success"},
        {"name": "candidate (arm64, ubuntu-24.04-arm)", "conclusion": "success"},
        {"name": "publish-index", "conclusion": "success"},
    ]
    monkeypatch.setattr(promotion, "jobs", lambda _: jobs)
    assert promotion.published_index(run) == jobs[-1]
    jobs[0]["conclusion"] = "failure"
    with pytest.raises(ValueError):
        promotion.published_index(run)
    with pytest.raises(ValueError):
        promotion.published_index({**run, "event": "push"})
    with pytest.raises(ValueError):
        promotion.published_index({**run, "head_branch": "main"})
    with pytest.raises(ValueError):
        promotion.published_index({**run, "path": ".github/workflows/unrelated.yml"})


def test_older_publication_cannot_replace_newer_selection(promotion, monkeypatch):
    monkeypatch.setattr(promotion, "api", lambda _: {
        "workflow_runs": [{"id": 5}, {"id": 4}, {"id": 2}]
    })
    monkeypatch.setattr(promotion, "jobs", lambda run: [
        {"name": "publish-index", "conclusion": "success" if run == 4 else "skipped"}
    ])
    assert promotion.newer_publication({"id": 2}) == 4
    assert promotion.newer_publication({"id": 5}) is None


def test_both_platform_configs_must_match_profile_and_source(promotion):
    features = {name: name == "desktop" for name in promotion.FEATURES}
    tag = promotion.IMAGE + ":experimental-" + SHA + "-d1-o0-w0-k0-c0-s0"
    blobs = {}
    descriptors = []
    for index, arch in enumerate(("amd64", "arm64")):
        config_digest = "sha256:" + str(index + 1) * 64
        manifest_digest = "sha256:" + str(index + 3) * 64
        labels = {
            "org.opencontainers.image.revision": SHA,
            "org.opencontainers.image.source": "https://github.com/GitLogos/agent-zero.git",
            **{"io.agent-zero.include-" + name: str(value).lower() for name, value in features.items()},
        }
        blobs["blobs/" + config_digest] = {
            "os": "linux", "architecture": arch, "config": {"Labels": labels},
        }
        blobs["manifests/" + manifest_digest] = {"config": {"digest": config_digest}}
        descriptors.append({"digest": manifest_digest, "platform": {"os": "linux", "architecture": arch}})
    payload = json.dumps({"mediaType": promotion.ACCEPT.split(", ")[0], "manifests": descriptors}).encode()

    class Registry:
        def read(self, resource):
            return json.dumps(blobs[resource]).encode(), resource.split("/")[1]

    assert promotion.verified_profile(Registry(), payload, tag, SHA) == features
    config = blobs["blobs/sha256:" + "2" * 64]
    config["config"]["Labels"]["io.agent-zero.include-office"] = "true"
    with pytest.raises(ValueError, match="must agree"):
        promotion.verified_profile(Registry(), payload, tag, SHA)
    config["config"]["Labels"]["org.opencontainers.image.revision"] = "c" * 40
    with pytest.raises(ValueError, match="provenance"):
        promotion.verified_profile(Registry(), payload, tag, SHA)


def test_workflow_alias_is_opt_in_serialized_and_has_no_rebuild_promotion_path():
    workflow = yaml.safe_load((ROOT / ".github/workflows/image-footprint.yml").read_text())
    inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["promote_run_id"]["default"] == inputs["promote_digest"]["default"] == ""
    jobs = workflow["jobs"]
    assert "!inputs.promote_run_id" in jobs["baseline"]["if"]
    assert jobs["baseline"]["needs"] == jobs["promote-existing"]["needs"] == "validate-request"
    for name in ("rolling-tag", "promote-existing"):
        job = jobs[name]
        assert "workflow_dispatch" in job["if"] and "inputs.publish_experimental" in job["if"]
        assert job["concurrency"] == {"group": "ghcr-image-rebuild-alias", "cancel-in-progress": False}
        assert not any("build-push-action" in step.get("uses", "") for step in job["steps"])
        assert job["steps"][-1]["run"] == "python3 docker/slim/promote_image.py"
    assert jobs["rolling-tag"]["needs"] == "publish-index"


def test_alias_put_preserves_exact_index_bytes_and_checks_readback(promotion, monkeypatch):
    calls = []
    payload = b'{"schemaVersion":2, "manifests":[]}\n'

    class Response:
        status = 201
        headers = {"Docker-Content-Digest": DIGEST}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(promotion, "OPEN", lambda request, timeout: calls.append(request) or Response())
    registry = promotion.Registry.__new__(promotion.Registry)
    registry.token = "ephemeral-test-key"
    monkeypatch.setattr(registry, "read", lambda _: (payload, DIGEST))
    registry.copy_alias(payload, "application/vnd.oci.image.index.v1+json", DIGEST)
    assert calls[0].method == "PUT"
    assert calls[0].full_url.endswith("/manifests/image-rebuild")
    assert calls[0].data is payload
    monkeypatch.setattr(registry, "read", lambda _: (payload + b" ", DIGEST))
    with pytest.raises(ValueError, match="verification"):
        registry.copy_alias(payload, "application/vnd.oci.image.index.v1+json", DIGEST)


def test_registry_redirect_does_not_forward_credentials_to_blob_storage(promotion):
    request = promotion.Request("https://ghcr.io/v2/example/blobs/test", headers={"Authorization": "Bearer test"})
    redirected = promotion.RegistryRedirect().redirect_request(
        request, None, 302, "Found", {}, "https://blob-storage.example/test"
    )
    assert redirected.get_header("Authorization") is None


@pytest.mark.parametrize("newer,expected,error", [
    (False, "", None),
    (False, DIGEST, None),
    (True, "", None),
    (True, DIGEST, RuntimeError),
    (False, "sha256:" + "f" * 64, ValueError),
])
def test_main_reconciles_newest_selection_but_fixed_promotions_never_drift(
    promotion, monkeypatch, tmp_path, newer, expected, error,
):
    copied = []
    runs = {2: {"id": 2, "head_sha": SHA}, 4: {"id": 4, "head_sha": "c" * 40}}
    digests = {2: DIGEST, 4: "sha256:" + "d" * 64}
    payload = b'{"mediaType":"application/vnd.oci.image.index.v1+json"}'
    features = {name: name == "desktop" for name in promotion.FEATURES}
    monkeypatch.setenv("SOURCE_RUN_ID", "2")
    monkeypatch.setenv("EXPECTED_DIGEST", expected)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))
    monkeypatch.setattr(promotion, "published_index", lambda run: {"id": run["id"]})

    def api(path, raw=False):
        run_id = int(path.split("/")[2])
        if raw:
            return (
                f"Name: {promotion.IMAGE}:experimental-{runs[run_id]['head_sha']}\n"
                f"Digest: {digests[run_id]}\n"
            )
        return runs[run_id]

    class Registry:
        def read(self, path):
            return payload, path.split("/")[1]

        def copy_alias(self, body, media, digest):
            copied.append((body, digest))

    monkeypatch.setattr(promotion, "api", api)
    monkeypatch.setattr(promotion, "Registry", Registry)
    monkeypatch.setattr(promotion, "verified_profile", lambda *_: features)
    monkeypatch.setattr(promotion, "newer_publication", lambda run: 4 if newer and run["id"] == 2 else None)
    if error:
        with pytest.raises(error):
            promotion.main()
        assert not copied
    else:
        promotion.main()
        assert copied == [(payload, digests[4 if newer else 2])]
        assert str(4 if newer else 2) in (tmp_path / "summary").read_text()


@pytest.mark.parametrize("run,digest,publish,valid", [
    ("", "", "", True),
    ("", "", "false", True),
    ("2", DIGEST, "true", True),
    ("2", DIGEST, "false", False),
    ("", DIGEST, "true", False),
    ("2", "", "true", False),
    ("0", DIGEST, "true", False),
    ("invalid", DIGEST, "true", False),
    ("2", "invalid", "true", False),
])
def test_invalid_retag_inputs_fail_before_build_or_publication(run, digest, publish, valid):
    workflow = yaml.safe_load((ROOT / ".github/workflows/image-footprint.yml").read_text())
    command = workflow["jobs"]["validate-request"]["steps"][0]["run"]
    script = command.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "SOURCE_RUN": run, "SOURCE_DIGEST": digest, "PUBLISH": publish},
        capture_output=True, text=True,
    )
    assert (result.returncode == 0) == valid
