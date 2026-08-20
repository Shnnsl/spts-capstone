window.SPTS_CONFIG = Object.freeze({
  API_BASE_URL: window.localStorage.getItem("spts_api_base_url") ||
    (window.location.protocol === "file:"
      ? "http://127.0.0.1:8000"
      : `${window.location.protocol}//${window.location.hostname}:8000`),
  DEFAULT_LINE_ID: window.localStorage.getItem("spts_trial_line_id") || "LINE-01",
  SIMULATOR_ENABLED: window.localStorage.getItem("spts_simulator_enabled") !== "false"
});
