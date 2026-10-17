import { createStore } from "/js/AlpineStore.js";
import { toastFrontendError } from "/components/notifications/notification-store.js";
import { callJsonApi } from "/js/api.js";
import { sttService } from "/js/stt-service.js";
import { ttsService } from "/js/tts-service.js";
import { sendMessage, updateChatInput } from "/index.js";

const PLUGIN_NAME = "_whisper_stt";

const Status = {
  INACTIVE: "inactive",
  ACTIVATING: "activating",
  LISTENING: "listening",
  RECORDING: "recording",
  WAITING: "waiting",
  PROCESSING: "processing",
};

const MicButtonClasses = [
  "mic-disabled",
  "mic-inactive",
  "mic-activating",
  "mic-listening",
  "mic-recording",
  "mic-waiting",
  "mic-processing",
];

const MicStatusLabels = {
  disabled: "Whisper STT disabled",
  inactive: "Microphone standby",
  activating: "Microphone activating",
  listening: "Listening for speech",
  recording: "Recording voice",
  waiting: "Waiting for final silence",
  processing: "Transcribing voice",
};

function clearMicrophoneTooltip(element) {
  const tooltip = globalThis.bootstrap?.Tooltip?.getInstance?.(element);
  tooltip?.dispose?.();
  element.removeAttribute("title");
  element.removeAttribute("data-bs-original-title");
  element.removeAttribute("data-bs-toggle");
  element.removeAttribute("data-bs-trigger");
  element.removeAttribute("data-bs-tooltip-initialized");
}

