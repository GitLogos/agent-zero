"""Functional checks for a disposable, already-started Agent Zero container."""

import asyncio
import base64
import cProfile
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
import zipfile


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=120, **kwargs).strip()


def runtimes():
    assert callable(cProfile.run), "The check directory must not shadow stdlib profile"
    assert sys.version_info[:2] == (3, 12), sys.version
    output = run(
        "/opt/venv/bin/python", "-c",
        "import sys, requests; assert sys.version_info[:2] == (3, 13); print(sys.version)",
    )
    assert "3.13" in output
    assert run("node", "-e", "console.log(6 * 7)") == "42"
    assert run("npm", "--version")
    run("/usr/bin/python3", "-c", "import uno; print('UNO available')")
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory, "hello.c")
        source.write_text('#include <stdio.h>\nint main(void) { puts("native-code-ok"); return 0; }\n')
        binary = Path(directory, "hello")
        run("gcc", str(source), "-o", str(binary))
        assert run(str(binary)) == "native-code-ok"
    assert run("llvm-config", "--version")
    print("Python 3.12 framework, Python 3.13 tasks, UNO, Node/npm and native compilation work.")


async def memory():
    from plugins._memory.helpers.memory import Memory
    from plugins._model_config.helpers.model_config import get_embedding_model_config_object

    config = get_embedding_model_config_object()
    assert config.provider.lower() == "huggingface", config.provider
    db, _created = Memory.initialize(None, config, "image-smoke", in_memory=True)
    store = Memory(db, memory_subdir="image-smoke")
    identifier = await store.insert_text("Image verification remembers the code phrase silver lighthouse.")
    matches = await store.search_similarity_threshold("silver lighthouse", 3, 0.1)
    assert any(doc.metadata["id"] == identifier for doc in matches), matches
    assert await store.delete_documents_by_ids([identifier])
    print("Default bundled embeddings and FAISS memory save/recall/delete work offline.")


def offline_memory():
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    print(run(sys.executable, __file__, "--offline-memory", "--dockerized=true", env=env))


def diagnose_office_conversion(soffice, source, target, root):
    for safe_mode in (True, False):
        for vcl in ("gen", None):
            for isolated in (False, True):
                label = f"safe-{safe_mode}-vcl-{vcl}-isolated-{isolated}"
                output = root / label
                output.mkdir()
                args = [soffice]
                if isolated:
                    args.append(f"-env:UserInstallation={(output / 'profile').as_uri()}")
                args.append("--headless")
                if safe_mode:
                    args.append("--safe-mode")
                args.extend(["--convert-to", target, "--outdir", str(output), str(source)])
                env = {**os.environ, "HOME": os.environ.get("HOME") or "/tmp"}
                if vcl:
                    env["SAL_USE_VCLPLUGIN"] = vcl
                else:
                    env.pop("SAL_USE_VCLPLUGIN", None)
                diagnostic = {"safe_mode": safe_mode, "vcl": vcl, "isolated_profile": isolated}
                try:
                    process = subprocess.run(args, text=True, capture_output=True, timeout=20, env=env)
                except subprocess.TimeoutExpired:
                    diagnostic["error"] = "LibreOffice invocation timed out after 20 seconds"
                else:
                    diagnostic.update({
                        "exit_code": process.returncode,
                        "stdout": process.stdout,
                        "stderr": process.stderr,
                        "output_exists": (output / source.with_suffix("." + target).name).exists(),
                    })
                print(json.dumps(diagnostic, indent=2), flush=True)


