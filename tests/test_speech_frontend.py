from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_settings_preserve_invalid_external_options_until_explicitly_corrected():
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const kokoro = fs.readFileSync("plugins/_kokoro_tts/webui/config.html", "utf8");
const settings = vm.runInThisContext("(" + kokoro.match(/x-data="([\s\S]*?)"\s*>/)[1] + ")");
global.config = { backend: "openai", speed: -1, request_timeout: null };
settings.initConfig();
assert.equal(config.speed, -1);
assert.equal(config.request_timeout, null);
config = { backend: "local", speed: -1 };
settings.initConfig();
assert.equal(config.speed, 1.1);
assert.equal(config.request_timeout, 120);
config = { backend: null };
settings.initConfig();
assert.equal(config.backend, null);
config = {};
settings.initConfig();
assert.equal(config.backend, "local");
const whisper = fs.readFileSync("plugins/_whisper_stt/webui/config.html", "utf8");
const initialize = whisper.match(/x-init="([^"]*)"/)[1];
config = { backend: null, request_timeout: null };
vm.runInThisContext(initialize);
assert.equal(config.backend, null);
assert.equal(config.request_timeout, null);
config = {};
vm.runInThisContext(initialize);
assert.equal(config.backend, "local");
assert.equal(config.request_timeout, 120);
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)


