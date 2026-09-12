(() => {
  "use strict";

  const PLUGIN_ID = "openhop.meshzork";
  const API = "/api/plugins/settings";
  const defaults = {
    meshcore_host: "127.0.0.1",
    meshcore_port: 5002,
    max_reply_bytes: 145,
    max_command_bytes: 160,
    duplicate_ttl_seconds: 600,
    auto_page_limit: 4,
    page_delay_seconds: 2.0,
    max_active_players: 3,
    active_player_timeout_seconds: 900,
    busy_notice_ttl_seconds: 300,
    save_retention_days: 30,
    frotz_path: "/usr/games/dfrotz",
    story_path: "",
    random_seed: 117,
    log_level: "INFO"
  };

  const $ = (id) => document.getElementById(id);
  let currentConfig = { ...defaults };
  let formDirty = false;

  function setNotice(message, kind = "") {
    const notice = $("notice");
    notice.textContent = message || "";
    notice.className = `notice ${kind}`.trim();
  }

  function setStatus(label, kind = "neutral") {
    const status = $("global-status");
    status.className = `status-pill ${kind}`;
    status.replaceChildren();
    const dot = document.createElement("span");
    dot.className = "status-dot";
    status.append(dot, document.createTextNode(label));
  }

  function repeaterJwt() {
    try {
      return window.localStorage.getItem("pymc_jwt_token") || "";
    } catch (_) {
      return "";
    }
  }

  async function apiFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    const token = repeaterJwt();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(url, { ...options, headers });
    if (response.status === 401) {
      throw new Error(
        token
          ? "Your openHop dashboard session expired. Sign in again and reopen MeshZork."
          : "Open MeshZork from the signed-in openHop dashboard."
      );
    }
    return response;
  }

  function configFromResponse(payload) {
    if (payload && typeof payload === "object" && payload.config && typeof payload.config === "object") {
      return payload.config;
    }
    return payload && typeof payload === "object" ? payload : {};
  }

  function cleanConfig(config) {
    const clean = {};
    Object.keys(defaults).forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(config, key)) clean[key] = config[key];
    });
    return clean;
  }

  function plural(value, unit) {
    return `${value} ${unit}${value === 1 ? "" : "s"}`;
  }

  function renderOverview(config) {
    const timeoutMinutes = Math.max(1, Math.round(config.active_player_timeout_seconds / 60));
    $("overview-players").textContent = String(config.max_active_players);
    $("overview-timeout").textContent = plural(timeoutMinutes, "minute");
    $("overview-retention").textContent = plural(config.save_retention_days, "day");
  }

  function populateSettings(config) {
    const cfg = { ...defaults, ...cleanConfig(config) };
    $("max_active_players").value = String(cfg.max_active_players);
    $("active_player_timeout_minutes").value = String(
      Math.max(1, Math.round(cfg.active_player_timeout_seconds / 60))
    );
    $("save_retention_days").value = String(cfg.save_retention_days);
    currentConfig = cfg;
    formDirty = false;
    renderOverview(cfg);
  }

  function integerValue(id, label, minimum, maximum) {
    const value = Number($(id).value.trim());
    if (!Number.isInteger(value) || value < minimum || value > maximum) {
      throw new Error(`${label} must be a whole number from ${minimum} to ${maximum}.`);
    }
    return value;
  }

  function buildConfig() {
    const players = integerValue("max_active_players", "Maximum active players", 1, 20);
    const timeoutMinutes = integerValue(
      "active_player_timeout_minutes", "Inactivity timeout", 1, 1440
    );
    const retentionDays = integerValue("save_retention_days", "Save retention", 1, 3650);
    return {
      ...defaults,
      ...cleanConfig(currentConfig),
      max_active_players: players,
      active_player_timeout_seconds: timeoutMinutes * 60,
      save_retention_days: retentionDays
    };
  }

  async function fetchConfig() {
    const response = await apiFetch(`${API}?id=${encodeURIComponent(PLUGIN_ID)}`);
    if (!response.ok) throw new Error(`Settings could not be loaded (HTTP ${response.status}).`);
    return configFromResponse(await response.json());
  }

  async function loadConfig(force = false) {
    try {
      setStatus("Loading", "neutral");
      const config = await fetchConfig();
      if (force || !formDirty) populateSettings(config);
      setStatus("Ready", "good");
      if ($("notice").classList.contains("error")) setNotice("");
    } catch (error) {
      setStatus("Error", "bad");
      setNotice(error instanceof Error ? error.message : String(error), "error");
    }
  }

  ["max_active_players", "active_player_timeout_minutes", "save_retention_days"].forEach((id) => {
    $(id).addEventListener("input", () => {
      formDirty = true;
      setStatus("Unsaved changes", "warn");
    });
  });

  $("reload-settings").addEventListener("click", () => {
    formDirty = false;
    setNotice("");
    loadConfig(true);
  });

  $("settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("save-settings");
    try {
      const config = buildConfig();
      button.disabled = true;
      setStatus("Saving", "neutral");
      setNotice("Saving settings and restarting MeshZork...");
      const response = await apiFetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: PLUGIN_ID, config, restart: true })
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Save failed (HTTP ${response.status})${text ? `: ${text}` : ""}`);
      }
      populateSettings(config);
      setStatus("Saved", "good");
      setNotice("Saved. MeshZork is restarting with the new limits.", "ok");
      setTimeout(() => loadConfig(true).catch(() => {}), 2000);
    } catch (error) {
      setStatus("Error", "bad");
      setNotice(error instanceof Error ? error.message : String(error), "error");
    } finally {
      button.disabled = false;
    }
  });

  loadConfig(true);
})();