def office_exports():
    import pymupdf
    from plugins._office.helpers import document_store, libreoffice

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for odf, ooxml, member in (
            ("odt", "docx", "word/document.xml"),
            ("ods", "xlsx", "xl/workbook.xml"),
            ("odp", "pptx", "ppt/presentation.xml"),
        ):
            source = root / f"IMAGE-SMOKE-{odf}.{odf}"
            source.write_bytes(document_store.template_bytes("document", odf, "IMAGE SMOKE", "Image verification content"))
            assert libreoffice.validate_odf(source)["ok"]
            for target in (ooxml, "pdf"):
                print(f"Converting {odf} to {target}", flush=True)
                converted = libreoffice.convert_document(source, target, root)
                if not converted["ok"]:
                    print(json.dumps({"framework_conversion_result": converted}, indent=2), flush=True)
                    diagnose_office_conversion(libreoffice.find_soffice(), source, target, root)
                assert converted["ok"], converted
                output = Path(converted["path"])
                assert output.stat().st_size > 100, output
                if target == "pdf":
                    with pymupdf.open(output) as pdf:
                        assert len(pdf) > 0
                else:
                    with zipfile.ZipFile(output) as archive:
                        assert member in archive.namelist()
    print("Writer/Calc/Impress export OOXML and PDF.")


def document_parsing():
    import pymupdf
    from plugins._office.helpers import document_store
    from unstructured.partition.docx import partition_docx
    from unstructured.partition.pdf import partition_pdf

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        docx = root / "parsing.docx"
        docx.write_bytes(document_store.template_bytes(
            "document", "docx", "IMAGE SMOKE", "Image verification content"
        ))
        assert "verification" in " ".join(str(item) for item in partition_docx(filename=str(docx)))
        pdf = root / "parsing.pdf"
        with pymupdf.open() as document:
            document.new_page().insert_text((72, 72), "Image verification content")
            document.save(pdf)
        assert "verification" in " ".join(str(item) for item in partition_pdf(filename=str(pdf), strategy="fast"))
    print("Unstructured DOCX/PDF parsing works.")


def ocr():
    from PIL import Image, ImageDraw, ImageFont

    with tempfile.TemporaryDirectory() as directory:
        image = Image.new("RGB", (1300, 180), "white")
        draw = ImageDraw.Draw(image)
        font_path = run("fc-match", "-f", "%{file}", "DejaVu Sans")
        draw.text((30, 50), "AGENT ZERO 31415", fill="black", font=ImageFont.truetype(font_path, 70))
        png = Path(directory, "ocr.png")
        image.save(png)
        assert "31415" in run("tesseract", str(png), "stdout", "--psm", "6")
    print("Tesseract recognizes rendered text.")


def ffmpeg():
    with tempfile.TemporaryDirectory() as directory:
        audio = Path(directory, "tone.wav")
        run("ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", str(audio))
        assert audio.stat().st_size > 1000
    print("ffmpeg generates an audio file.")


def plugin_hooks():
    from plugins._browser import hooks as browser
    from plugins._desktop import hooks as desktop
    from plugins._office import hooks as office

    assert browser.prepare_playwright_cache()["binary"]
    for hook in (office, desktop):
        result = hook.cleanup_stale_runtime_state()
        assert result["ok"], result
        assert not result["installed"], f"Missing build-time dependencies: {result}"
    print("Normal browser/Office/Desktop hooks reconcile without installing missing packages.")


async def browser():
    from patchright.async_api import async_playwright
    from plugins._browser.helpers.interactive_view import BrowserInteractiveView
    from plugins._browser.helpers.playwright import get_playwright_binary

    viewer = BrowserInteractiveView("image-smoke")
    try:
        state = viewer.ensure_viewer(1024, 768)
        assert state["available"], state
        with urllib.request.urlopen(f"http://127.0.0.1:{viewer.port}/", timeout=15) as response:
            assert response.status == 200
        async with async_playwright() as playwright:
            for headless in (True, False):
                browser = await playwright.chromium.launch(
                    executable_path=str(get_playwright_binary()), headless=headless,
                    args=["--no-sandbox"], env={**os.environ, "DISPLAY": viewer.display_name},
                )
                try:
                    page = await browser.new_page()
                    await page.goto("data:text/html,<h1>Image smoke</h1><input id='code'>")
                    await page.locator("#code").fill("browser-ok")
                    assert await page.locator("#code").input_value() == "browser-ok"
                    assert await page.locator("h1").inner_text() == "Image smoke"
                    assert (await page.screenshot()).startswith(b"\x89PNG\r\n\x1a\n")
                finally:
                    await browser.close()
    finally:
        viewer.close()
    print("Patchright navigation/input/screenshots work headless and headful with the Xpra viewer.")