def test_tts_external_failure_never_falls_back_and_stop_cancels_synthesis():
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
global.window = { speechSynthesis: { speaking: false, cancel() {} } };
global.document = { addEventListener() {} };
global.CustomEvent = class extends Event { constructor(type, options) { super(type); this.detail = options.detail; } };
const notices = [];
global.shortcuts = { frontendNotification: (value) => notices.push(value) };
global.sleep = async () => {};
let source = fs.readFileSync("webui/js/tts-service.js", "utf8");
source = source.replace(/^import .*;$/gm, "").replace("export const ttsService", "globalThis.ttsService");
vm.runInThisContext(source);
(async () => {
  const tts = global.ttsService;
  tts.userHasInteracted = true;
  let fallback = 0;
  tts.speakWithBrowser = async () => fallback++;
  const remove = tts.registerProvider("external", {
    allowBrowserFallback: () => false,
    synthesize: async () => { throw new Error("External service HTTP 401"); },
  });
  await tts.speak("Fixture message.");
  assert.equal(fallback, 0);
  assert.equal(tts.ttsStream.running, false);
  assert.equal(tts.ttsStream.stopped, true);
  assert.equal(notices.at(-1).message, "External service HTTP 401");
  remove();
  tts.registerProvider("local", { synthesize: async () => { throw new Error("Local failure"); } });
  await tts.speak("Local fixture.");
  assert.equal(fallback, 1);
  tts.unregisterProvider("local");
  let requestSignal;
  let started;
  const ready = new Promise(resolve => started = resolve);
  tts.registerProvider("external", {
    allowBrowserFallback: () => false,
    synthesize: (text, { signal }) => new Promise((resolve, reject) => {
      requestSignal = signal;
      signal.addEventListener("abort", () => reject(new DOMException("Cancelled", "AbortError")));
      started();
    }),
  });
  const pending = tts.speak("Cancellation fixture.");
  await ready;
  tts.stop();
  await pending;
  assert.equal(requestSignal.aborted, true);
  assert.equal(fallback, 1);
  assert.equal(tts.ttsStream.running, false);
  assert.equal(tts.pendingSynthesis.size, 0);
  tts.unregisterProvider("external");
  tts.registerProvider("cached-local", {
    allowBrowserFallback: () => true,
    synthesize: async () => {
      const error = new Error("Actual backend is external");
      error.allowBrowserFallback = false;
      throw error;
    },
  });
  await tts.speak("Stale local status.");
  assert.equal(fallback, 1);
  tts.unregisterProvider("cached-local");
  tts.registerProvider("cached-external", {
    allowBrowserFallback: () => false,
    synthesize: async () => {
      const error = new Error("Actual backend is local");
      error.allowBrowserFallback = true;
      throw error;
    },
  });
  await tts.speak("Stale external status.");
  assert.equal(fallback, 2);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)


def test_microphone_stop_aborts_upload_and_failed_transcription_is_visible():
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const notices = [];
global.window = { toastFetchError: (label, error) => notices.push(error.message) };
global.createStore = (name, model) => model;
global.requestAnimationFrame = () => 0;
global.cancelAnimationFrame = () => {};
let source = fs.readFileSync("plugins/_whisper_stt/webui/whisper-stt-store.js", "utf8");
source = source.replace(/^import .*;$/gm, "").replace("export const store", "globalThis.store");
vm.runInThisContext(source + "\nglobalThis.Microphone = MicrophoneInput;");
(async () => {
  let sent = 0;
  let signal;
  let start;
  const ready = new Promise(resolve => start = resolve);
  global.callJsonApi = (path, input, options) => new Promise((resolve, reject) => {
    signal = options.signal;
    signal.addEventListener("abort", () => reject(new DOMException("Cancelled", "AbortError")));
    start();
  });
  const makeMic = () => {
    const mic = new global.Microphone({ notifyStatusChange() {}, config: {} }, async () => sent++);
    mic._status = "processing";
    mic.capture = {
      recorder: { state: "inactive", mimeType: "audio/webm" },
      chunks: [new Blob(["fixture"], { type: "audio/webm" })],
      stopped: Promise.resolve(),
    };
    mic.convertBlobToBase64 = async () => "fixture";
    return mic;
  };
  const mic = makeMic();
  const pending = mic.process();
  await ready;
  mic.status = "inactive";
  mic.dispose();
  await pending;
  assert.equal(signal.aborted, true);
  assert.equal(sent, 0);
  assert.equal(notices.length, 0);
  let rejectCsrf;
  let startCsrf;
  const csrfReady = new Promise(resolve => startCsrf = resolve);
  global.callJsonApi = () => new Promise((resolve, reject) => {
    rejectCsrf = reject;
    startCsrf();
  });
  const cancelled = makeMic();
  const csrfPending = cancelled.process();
  await csrfReady;
  cancelled.status = "inactive";
  cancelled.dispose();
  rejectCsrf(new Error("CSRF acquisition failed after stop"));
  await csrfPending;
  assert.equal(notices.length, 0);
  assert.equal(sent, 0);
  global.callJsonApi = async () => ({ success: false, error: "External STT HTTP 503", text: "must not send" });
  const failed = makeMic();
  await failed.process();
  assert.equal(sent, 0);
  assert.equal(notices.at(-1), "External STT HTTP 503");
  assert.equal(failed.status, "listening");
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)


def test_recorder_keeps_complete_containers_preroll_and_final_data_for_repeated_turns():
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
let source = fs.readFileSync("plugins/_whisper_stt/webui/whisper-stt-store.js", "utf8");
source = source.replace(/^import .*;$/gm, "").replace("export const store", "globalThis.store");
global.createStore = (name, model) => model;
global.requestAnimationFrame = () => 0;
global.cancelAnimationFrame = () => {};
const timers = new Map();
let timerId = 0;
global.setTimeout = (fn, delay) => {
  const id = ++timerId;
  timers.set(id, { fn: () => { timers.delete(id); fn(); }, delay });
  return id;
};
global.clearTimeout = id => timers.delete(id);
global.window = { toastFetchError: (title, error) => { throw error; } };
const recordings = [];
class Recorder {
  constructor(stream) { this.stream = stream; this.mimeType = "audio/webm;codecs=opus"; this.state = "inactive"; recordings.push(this); }
  start(timeslice) {
    assert.equal(timeslice, 250);
    this.state = "recording";
    this.emit("HEADER");
  }
  emit(text) { this.ondataavailable({ data: new Blob([text], { type: this.mimeType }) }); }
  stop() {
    this.state = "inactive";
    queueMicrotask(() => { this.emit("FINAL"); this.onstop(); });
  }
}
global.MediaRecorder = Recorder;
const uploads = [];
global.callJsonApi = async (url, input) => { uploads.push(input.audio); return { success: true, text: "fixture" }; };
vm.runInThisContext(source + "\nglobalThis.Microphone = MicrophoneInput;");
(async () => {
  let delivered = 0;
  const mic = new Microphone({ notifyStatusChange() {}, config: { waiting_timeout: 2000 }, stop() { mic.status = "inactive"; mic.dispose(); } }, async () => delivered++);
  mic.mediaStream = {};
  const blobs = [];
  mic.convertBlobToBase64 = async blob => { blobs.push(blob); return await blob.text(); };
  for (let turn = 0; turn < 3; turn++) {
    mic.status = "listening";
    const initial = mic.capture.recorder;
    initial.emit("PREROLL");
    // Begin a new idle recorder while the current one still retains preroll.
    const rotate = timers.get(mic.rotationTimer);
    rotate.fn();
    assert.ok(mic.nextCapture);
    if (turn === 1) {
      const old = mic.capture;
      const ready = timers.get(mic.rotationTimer);
      mic.nextCapture.recorder.emit("IDLE-PREROLL");
      ready.fn();
      assert.notEqual(mic.capture, old);
      assert.equal(old.recorder.state, "inactive");
    }
    const active = mic.capture.recorder;
    mic.status = "recording";
    assert.equal(mic.nextCapture, null);
    active.emit("VOICE");
    mic.status = "waiting";
    active.emit("SILENCE");
    mic.status = "recording";
    active.emit("MORE");
    mic.status = "waiting";
    // Invoke process directly to observe its awaited final data.
    mic._status = "processing";
    mic.clearCaptureTimers();
    const before = uploads.length;
    const processing = mic.process();
    assert.equal(uploads.length, before);
    await processing;
    assert.equal(uploads.length, before + 1);
    assert.match(uploads.at(-1), /^HEADER(?:PREROLL|IDLE-PREROLL)VOICESILENCEMOREFINAL$/);
    assert.equal(blobs.at(-1).type, "audio/webm;codecs=opus");
    assert.equal(mic.status, "listening");
    // The return to listening creates a fresh independent container.
    assert.equal(mic.capture.recorder.state, "recording");
  }
  assert.equal(delivered, 3);
  const before = uploads.length;
  mic.status = "recording";
  mic._status = "processing";
  const late = mic.process();
  mic.status = "inactive";
  mic.dispose();
  await late;
  assert.equal(uploads.length, before);
  assert.equal(timers.size, 0);
  assert.ok(recordings.every(recorder => recorder.state === "inactive"));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)


def test_excluded_local_tts_provider_never_allows_browser_fallback():
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
global.createStore = (name, model) => model;
let provider;
global.ttsService = {
  registerProvider: (name, value) => { provider = value; return () => {}; },
};
global.callJsonApi = async () => ({
  success: false, backend: "local", allow_browser_fallback: false,
  error: "Local Kokoro is not included in this image",
});
let source = fs.readFileSync("plugins/_kokoro_tts/webui/kokoro-tts-store.js", "utf8");
source = source.replace(/^import .*;$/gm, "").replace("export const store", "globalThis.store");
vm.runInThisContext(source);
(async () => {
  store.enabled = true;
  store.localAvailable = false;
  store.registerProvider();
  assert.equal(provider.allowBrowserFallback(), false);
  await assert.rejects(provider.synthesize("Fixture"), error => error.allowBrowserFallback === false);
  store.localAvailable = true;
  assert.equal(provider.allowBrowserFallback(), true);
  store.config.backend = "openai";
  assert.equal(provider.allowBrowserFallback(), false);
  store.config.backend = "local";
  store.localAvailable = false;
  store.statusLoaded = true;
  const cleanup = store.providerCleanup;
  global.callJsonApi = async () => { throw new Error("Status unavailable"); };
  await store.refreshStatus({ suppressError: true });
  assert.equal(store.providerCleanup, cleanup);
  assert.equal(provider.allowBrowserFallback(), false);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