const model = {
  runtimeInitialized: false,
  statusLoaded: false,
  loading: false,
  error: "",
  enabled: false,
  config: {
    backend: "local",
    external_model: "",
    model_size: "base",
    language: "en",
    message_mode: "send",
    silence_threshold: 0.3,
    silence_duration: 1000,
    waiting_timeout: 2000,
  },
  modelReady: false,
  localAvailable: true,
  modelLoading: false,
  loadedModel: "",
  packageVersion: "",
  providerCleanup: null,
  microphoneInput: null,
  finalTranscriptHandler: null,
  isProcessingClick: false,
  devices: [],
  selectedDevice: "",
  requestingPermission: false,
  _ttsListener: null,
  _deviceChangeListenerBound: false,

  async initRuntime() {
    if (this.runtimeInitialized) return;

    this.runtimeInitialized = true;
    await this.loadDevices();
    await this.refreshStatus({ suppressError: true });

    if (!this._deviceChangeListenerBound) {
      navigator.mediaDevices?.addEventListener?.("devicechange", () => {
        void this.loadDevices();
      });
      this._deviceChangeListenerBound = true;
    }

    if (!this._ttsListener) {
      this._ttsListener = (event) => {
        if (event?.detail?.isSpeaking && this.micStatus !== Status.INACTIVE) {
          this.stop();
        }
      };
      ttsService.addEventListener("statechange", this._ttsListener);
    }
  },

  async ensureStatusLoaded({ force = false, suppressError = true } = {}) {
    if ((!this.statusLoaded || force) && !this.loading) {
      await this.refreshStatus({ suppressError });
    }
  },

  async refreshStatus({ suppressError = false } = {}) {
    this.loading = true;
    this.error = "";

    try {
      const status = await callJsonApi(`/plugins/${PLUGIN_NAME}/status`, {});
      this.statusLoaded = true;
      this.enabled = !!status?.enabled;
      this.config = {
        backend: status?.config?.backend || "local",
        external_model: status?.config?.external_model || "",
        model_size: status?.config?.model_size || "base",
        language: status?.config?.language || "en",
        message_mode:
          status?.config?.message_mode === "draft" ? "draft" : "send",
        silence_threshold: Number(status?.config?.silence_threshold ?? 0.3),
        silence_duration: Number(status?.config?.silence_duration ?? 1000),
        waiting_timeout: Number(status?.config?.waiting_timeout ?? 2000),
      };
      this.modelReady = !!status?.model?.ready;
      this.localAvailable = status?.local_available !== false;
      this.modelLoading = !!status?.model?.loading;
      this.loadedModel = status?.model?.loaded_model || "";
      this.packageVersion = status?.package?.version || "";
      this.error = status?.configuration_error || "";

      if (this.enabled) {
        this.registerProvider();
      } else {
        this.unregisterProvider();
      }
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
      this.unregisterProvider();
      if (!suppressError) {
        void toastFrontendError(this.error, "Whisper STT");
      }
    } finally {
      this.loading = false;
      this.updateMicrophoneButtonUI();
    }
  },

  registerProvider() {
    if (this.providerCleanup || !this.enabled) return;

    this.providerCleanup = sttService.registerProvider(PLUGIN_NAME, {
      handleMicrophoneClick: async () => await this.handleMicrophoneClick(),
      requestMicrophonePermission: async () =>
        await this.requestMicrophonePermission(),
      updateMicrophoneButtonUI: () => this.updateMicrophoneButtonUI(),
      stop: () => this.stop(),
      getStatus: () => this.micStatus,
    });

    sttService.emitStatusChange(this.micStatus);
    this.updateMicrophoneButtonUI();
  },

  unregisterProvider() {
    if (!this.providerCleanup) return;

    this.stop();
    this.providerCleanup();
    this.providerCleanup = null;
  },

  async openConfig() {
    const { store } = await import("/components/plugins/plugin-settings-store.js");
    await store.openConfig(PLUGIN_NAME);
    await this.refreshStatus();
  },

  openPanel() {
    window.openModal?.(`/plugins/${PLUGIN_NAME}/webui/main.html`);
  },

  updateMicrophoneButtonUI() {
    const status = this.enabled ? this.micStatus : "disabled";
    const label = MicStatusLabels[status] || "Microphone";
    const microphoneButtons = document.querySelectorAll(
      "[data-whisper-microphone], #microphone-button",
    );
    for (const microphoneButton of microphoneButtons) {
      clearMicrophoneTooltip(microphoneButton);
      microphoneButton.classList.remove(...MicButtonClasses);
      microphoneButton.classList.add(`mic-${status}`);
      microphoneButton.setAttribute("data-status", status);
      microphoneButton.setAttribute("aria-label", label);
      microphoneButton.setAttribute(
        "aria-pressed",
        String(
          status !== "disabled" &&
            status !== Status.INACTIVE &&
            status !== Status.ACTIVATING,
        ),
      );
    }
  },

  async loadDevices() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      this.devices = devices.filter(
        (device) => device.kind === "audioinput" && device.deviceId,
      );

      const saved = localStorage.getItem("whisperSttSelectedDevice") || "";
      const savedStillExists = this.devices.some(
        (device) => device.deviceId === saved,
      );

      if (savedStillExists) {
        this.selectedDevice = saved;
        return;
      }

      const defaultDevice =
        this.devices.find((device) => device.deviceId === "default") ||
        this.devices[0];
      this.selectedDevice = defaultDevice?.deviceId || "";
    } catch (error) {
      console.error("[Whisper STT] Failed to enumerate audio devices", error);
      this.devices = [];
      this.selectedDevice = "";
    }
  },

  async selectDevice(deviceId) {
    this.selectedDevice = deviceId || "";
    localStorage.setItem("whisperSttSelectedDevice", this.selectedDevice);

    if (this.microphoneInput?.selectedDeviceId !== this.selectedDevice) {
      this.stop();
      this.microphoneInput = null;
    }
  },

  getSelectedDevice() {
    let device = this.devices.find(
      (candidate) => candidate.deviceId === this.selectedDevice,
    );

    if (!device && this.devices.length > 0) {
      device =
        this.devices.find((candidate) => candidate.deviceId === "default") ||
        this.devices[0];
    }

    return device || null;
  },

  async requestMicrophonePermission() {
    this.requestingPermission = true;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      await this.loadDevices();
      return true;
    } catch (error) {
      console.error("[Whisper STT] Microphone permission denied", error);
      globalThis.toast?.(
        "Microphone access denied. Please enable microphone access in your browser settings.",
        "error",
      );
      return false;
    } finally {
      this.requestingPermission = false;
    }
  },

  async handleMicrophoneClick(finalTranscriptHandler = null) {
    if (this.isProcessingClick) return;

    this.finalTranscriptHandler =
      typeof finalTranscriptHandler === "function" ? finalTranscriptHandler : null;
    this.isProcessingClick = true;
    try {
      await this.ensureStatusLoaded({ force: true, suppressError: false });
      if (!this.enabled) {
        this.finalTranscriptHandler = null;
        globalThis.justToast?.("Whisper STT is disabled.", "info");
        return;
      }

      ttsService.stop();

      const selectedDevice = this.getSelectedDevice();
      if (
        this.microphoneInput &&
        this.microphoneInput.selectedDeviceId !== (selectedDevice?.deviceId || "")
      ) {
        this.stop();
        this.microphoneInput = null;
      }

      if (!this.microphoneInput) {
        await this.initMicrophone();
      }

      if (this.microphoneInput) {
        await this.microphoneInput.toggle();
      }
    } finally {
      setTimeout(() => {
        this.isProcessingClick = false;
      }, 300);
    }
  },

  async initMicrophone() {
    if (this.microphoneInput) return this.microphoneInput;

    const input = new MicrophoneInput(this, async (text, isFinal) => {
      if (isFinal) {
        await this.deliverVoiceMessage(text);
      }
    });

    this.microphoneInput = input;
    const initialized = await input.initialize();
    if ((!initialized || input.disposed) && this.microphoneInput === input) {
      this.microphoneInput = null;
    }
    return this.microphoneInput;
  },

  async deliverVoiceMessage(text) {
    if (this.finalTranscriptHandler) {
      await this.finalTranscriptHandler(text, {
        messageMode: this.config.message_mode,
        sendImmediately: this.sendsImmediately,
      });
      return;
    }
    await this.sendVoiceMessage(text);
  },

  async sendVoiceMessage(text) {
    const message = String(text || "").trim();
    if (!message) return;

    updateChatInput(message);

    if (!this.sendsImmediately) {
      this.stop();
      return;
    }

    if (!this.microphoneInput?.messageSent) {
      this.microphoneInput.messageSent = true;
      await sendMessage();
    }
  },

  notifyStatusChange() {
    this.updateMicrophoneButtonUI();
    sttService.emitStatusChange(this.micStatus);
  },

  stop() {
    if (this.microphoneInput) {
      this.microphoneInput.status = Status.INACTIVE;
      this.microphoneInput.dispose();
      this.microphoneInput = null;
    }

    this.finalTranscriptHandler = null;

    this.notifyStatusChange();
  },

  get micStatus() {
    return this.microphoneInput?.status || Status.INACTIVE;
  },

  get sendsImmediately() {
    return this.config.message_mode !== "draft";
  },

  get messageModeLabel() {
    return this.sendsImmediately ? "Send immediately" : "Draft in composer";
  },

  get statusText() {
    if (!this.enabled) return "Disabled";
    if (this.error) return "Configuration error";
    if (this.config.backend === "openai") return this.modelReady ? "Configured" : "Not configured";
    if (this.modelLoading) return "Loading";
    if (this.modelReady) return "Ready";
    return "Idle";
  },

  get statusClass() {
    if (!this.enabled) return "warn";
    if (this.modelLoading) return "warn";
    if (this.modelReady) return "ok";
    return "warn";
  },

  get backendSummary() {
    return this.config.backend === "local" ? "Local Whisper" : "External OpenAI-compatible";
  },

  get modelSummary() {
    return this.config.backend === "openai" ? this.config.external_model : this.config.model_size;
  },

  get selectedDeviceLabel() {
    const device = this.getSelectedDevice();
    if (!device) return "System default";
    return device.label || "System default";
  },
};

