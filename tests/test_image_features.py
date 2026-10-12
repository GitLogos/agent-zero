import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from helpers import image_features


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profile = load_module("image_profile", "docker/slim/image_profile.py")
selection = load_module("image_selection", "docker/run/fs/ins/select_image_requirements.py")
configuration = load_module("image_configuration", "docker/run/fs/ins/configure_image_features.py")


@pytest.fixture(autouse=True)
def isolated_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(image_features, "MANIFEST", tmp_path / "features.json")
    image_features.get_features.cache_clear()
    yield
    image_features.get_features.cache_clear()


def test_legacy_nonprofile_runtime_preserves_all_features():
    assert all(image_features.get_features().values())
    assert not image_features.unavailable_reason("_office")


@pytest.mark.parametrize("disabled", [
    (), image_features.FEATURES, ("desktop", "kokoro"), ("office", "whisper", "chromium", "searxng"),
])
def test_independent_features_filter_only_approved_speech_roots(disabled):
    features = {name: name not in disabled for name in image_features.FEATURES}
    image_features.MANIFEST.write_text(json.dumps(features))
    assert image_features.get_features() == features
    for name in features:
        assert image_features.available(name) == features[name]
        if not features[name]:
            with pytest.raises(RuntimeError, match="not included"):
                image_features.require(name)
    source = (ROOT / "requirements.txt").read_text()
    selected = selection.select_requirements(source, features)
    for line in source.splitlines(keepends=True):
        if line.startswith("kokoro"):
            assert (line in selected) == features["kokoro"]
        elif line.startswith("openai-whisper"):
            assert (line in selected) == features["whisper"]
        else:
            assert line in selected


def test_profile_names_are_noncolliding_and_keep_all_on_compatibility():
    features = dict.fromkeys(image_features.FEATURES, True)
    assert profile.profile_suffix(features) == ""
    names = set()
    for feature in image_features.FEATURES:
        selected = {**features, feature: False}
        names.add(profile.profile_suffix(selected))
    assert len(names) == 6
    assert profile.profile_suffix(dict.fromkeys(image_features.FEATURES, False)) == "-d0-o0-w0-k0-c0-s0"
    assert profile.FEATURES == configuration.FEATURES == image_features.FEATURES


@pytest.mark.parametrize("data", [{"desktop": False}, dict.fromkeys(image_features.FEATURES, "false"), []])
def test_invalid_manifest_is_not_silently_enabled(data):
    image_features.MANIFEST.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        image_features.get_features()


def test_search_exclusion_removes_supervisor_program_not_other_services(tmp_path):
    path = tmp_path / "supervisor.conf"
    original = (ROOT / "docker/run/fs/etc/supervisor/conf.d/supervisord.conf").read_text()
    path.write_text(original)
    configuration.configure_supervisor(path, dict.fromkeys(image_features.FEATURES, True))
    assert path.read_text() == original
    configuration.configure_supervisor(path, dict.fromkeys(image_features.FEATURES, False))
    result = path.read_text()
    assert "[program:run_searxng]" not in result
    for program in ("run_ui", "run_sshd", "run_cron", "run_tunnel_api"):
        assert "[program:" + program + "]" in result


def test_environment_false_values_are_preserved_and_invalid_values_fail(monkeypatch):
    for name in configuration.FEATURES:
        monkeypatch.setenv("A0_INCLUDE_" + name.upper(), "false")
    assert not any(configuration.from_environment().values())
    monkeypatch.setenv("A0_INCLUDE_OFFICE", "0")
    with pytest.raises(ValueError):
        configuration.from_environment()


def test_workflow_boolean_defaults_and_real_build_args():
    workflow = yaml.safe_load((ROOT / ".github/workflows/image-footprint.yml").read_text())
    inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["publish_experimental"]["default"] is False
    candidate = workflow["jobs"]["candidate"]
    build = next(step for step in candidate["steps"] if step.get("uses", "").startswith("docker/build-push-action"))
    for feature in image_features.FEATURES:
        name = "include_" + feature
        assert inputs[name]["type"] == "boolean" and inputs[name]["default"] is True
        env = candidate["env"]["INCLUDE_" + feature.upper()]
        assert "github.event_name != 'workflow_dispatch' || inputs." + name in env
        assert "|| true" not in env
        assert "A0_INCLUDE_" + feature.upper() in build["with"]["build-args"]
    publish = next(step for step in candidate["steps"] if step.get("run") == 'docker push "$IMAGE"')
    assert "success()" in publish["if"] and "inputs.publish_experimental" in publish["if"]
    assert "success()" in workflow["jobs"]["publish-index"]["if"]
    smoke = next(step for step in candidate["steps"] if step.get("name") == "Run real retained-feature and omission checks")
    assert smoke["if"] == "always() && steps.startup.outcome == 'success'"


def test_feature_bootstrap_uses_only_standard_library():
    subprocess.run(
        [sys.executable, "-S", str(ROOT / "docker/run/fs/ins/configure_image_features.py"), "--help"],
        check=True, capture_output=True, timeout=30,
    )
