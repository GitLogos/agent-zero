import { createStore } from "/js/AlpineStore.js";
import { toastFrontendError } from "/components/notifications/notification-store.js";
import { callJsonApi } from "/js/api.js";
import { ttsService } from "/js/tts-service.js";

const PLUGIN_NAME = "_kokoro_tts";

const model = {
  runtimeInitialized: false,
  statusLoaded: false,
  loading: false,
  error: "",
  enabled: false,
  config: {
    backend: "local",
    external_model: "",
    external_voice: "",
    voice: "",
    voice_weights: {},
    speed: 1.1,
  },
  modelReady: false,
  localAvailable: true,
  modelLoading: false,
  packageVersion: "",
  providerCleanup: null,

  async initRuntime() {
    if (this.runtimeInitialized) return;
    this.runtimeInitialized = true;
    await this.refreshStatus({ suppressError: true });
  },

  async ensureStatusLoaded() {
    if (this.statusLoaded || this.loading) return;
    await this.refreshStatus({ suppressError: true });
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
        external_voice: status?.config?.external_voice || "",
        voice: status?.config?.voice || "",
        voice_weights: status?.config?.voice_weights || {},
        speed: Number(status?.config?.speed || 1.1),
      };
      this.modelReady = !!status?.model?.ready;
      this.localAvailable = status?.local_available !== false;
      this.modelLoading = !!status?.model?.loading;
      this.packageVersion = status?.package?.version || "";
      this.error = status?.configuration_error || "";

      if (this.enabled) {
        this.registerProvider();
      } else {
        this.unregisterProvider();
      }
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
      if (this.config.backend === "local") this.unregisterProvider();
      if (!suppressError) {
        void toastFrontendError(this.error, "Kokoro TTS");
      }
    } finally {
      this.loading = false;
    }
  },

  registerProvider() {
    if (this.providerCleanup || !this.enabled) return;

    this.providerCleanup = ttsService.registerProvider(PLUGIN_NAME, {
      allowBrowserFallback: () => this.config.backend === "local" && this.localAvailable,
      synthesize: async (text, { signal } = {}) => {
        const result = await callJsonApi(`/plugins/${PLUGIN_NAME}/synthesize`, {
          text,
        }, { signal });
        if (!result?.success) {
          const error = new Error(result?.error || "Kokoro TTS synthesis failed.");
          error.allowBrowserFallback = result?.allow_browser_fallback ?? (result?.backend === "local" && this.localAvailable);
          throw error;
        }

        return {
          audioBase64: result.audio || "",
          mimeType: result.mime_type || "audio/wav",
        };
      },
    });
  },

  unregisterProvider() {
    if (!this.providerCleanup) return;
    this.providerCleanup();
    this.providerCleanup = null;
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

  get voiceSummary() {
    if (this.config.backend === "openai") return this.config.external_voice || "";
    const entries = Object.entries(this.config.voice_weights || {});
    if (!entries.length) return this.config.voice || "";

    const total = entries.reduce((sum, [, weight]) => sum + Number(weight || 0), 0);
    if (total <= 0) return this.config.voice || "";
    return entries
      .map(([voice, weight]) => `${voice} ${Math.round((Number(weight) / total) * 100)}%`)
      .join(" · ");
  },

  get backendSummary() {
    return this.config.backend === "local" ? "Local Kokoro" : "External OpenAI-compatible";
  },

  async openConfig() {
    const { store } = await import("/components/plugins/plugin-settings-store.js");
    await store.openConfig(PLUGIN_NAME);
    await this.refreshStatus();
  },

  openPanel() {
    window.openModal?.(`/plugins/${PLUGIN_NAME}/webui/main.html`);
  },
};

export const store = createStore("kokoroTts", model);