class MicrophoneInput {
  constructor(owner, updateCallback) {
    this.owner = owner;
    this.updateCallback = updateCallback;
    this.mediaStream = null;
    this.mediaRecorder = null;
    this.audioContext = null;
    this.mediaStreamSource = null;
    this.analyserNode = null;
    this.capture = null;
    this.nextCapture = null;
    this.rotationTimer = null;
    this.captureLimitTimer = null;
    this.disposed = false;
    this.messageSent = false;
    this.lastAudioTime = null;
    this.waitingTimer = null;
    this.silenceStartTime = null;
    this.analysisFrame = null;
    this.selectedDeviceId = "";
    this._status = Status.INACTIVE;
    this.transcriptionController = null;
  }

  get status() {
    return this._status;
  }

  set status(nextStatus) {
    if (this._status === nextStatus) return;

    const previousStatus = this._status;
    this._status = nextStatus;
    this.handleStatusChange(previousStatus, nextStatus);
    this.owner.notifyStatusChange();
  }

  async initialize() {
    this.status = Status.ACTIVATING;

    try {
      const selectedDevice = this.owner.getSelectedDevice();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId:
            selectedDevice?.deviceId
              ? { exact: selectedDevice.deviceId }
              : undefined,
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      });
      if (this.disposed) {
        stream.getTracks().forEach((track) => track.stop());
        return false;
      }

