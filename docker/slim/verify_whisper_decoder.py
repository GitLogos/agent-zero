"""Prove multipart audio compatibility with whisper.cpp's real server decoder.

Build-only verification: synthetic tones, no model/inference, no user services.
"""

import asyncio
import base64
from email.parser import BytesParser
from email.policy import default
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen
import wave

import httpx


COMMIT = "0c7be696371069e0baa2515ed7aa08d5a5473aa6"
ARCHIVE_SHA256 = "20f6c4c2dd25225326d284b145998ffe48efabfee4e6c94c0437cb4f78dbab76"
ROOT = Path(__file__).resolve().parents[2]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, timeout=300, **kwargs)


def main():
    sys.path.insert(0, str(ROOT))
    from helpers import external_speech as speech

    if not shutil.which("ffmpeg"):
        raise RuntimeError("Real ffmpeg codec checks are required, not skipped.")
    with tempfile.TemporaryDirectory(prefix="a0-whisper-decoder-") as directory:
        work = Path(directory)
        with urlopen(
            f"https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/{COMMIT}", timeout=120
        ) as response:
            archive = response.read(20 * 1024 * 1024)
        if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
            raise ValueError("Pinned whisper.cpp source archive digest mismatch.")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
            source.extractall(work, filter="data")
        source = work / ("whisper.cpp-" + COMMIT)
        (work / "decoder.cpp").write_text(r'''
#include "common-whisper.h"
#include <cmath>
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>
int main(int argc, char ** argv) {
    if (argc != 2) return 3;
    std::ifstream input(argv[1], std::ios::binary);
    std::string bytes((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    std::vector<float> samples;
    std::vector<std::vector<float>> stereo;
    if (!read_audio_data(bytes.data(), bytes.size(), samples, stereo, false)) return 2;
    double energy = 0;
    for (float sample : samples) energy += sample * sample;
    if (samples.empty() || !std::isfinite(energy) || energy <= 0) return 4;
    std::cout << samples.size() << "\n";
}
''')
        (work / "CMakeLists.txt").write_text(f'''
cmake_minimum_required(VERSION 3.16)
project(a0_decoder_check C CXX)
set(CMAKE_CXX_STANDARD 17)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES ON CACHE BOOL "" FORCE)
set(WHISPER_COMMON_FFMPEG OFF CACHE BOOL "" FORCE)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)
set(GGML_BLAS OFF CACHE BOOL "" FORCE)
add_subdirectory("{source.as_posix()}" whisper)
add_executable(a0_decoder decoder.cpp)
target_include_directories(a0_decoder PRIVATE "{source.as_posix()}/examples")
target_link_libraries(a0_decoder PRIVATE common)
''')
        build = work / "build"
        run("cmake", "-S", str(work), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release")
        run("cmake", "--build", str(build), "--target", "a0_decoder", "--parallel", "2")
        decoder = build / "a0_decoder"
        fixtures = work / "fixtures"
        fixtures.mkdir()
        for extension, codec in (("webm", "libopus"), ("mp4", "aac"), ("wav", "pcm_s16le")):
            run(
                "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=0.2", "-ac", "2",
                "-c:a", codec, str(fixtures / ("generated." + extension)),
            )
        run("node", str(ROOT / "docker/slim/record_microphone.mjs"), str(fixtures), cwd=ROOT)
        outputs = []

        async def check():
            client_class = httpx.AsyncClient
            for recording in sorted(fixtures.iterdir()):
                original = recording.read_bytes()
                if recording.suffix in (".webm", ".mp4"):
                    rejected = subprocess.run([str(decoder), str(recording)], capture_output=True, timeout=15)
                    if rejected.returncode != 2 or b"failed to decode audio data from memory buffer" not in rejected.stderr:
                        raise AssertionError("Original encoded audio did not reproduce the upstream server decoder error.")
                captured = []

                def provider(request):
                    message = BytesParser(policy=default).parsebytes(
                        b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content
                    )
                    file = next(part for part in message.iter_parts() if part.get_filename())
                    assert file.get_filename() == "microphone.wav" and file.get_content_type() == "audio/wav"
                    captured.append(file.get_payload(decode=True))
                    return httpx.Response(200, json={"text": "Synthetic decoder fixture"})

                mock = httpx.MockTransport(provider)
                speech.httpx.AsyncClient = lambda **kwargs: client_class(transport=mock, **kwargs)
                try:
                    await speech.transcribe(base64.b64encode(original).decode(), {
                        **speech.DEFAULT_CONFIG, "external_base_url": "http://fixture.invalid/v1",
                        "external_model": "decoder-fixture",
                    }, "en")
                finally:
                    speech.httpx.AsyncClient = client_class
                assert len(captured) == 1
                wav = captured[0]
                assert int.from_bytes(wav[4:8], "little") == len(wav) - 8
                assert int.from_bytes(wav[40:44], "little") == len(wav) - 44
                with wave.open(io.BytesIO(wav), "rb") as audio:
                    assert (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) == (1, 16000, 2)
                    count = audio.getnframes()
                    assert count > 0 and any(audio.readframes(count))
                normalized = work / "multipart.wav"
                normalized.write_bytes(wav)
                decoded = run(str(decoder), str(normalized), capture_output=True, text=True)
                assert int(decoded.stdout.strip()) == count
                outputs.append({"recording": recording.name, "decoded_16khz_samples": count})

        asyncio.run(check())
        print(json.dumps({
            "whisper_cpp_commit": COMMIT, "archive_sha256": ARCHIVE_SHA256,
            "decoder": "Exact server read_audio_data(memory) without FFmpeg extension",
            "recognition_inference": "Not run; no model is needed to prove decoder compatibility",
            "captured_multipart_checks": outputs,
        }, indent=2))


if __name__ == "__main__":
    main()