def live_office():
    from plugins._desktop.helpers.desktop_session import DesktopSessionManager
    from plugins._office.helpers.document_store import create_document

    manager = DesktopSessionManager()
    try:
        doc = create_document("document", "IMAGE SMOKE LIVE", "odt", "Interactive Office verification")
        state = manager.open(doc)
        assert state["available"], state
        env = {**os.environ, "DISPLAY": state["display"]}
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            windows = run("xwininfo", "-root", "-tree", env=env)
            if "IMAGE SMOKE LIVE" in windows:
                break
            time.sleep(0.5)
        else:
            raise AssertionError(f"LibreOffice document window did not open: {windows}")
    finally:
        manager.shutdown()
    print("Xfce/Xpra Desktop opens a real LibreOffice Writer document window.")


def search_and_services():
    import yaml

    settings = yaml.safe_load(Path("/etc/searxng/settings.yml").read_text())
    port = settings["server"]["port"]
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/search?q=LibreOffice&format=json", timeout=90
    ) as response:
        result = json.load(response)
    assert result["query"] == "LibreOffice", result
    assert result["results"], f"SearXNG returned no real search results: {result}"
    statuses = run("supervisorctl", "status")
    for service in ("run_ui", "run_sshd", "run_searxng", "run_cron"):
        assert any(line.startswith(service + " ") and "RUNNING" in line for line in statuses.splitlines()), statuses
    run("/usr/sbin/sshd", "-t")
    print("SearXNG returns search results; supervised WebUI, SSH, search and cron are running.")


async def speech():
    from plugins._kokoro_tts.helpers import runtime as tts
    from plugins._whisper_stt.helpers import runtime as stt

    audio = await tts.synthesize_sentences(
        ["The image smoke test is successful."], {"voice": "af_heart", "speed": 1.0}
    )
    assert base64.b64decode(audio).startswith(b"RIFF")
    result = await stt.transcribe(audio, {"model_size": "base", "language": "en"})
    text = result.get("text", "").strip().lower()
    assert "test" in text or "image" in text, result
    print("Kokoro synthesizes speech and Whisper base transcribes the generated audio.")


def main():
    from helpers import runtime

    runtime.initialize()
    if "--offline-memory" in sys.argv:
        asyncio.run(memory())
        return
    if "--baseline" in sys.argv:
        cases = {
            "runtimes": runtimes,
            "offline_memory": offline_memory,
            "office_exports": office_exports,
            "document_parsing": document_parsing,
            "ocr": ocr,
            "ffmpeg": ffmpeg,
        }
    else:
        cases = {
            "runtimes": runtimes,
            "offline_memory": offline_memory,
            "office_exports": office_exports,
            "document_parsing": document_parsing,
            "ocr": ocr,
            "ffmpeg": ffmpeg,
            "plugin_hooks": plugin_hooks,
            "browser_headless_and_interactive": lambda: asyncio.run(browser()),
            "live_office": live_office,
            "search_and_services": search_and_services,
            "speech_synthesis_and_transcription": lambda: asyncio.run(speech()),
        }
    results = {}
    for name, check in cases.items():
        print(f"\n=== {name} ===", flush=True)
        try:
            check()
        except Exception as exc:
            traceback.print_exc()
            results[name] = {"passed": False, "error": str(exc)}
        else:
            results[name] = {"passed": True}
    Path("/tmp/image-smoke-results.json").write_text(json.dumps(results, indent=2))
    assert all(result["passed"] for result in results.values()), results


if __name__ == "__main__":
    main()