      this.selectedDeviceId = selectedDevice?.deviceId || "";
      this.mediaStream = stream;
      this.setupAudioAnalysis(stream);
      return true;
    } catch (error) {
      if (this.disposed) return false;
      console.error("[Whisper STT] Microphone initialization failed", error);
      globalThis.toast?.(
        "Failed to access the microphone. Please check browser permissions.",
        "error",
      );
      this.status = Status.INACTIVE;
      this.dispose();
      return false;
    }
  }

  handleStatusChange(previousStatus, nextStatus) {
    switch (nextStatus) {
      case Status.INACTIVE:
        this.handleInactiveState();
        break;
      case Status.LISTENING:
        this.handleListeningState();
        break;
      case Status.RECORDING:
        this.handleRecordingState();
        break;
      case Status.WAITING:
        this.handleWaitingState();
        break;
      case Status.PROCESSING:
        this.handleProcessingState();
        break;
    }
  }

  handleInactiveState() {
    this.clearCaptureTimers();
    this.stopRecording();
    this.stopAudioAnalysis();
    clearTimeout(this.waitingTimer);
    this.waitingTimer = null;
  }

  handleListeningState() {
    this.silenceStartTime = null;
    this.lastAudioTime = null;
    this.messageSent = false;
    if (!this.disposed && this.mediaStream) {
      try {
        this.capture = this.startCapture();
        this.mediaRecorder = this.capture.recorder;
        this.scheduleCaptureRotation();
      } catch (error) {
        this.captureFailed(error);
        return;
      }
    }
    this.startAudioAnalysis();
  }

  handleRecordingState() {
    // Keep the already-running listening capture, including its container header
    // and pre-speech samples. VAD changes must never discard encoded chunks.
    this.clearCaptureTimers();
    this.captureLimitTimer = setTimeout(() => {
      this.captureFailed(new Error("Voice recording exceeds the 10-minute limit. Please record a shorter message."));
    }, Math.max(0, 600000 - (Date.now() - (this.capture?.startedAt || Date.now()))));
    clearTimeout(this.waitingTimer);
    this.waitingTimer = null;
  }

  handleWaitingState() {
    clearTimeout(this.waitingTimer);
    this.waitingTimer = setTimeout(() => {
      if (this.status === Status.WAITING) {
        this.status = Status.PROCESSING;
      }
    }, this.owner.config.waiting_timeout);
  }

  handleProcessingState() {
    this.clearCaptureTimers();
    void this.process();
  }

  startCapture() {
    const recorder = new MediaRecorder(this.mediaStream);
    const capture = { recorder, chunks: [], bytes: 0, error: null, startedAt: Date.now() };
    capture.stopped = new Promise((resolve) => {
      capture.cancel = resolve;
      recorder.ondataavailable = (event) => {
        if (!event.data.size) return;
        capture.bytes += event.data.size;
        if (capture.bytes > 50 * 1024 * 1024) {
          capture.error = new Error("Voice recording exceeds the 50 MiB limit. Please record a shorter message.");
          this.captureFailed(capture.error);
          return;
        }
        capture.chunks.push(event.data);
      };
      recorder.onerror = () => {
        capture.error = new Error("The browser could not encode microphone audio. Please restart the microphone.");
        this.captureFailed(capture.error);
      };
      recorder.onstop = () => resolve();
    });
    recorder.start(250);
    return capture;
  }

  scheduleCaptureRotation() {
    // Overlap complete recordings while idle instead of retaining individual
    // WebM/MP4 fragments, which need not have their own decoder headers.
    this.rotationTimer = setTimeout(() => {
      if (this.status !== Status.LISTENING || this.disposed) return;
      try {
        this.nextCapture = this.startCapture();
        this.rotationTimer = setTimeout(() => {
          if (this.status !== Status.LISTENING || this.disposed) return;
          const previous = this.capture;
          this.capture = this.nextCapture;
          this.nextCapture = null;
          this.mediaRecorder = this.capture.recorder;
          this.finishCapture(previous);
          this.scheduleCaptureRotation();
        }, 1000);
      } catch (error) {
        this.captureFailed(error);
      }
    }, 1000);
  }

  clearCaptureTimers() {
    clearTimeout(this.rotationTimer);
    clearTimeout(this.captureLimitTimer);
    this.rotationTimer = null;
    this.captureLimitTimer = null;
    if (this.nextCapture) {
      this.finishCapture(this.nextCapture);
      this.nextCapture.cancel();
      this.nextCapture = null;
    }
  }

  finishCapture(capture) {
    if (capture?.recorder.state === "recording") capture.recorder.stop();
    return capture?.stopped;
  }

  captureFailed(error) {
    if (this.disposed || this.status === Status.INACTIVE) return;
    window.toastFetchError?.("Microphone error", error);
    this.owner.stop();
  }

  setupAudioAnalysis(stream) {
    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    this.mediaStreamSource = this.audioContext.createMediaStreamSource(stream);
    this.analyserNode = this.audioContext.createAnalyser();
    this.analyserNode.fftSize = 2048;
    this.analyserNode.minDecibels = -90;
    this.analyserNode.maxDecibels = -10;
    this.analyserNode.smoothingTimeConstant = 0.85;
    this.mediaStreamSource.connect(this.analyserNode);
  }

  startAudioAnalysis() {
    const analyzeFrame = () => {
      if (this.status === Status.INACTIVE || !this.analyserNode) return;

      const dataArray = new Uint8Array(this.analyserNode.fftSize);
      this.analyserNode.getByteTimeDomainData(dataArray);

      let sum = 0;
      for (let index = 0; index < dataArray.length; index += 1) {
        const amplitude = (dataArray[index] - 128) / 128;
        sum += amplitude * amplitude;
      }

      const rms = Math.sqrt(sum / dataArray.length);
      const now = Date.now();
      const silenceThreshold = this.densify(this.owner.config.silence_threshold);

      if (rms > silenceThreshold) {
        this.lastAudioTime = now;
        this.silenceStartTime = null;

        if (
          (this.status === Status.LISTENING || this.status === Status.WAITING) &&
          !ttsService.isSpeaking()
        ) {
          this.status = Status.RECORDING;
        }
      } else if (this.status === Status.RECORDING) {
        if (!this.silenceStartTime) {
          this.silenceStartTime = now;
        }

        const silenceDuration = now - this.silenceStartTime;
        if (silenceDuration >= this.owner.config.silence_duration) {
          this.status = Status.WAITING;
        }
      }

      this.analysisFrame = requestAnimationFrame(analyzeFrame);
    };

    this.stopAudioAnalysis();
    this.analysisFrame = requestAnimationFrame(analyzeFrame);
  }

  stopAudioAnalysis() {
    if (this.analysisFrame) {
      cancelAnimationFrame(this.analysisFrame);
      this.analysisFrame = null;
    }
  }

  stopRecording() {
    this.finishCapture(this.capture);
  }

  densify(value) {
    return Math.exp(-5 * (1 - value));
  }

  async process() {
    const capture = this.capture;
    try {
      // stop() queues one last dataavailable before stop. Await it even though
      // status is already PROCESSING; it can contain all of a short utterance.
      await this.finishCapture(capture);
      if (this.disposed || this.status !== Status.PROCESSING) return;
      if (capture?.error) throw capture.error;
      if (!capture?.chunks.length) throw new Error("The microphone produced no audio. Please try recording again.");
      const audioBlob = new Blob(capture.chunks, {
        type: capture.recorder.mimeType || capture.chunks[0].type,
      });
      const audio = await this.convertBlobToBase64(audioBlob);
      if (this.disposed || this.status !== Status.PROCESSING) return;
      const controller = new AbortController();
      this.transcriptionController = controller;
      const result = await callJsonApi(`/plugins/${PLUGIN_NAME}/transcribe`, {
        audio,
      }, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!result?.success) throw new Error(result?.error || "Transcription failed.");
      const text = this.filterResult(result?.text || "");
      if (text) {
        await this.updateCallback(text, true);
      }
    } catch (error) {
      if (error?.name === "AbortError" || this.transcriptionController?.signal.aborted || this.status === Status.INACTIVE) return;
      console.error("[Whisper STT] Transcription failed", error);
      window.toastFetchError?.("Transcription error", error);
    } finally {
      this.transcriptionController = null;
      if (this.capture === capture) this.capture = null;
      if (this.status === Status.PROCESSING) {
        this.status = Status.LISTENING;
      }
    }
  }

  convertBlobToBase64(audioBlob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const result = String(reader.result || "");
        resolve(result.split(",")[1] || "");
      };
      reader.onerror = (error) => reject(error);
      reader.readAsDataURL(audioBlob);
    });
  }

  filterResult(text) {
    const normalized = String(text || "").trim();
    if (!normalized) return "";

    const wrapped =
      (normalized.startsWith("{") && normalized.endsWith("}")) ||
      (normalized.startsWith("(") && normalized.endsWith(")")) ||
      (normalized.startsWith("[") && normalized.endsWith("]"));

    if (wrapped) {
      return "";
    }

    return normalized;
  }

  async toggle() {
    const hasPermission = await this.requestPermission();
    if (!hasPermission || this.disposed) return;

    if (
      this.status === Status.INACTIVE ||
      this.status === Status.ACTIVATING
    ) {
      this.status = Status.LISTENING;
    } else {
      this.owner.stop();
    }
  }

  async requestPermission() {
    return await this.owner.requestMicrophonePermission();
  }

  dispose() {
    this.disposed = true;
    this.transcriptionController?.abort();
    this.clearCaptureTimers();
    this.stopRecording();
    this.capture?.cancel?.();
    clearTimeout(this.waitingTimer);
    this.waitingTimer = null;
    this.stopAudioAnalysis();

    try {
      this.mediaRecorder?.stream?.getTracks?.().forEach((track) => track.stop());
    } catch (_error) {
      // Ignore media cleanup failures.
    }

    try {
      this.mediaStream?.getTracks?.().forEach((track) => track.stop());
    } catch (_error) {
      // Ignore media cleanup failures.
    }

    try {
      this.audioContext?.close?.();
    } catch (_error) {
      // Ignore audio context cleanup failures.
    }

    this.mediaStream = null;
    this.mediaRecorder = null;
    this.mediaStreamSource = null;
    this.analyserNode = null;
    this.audioContext = null;
    this.capture = null;
  }
}

export const store = createStore("whisperStt", model);
