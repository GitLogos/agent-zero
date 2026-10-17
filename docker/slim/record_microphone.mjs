// Exercise the real store with synthetic Web Audio and native MediaRecorder.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

const output = process.argv[2];
assert.ok(output, "Provide an isolated fixture output directory.");
const profile = await mkdtemp(path.join(os.tmpdir(), "a0-recorder-check-"));
const chrome = spawn(process.env.CHROME_BIN || "google-chrome", [
  "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
  "--autoplay-policy=no-user-gesture-required", "--remote-debugging-port=0",
  `--user-data-dir=${profile}`, "about:blank",
], { stdio: "ignore" });
let launchError;
chrome.on("error", error => { launchError = error; });
let socket;
try {
  let port;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (launchError) throw launchError;
    try {
      port = Number((await readFile(path.join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]);
      break;
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      await sleep(100);
    }
  }
  assert.ok(port, "Synthetic microphone browser did not become ready.");
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(page => page.type === "page").webSocketDebuggerUrl);
  await once(socket, "open");
  const source = (await readFile("plugins/_whisper_stt/webui/whisper-stt-store.js", "utf8"))
    .replace(/^import .*;$/gm, "").replace("export const store", "const store");
  const expression = `(async () => {
    globalThis.createStore = (_, model) => model;
    ${source}
    const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
    const uploads = [], fixtures = [], errors = [], recorders = [];
    const NativeRecorder = MediaRecorder;
    window.toastFetchError = (_, error) => errors.push(error.message);
    let delivered = 0;
    globalThis.callJsonApi = async (_, {audio}) => {
      uploads.push(audio);
      return {success: true, text: "Synthetic fixture"};
    };
    for (const mime of ["audio/webm;codecs=opus", "audio/mp4;codecs=mp4a.40.2"]) {
      if (!NativeRecorder.isTypeSupported(mime)) continue;
      globalThis.MediaRecorder = class extends NativeRecorder {
        constructor(stream) { super(stream, {mimeType: mime}); recorders.push(this); }
      };
      const context = new AudioContext({sampleRate: 48000});
      const oscillator = context.createOscillator();
      oscillator.frequency.value = 440;
      const destination = context.createMediaStreamDestination();
      oscillator.connect(destination);
      oscillator.start();
      await context.resume();
      let mic;
      const owner = {
        config: {waiting_timeout: 2000}, notifyStatusChange() {},
        stop() { mic.status = "inactive"; mic.dispose(); },
      };
      mic = new MicrophoneInput(owner, async () => delivered++);
      mic.mediaStream = destination.stream;
      mic.status = "listening";
      for (let turn = 0; turn < 3; turn++) {
        const before = uploads.length;
        await delay(turn === 1 ? 2300 : 40);
        if (uploads.length !== before) throw new Error("Idle audio was uploaded.");
        mic.status = "recording";
        await delay(50);
        mic.status = "waiting";
        if (turn === 1) {
          await delay(40);
          mic.status = "recording";
          await delay(50);
          mic.status = "waiting";
        }
        await delay(40);
        mic._status = "processing";
        mic.clearCaptureTimers();
        await mic.process();
        if (uploads.length !== before + 1) throw new Error("Missing complete utterance upload.");
        fixtures.push({mime, turn, audio: uploads.at(-1)});
      }
      const before = uploads.length;
      let conversionStarted, release;
      const converting = new Promise(resolve => conversionStarted = resolve);
      const blocked = new Promise(resolve => release = resolve);
      mic.convertBlobToBase64 = async () => { conversionStarted(); await blocked; return "must-not-upload"; };
      mic.status = "recording";
      await delay(80);
      mic._status = "processing";
      mic.clearCaptureTimers();
      const pending = mic.process();
      await converting;
      mic.status = "inactive";
      mic.dispose();
      release();
      await pending;
      if (uploads.length !== before) throw new Error("Stopped conversion uploaded audio.");
      oscillator.stop();
      await context.close();
      if (recorders.some(recorder => recorder.state !== "inactive")) throw new Error("Encoder leaked after dispose.");
      if (destination.stream.getTracks().some(track => track.readyState !== "ended")) throw new Error("Stream leaked.");
    }
    if (errors.length) throw new Error(errors.join("; "));
    if (fixtures.length < 3 || delivered !== fixtures.length) throw new Error("Native recorder checks did not execute.");
    return fixtures;
  })()`;
  const result = new Promise((resolve, reject) => {
    socket.addEventListener("message", event => {
      const message = JSON.parse(event.data);
      if (message.id !== 1) return;
      if (message.error || message.result?.exceptionDetails) {
        reject(new Error(JSON.stringify(message.error || message.result.exceptionDetails)));
      } else resolve(message.result.result.value);
    });
    socket.addEventListener("error", reject);
  });
  socket.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: {
    expression, awaitPromise: true, returnByValue: true, timeout: 45000,
  } }));
  const fixtures = await Promise.race([
    result, sleep(50000, undefined, { ref: false }).then(() => { throw new Error("Native MediaRecorder checks timed out."); }),
  ]);
  for (const [index, fixture] of fixtures.entries()) {
    const extension = fixture.mime.includes("mp4") ? "mp4" : "webm";
    await writeFile(path.join(output, `browser-${index}.${extension}`), Buffer.from(fixture.audio, "base64"));
  }
  console.log(JSON.stringify({ native_recordings: fixtures.length, mime_types: [...new Set(fixtures.map(fixture => fixture.mime))] }));
} finally {
  socket?.close();
  if (chrome.exitCode === null && chrome.pid) {
    chrome.kill();
    await Promise.race([once(chrome, "exit"), sleep(3000)]);
    if (chrome.exitCode === null) {
      chrome.kill("SIGKILL");
      await once(chrome, "exit");
    }
  }
  await rm(profile, { recursive: true, force: true });
}
