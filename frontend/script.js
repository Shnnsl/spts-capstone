// -----------------------------
// Line UI
// -----------------------------
function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("en-US", { dateStyle: "long", timeStyle: "short" }).format(date);
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value ?? "—";
  return element.innerHTML;
}

function getFriendlyError(status, detail = "") {
  if (status === 400 && String(detail).toLowerCase().includes("overlap")) {
    return "This downtime overlaps with an existing event for the selected machine.";
  }
  if (status === 409 && String(detail).includes("Trial has not started")) {
    return detail;
  }
  return ({
    400: "The request could not be completed. Please review the information and try again.",
    401: "Your session has expired. Please sign in again.",
    403: "You do not have permission to perform this action.",
    404: "The requested information could not be found.",
    409: "This entry conflicts with an existing record.",
    500: "An unexpected error occurred. Please try again."
  })[status] || "An unexpected error occurred. Please try again.";
}

async function requireSuccessfulResponse(response) {
  if (response.ok) return;
  let detail = "";
  try {
    detail = (await response.json()).detail || "";
  } catch {
    // Intentionally hide technical response details from users.
  }
  throw new Error(getFriendlyError(response.status, detail));
}

function showAlert(element, message, type = "error", details = []) {
  if (!element) return;
  element.replaceChildren();
  element.className = `user-alert ${type}`;
  element.hidden = false;
  const heading = document.createElement("strong");
  heading.textContent = message;
  element.appendChild(heading);
  details.forEach(({ label, value }) => {
    const row = document.createElement("p");
    const labelNode = document.createElement("span");
    const valueNode = document.createElement("b");
    labelNode.textContent = `${label}: `;
    valueNode.textContent = value;
    row.append(labelNode, valueNode);
    element.appendChild(row);
  });
}

function setButtonLoading(button, loading, loadingText = "Working…") {
  if (!button) return;
  if (loading) {
    button.dataset.originalText = button.textContent;
    button.textContent = loadingText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }
}

function renderDashboardIdentity(user) {
  if (!user) return;
  const normalizedRole = normalizeRole(user.role);
  document.querySelectorAll("[data-current-user]").forEach(element => {
    element.textContent = user.full_name || user.username;
    element.title = `Username: ${user.username}`;
  });
  document.querySelectorAll("[data-current-role]").forEach(element => {
    element.textContent = normalizedRole.replaceAll("_", " ");
  });
  const linksByRole = {
    LINE_WORKSTATION: [["Line Dashboard", "line.html"]],
    SUPERVISOR: [["Supervisor Dashboard", "supervisor.html"], ["Line Monitoring", "line.html"]],
    MANAGER: [["Manager Dashboard", "manager.html"], ["Line Dashboard", "line.html"]],
    ADMINISTRATOR: [["Administrator", "admin.html"], ["Line Dashboard", "line.html"], ["Supervisor Dashboard", "supervisor.html"], ["Manager Dashboard", "manager.html"]]
  };
  document.querySelectorAll("[data-role-navigation]").forEach(nav => {
    nav.replaceChildren();
    (linksByRole[normalizedRole] || []).forEach(([label, href]) => {
      const link = document.createElement("a");
      link.href = href;
      link.textContent = label;
      if (window.location.pathname.endsWith(href)) link.setAttribute("aria-current", "page");
      nav.appendChild(link);
    });
  });
  const canOperateTrial = ["SUPERVISOR", "ADMINISTRATOR"].includes(normalizedRole);
  document.querySelectorAll("[data-trial-start], [data-trial-finalize], [data-trial-reset], [data-trial-reject]").forEach(element => {
    element.hidden = !canOperateTrial;
  });
  document.querySelectorAll("[data-trial-simulator]").forEach(element => {
    element.hidden = !canOperateTrial || !window.SPTS_CONFIG?.SIMULATOR_ENABLED;
  });
}

async function quickDowntime() {
  const resultBox = document.getElementById("lineResult");
  const submitButton = document.getElementById("downtimeSubmitButton");
  const minutes = Number(document.getElementById("minutes").value);
  const reason = document.getElementById("reason_code").value;
  const line = document.getElementById("selectedLine").value;
  const machine = document.getElementById("selectedMachine").value;

  if (!line || !machine) {
    showAlert(resultBox, "Please select a line and machine.", "warning");
    return;
  }

  if (!minutes || minutes <= 0) {
    showAlert(resultBox, "Please enter valid downtime minutes.", "warning");
    return;
  }

  const now = new Date();
  const past = new Date(now.getTime() - minutes * 60000);

  const data = {
    line_id: line,
    machine_id: machine,
    reason_code: reason,
    start_time: past.toISOString(),
    end_time: now.toISOString(),
    source: "MANUAL",
    comments: "Line quick entry"
  };

  try {
    setButtonLoading(submitButton, true, "Recording…");
    const response = await authenticatedFetch(`${API_BASE}/downtime`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(data)
    });

    await requireSuccessfulResponse(response);
    const result = await response.json();
    const isApproved = result.status === "Approved";
    showAlert(
      resultBox,
      isApproved ? "Downtime recorded and approved." : "Downtime submitted for supervisor approval.",
      isApproved ? "success" : "warning",
      [
        { label: "Reason", value: result.reason_code || reason },
        { label: "Duration", value: `${result.minutes ?? minutes} minutes` },
        { label: "Status", value: isApproved ? "Approved" : "Pending Approval" }
      ]
    );
    document.getElementById("minutes").value = "";
    await loadLineUI();
  } catch (error) {
    showAlert(resultBox, error.message || getFriendlyError(500), "error");
  } finally {
    setButtonLoading(submitButton, false);
  }
}

function updateMachineOptions() {
  const lineSelect = document.getElementById("selectedLine");
  const machineSelect = document.getElementById("selectedMachine");

  if (!lineSelect || !machineSelect) return;

  const machinesByLine = {
    Line1: ["Packer1", "Mixer1", "Filler1"],
    Line2: ["Packer2", "Mixer2", "Filler2"],
    Line3: ["Packer3", "Mixer3", "Filler3"]
  };

  const selectedLine = lineSelect.value || "Line1";
  const machines = machinesByLine[selectedLine] || machinesByLine.Line1;

  machineSelect.innerHTML = "";

  machines.forEach(machine => {
    const option = document.createElement("option");
    option.value = machine;
    option.textContent = machine;
    machineSelect.appendChild(option);
  });
}

async function loadLineUI() {
  const totalEventsEl = document.getElementById("totalEvents");
  const downtimeEl = document.getElementById("downtime");
  const pendingEl = document.getElementById("pending");
  const statusEl = document.getElementById("lineStatus");
  const oeeEl = document.getElementById("oeeDisplay");

  if (!totalEventsEl || !downtimeEl || !pendingEl || !statusEl || !oeeEl) return;

  const selectedLine = document.getElementById("selectedLine")?.value || "Line1";

  try {
    const response = await authenticatedFetch(`${API_BASE}/lines/${selectedLine}/summary`, {
      method: "GET"
    });

    const data = await response.json();

    totalEventsEl.textContent = data.total_events;
    downtimeEl.textContent = data.total_downtime_minutes;
    pendingEl.textContent = data.pending_events;

    if (document.getElementById("trialInputTubeCount")) {
      // Tabletop status is authoritative for this page's line-status card.
    } else if (data.pending_events > 0) {
      statusEl.innerHTML = `<span class="pulse-dot red-dot"></span> ATTENTION`;
      statusEl.className = "status stopped";
    } else if (data.total_downtime_minutes > 0) {
      statusEl.innerHTML = `<span class="pulse-dot"></span> RUNNING (RECENT STOP)`;
      statusEl.className = "status running";
    } else {
      statusEl.innerHTML = `<span class="pulse-dot"></span> RUNNING`;
      statusEl.className = "status running";
    }

    const latestEventBox = document.getElementById("latestEventBox");
    if (latestEventBox) {
      if (data.latest_event) {
        latestEventBox.innerHTML = `
          <p><strong>Machine:</strong> ${escapeHtml(data.latest_event.machine_id)}</p>
          <p><strong>Reason:</strong> ${escapeHtml(data.latest_event.reason_code)}</p>
          <p><strong>Duration:</strong> ${escapeHtml(data.latest_event.minutes)} minutes</p>
          <p><strong>Status:</strong> <span class="status-badge ${data.latest_event.status === "Approved" ? "approved" : "pending"}">${data.latest_event.status === "Pending" ? "Pending Approval" : escapeHtml(data.latest_event.status)}</span></p>
        `;
      } else {
        latestEventBox.innerHTML = "<p>No downtime event recorded yet.</p>";
      }
    }

    const alertsBox = document.getElementById("alertsBox");
    if (alertsBox) {
      alertsBox.innerHTML = data.pending_events > 0
        ? `<p>${escapeHtml(data.pending_events)} downtime event(s) need supervisor review.</p>`
        : "<p>No active alerts.</p>";
    }

    const lastUpdated = document.getElementById("lastUpdated");
    if (lastUpdated) {
      lastUpdated.textContent = "Last updated: " + new Date().toLocaleTimeString();
    }
  } catch (error) {
    console.error("Line summary error:", error);
  }

  if (!document.getElementById("trialInputTubeCount")) await loadOEEForLine();
}

async function loadOEEForLine() {
  if (document.getElementById("trialInputTubeCount")) return;
  const oeeEl = document.getElementById("oeeDisplay");
  if (!oeeEl) return;

  try {
    const response = await authenticatedFetch(`${API_BASE}/oee/calculate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        planned_production_minutes: 480,
        downtime_minutes: 60,
        ideal_cycle_time: 0.5,
        total_count: 700,
        good_count: 680
      })
    });

    const oee = await response.json();

    oeeEl.textContent = `${oee.oee_percent} %`;

    const progress = document.getElementById("oeeProgress");
    if (progress) progress.style.width = `${Math.min(oee.oee_percent, 100)}%`;

    const availabilityPercent = Math.round(oee.availability * 100);
    const performancePercent = Math.round(oee.performance * 100);
    const qualityPercent = Math.round(oee.quality * 100);

    const availabilityValue = document.getElementById("availabilityValue");
    const performanceValue = document.getElementById("performanceValue");
    const qualityValue = document.getElementById("qualityValue");

    if (availabilityValue) availabilityValue.textContent = `${availabilityPercent}%`;
    if (performanceValue) performanceValue.textContent = `${performancePercent}%`;
    if (qualityValue) qualityValue.textContent = `${qualityPercent}%`;

    const availabilityFill = document.querySelector(".availability-fill");
    const performanceFill = document.querySelector(".performance-fill");
    const qualityFill = document.querySelector(".quality-fill");

    if (availabilityFill) availabilityFill.style.width = `${Math.min(availabilityPercent, 100)}%`;
    if (performanceFill) performanceFill.style.width = `${Math.min(performancePercent, 100)}%`;
    if (qualityFill) qualityFill.style.width = `${Math.min(qualityPercent, 100)}%`;

    if (oee.oee_percent >= 85) {
      oeeEl.style.color = "#22c55e";
    } else if (oee.oee_percent >= 60) {
      oeeEl.style.color = "#eab308";
    } else {
      oeeEl.style.color = "#ef4444";
    }
  } catch (error) {
    console.error("OEE error:", error);
  }
}

function updateCurrentTime() {
  const timeEl = document.getElementById("currentTime");

  if (timeEl) {
    timeEl.textContent = new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    });
  }
}

const TRIAL_EVENTS = {
  INPUT_TUBE: { station: "INPUT", sensor_id: "S1", gpio_pin: 17, event_type: "PRODUCT_DETECTED" },
  FILLER_ACTIVE: { station: "FILLER", sensor_id: "S2", gpio_pin: 27, event_type: "SENSOR_ACTIVE" },
  FILLER_CLEAR: { station: "FILLER", sensor_id: "S2", gpio_pin: 27, event_type: "SENSOR_CLEAR" },
  CARTONER_ACTIVE: { station: "CARTONER", sensor_id: "S3", gpio_pin: 22, event_type: "SENSOR_ACTIVE" },
  CARTONER_CLEAR: { station: "CARTONER", sensor_id: "S3", gpio_pin: 22, event_type: "SENSOR_CLEAR" },
  CASE_PACKER_ACTIVE: { station: "CASE_PACKER", sensor_id: "S4", gpio_pin: 23, event_type: "SENSOR_ACTIVE" },
  CASE_PACKER_CLEAR: { station: "CASE_PACKER", sensor_id: "S4", gpio_pin: 23, event_type: "SENSOR_CLEAR" },
  FINISHED_CASE: { station: "FINISHED_GOODS", sensor_id: "S5", gpio_pin: 24, event_type: "CASE_DETECTED" }
};
const TRIAL_SEQUENCE = Object.values(TRIAL_EVENTS);
const TABLETOP_UI_VERSION = "tube-case-r2";
console.info(`SPTS tabletop UI version: ${TABLETOP_UI_VERSION}`);
// Development input simulation only. These events update SPTS counters through
// the API and never issue conveyor, motor, speed, power, or relay commands.
let trialSimulatorIndex = 0;
let latestTrialOEE = null;
let latestTrialStatus = null;

function getTrialLineId() {
  return window.SPTS_CONFIG?.DEFAULT_LINE_ID || "LINE-01";
}

function renderTrialStatus(data) {
  latestTrialStatus = data;
  const numeric = (value, fallback = 0) => Number(value ?? fallback);
  const reportedLineState = String(data.line_status || "").toUpperCase();
  const tabletopState = data.trial_completed || reportedLineState === "COMPLETED"
    ? "COMPLETED"
    : data.active_downtime || reportedLineState === "DOWNTIME"
      ? "DOWNTIME"
      : data.trial_started || reportedLineState === "RUNNING"
        ? "RUNNING"
        : "READY";
  const affected = data.affected_station?.replaceAll("_", " ");
  const statusLabel = tabletopState === "DOWNTIME" && affected
    ? `DOWNTIME — ${affected}`
    : tabletopState;
  const affectedLabel = affected
    ? affected.toLowerCase().replace(/\b\w/g, letter => letter.toUpperCase())
    : "";
  const stateMessage = {
    READY: "Waiting for trial start",
    RUNNING: "Production monitoring active",
    DOWNTIME: affectedLabel
      ? `Product blockage detected at ${affectedLabel}`
      : "Product blockage detected",
    COMPLETED: "Trial finalized"
  }[tabletopState];
  const values = {
    trialInputTubeCount: numeric(data.input_tube_count),
    trialFinishedCaseCount: numeric(data.finished_case_count),
    trialFinishedTubeEquivalent: numeric(data.finished_tube_equivalent),
    trialUnaccountedTubes: numeric(data.unaccounted_tube_count),
    trialFinalizedWaste: numeric(data.finalized_waste_tube_count),
    trialUnitsPerCase: numeric(data.units_per_case, 12),
    trialDetailInputTubes: numeric(data.input_tube_count),
    trialDetailFinishedCases: numeric(data.finished_case_count),
    trialDetailFinishedEquivalent: numeric(data.finished_tube_equivalent),
    trialDetailFinalizedWaste: numeric(data.finalized_waste_tube_count),
    trialFillerSensor: data.filler_sensor_state === "ACTIVE" ? "BLOCKED" : "CLEAR",
    trialCartonerSensor: data.cartoner_sensor_state === "ACTIVE" ? "BLOCKED" : "CLEAR",
    trialCasePackerSensor: data.case_packer_sensor_state === "ACTIVE" ? "BLOCKED" : "CLEAR",
    trialLineStatus: statusLabel
  };
  Object.entries(values).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  });
  const line = document.getElementById("trialLineId");
  if (line) line.textContent = data.line_id;
  const livePanel = document.getElementById("liveLineStatusPanel");
  if (livePanel) {
    livePanel.classList.remove("is-ready", "is-running", "is-downtime", "is-completed");
    livePanel.classList.add(`is-${tabletopState.toLowerCase()}`);
  }
  const liveMessage = document.getElementById("liveLineMessage");
  if (liveMessage) liveMessage.textContent = stateMessage;
  const liveIndicator = document.getElementById("liveLineIndicator");
  if (liveIndicator) {
    liveIndicator.textContent = {
      READY: "○",
      RUNNING: "●",
      DOWNTIME: "!",
      COMPLETED: "✓"
    }[tabletopState];
  }
  const liveDowntime = document.getElementById("liveLineDowntimeElapsed");
  if (liveDowntime) {
    liveDowntime.hidden = tabletopState !== "DOWNTIME";
    liveDowntime.textContent = `Active downtime ${formatElapsedSeconds(data.elapsed_downtime_seconds || 0)}`;
  }
  const liveFlow = document.getElementById("liveLineFlow");
  if (liveFlow) {
    const affectedDescription = affectedLabel ? ` Affected machine: ${affectedLabel}.` : "";
    liveFlow.setAttribute("aria-label", `Production flow. Current state: ${statusLabel}.${affectedDescription}`);
  }
  document.querySelectorAll("[data-flow-station]").forEach(station => {
    const isAffected = Boolean(data.active_downtime && station.dataset.flowStation === data.affected_station);
    station.classList.toggle("is-affected", isAffected);
  });
  const mainLineStatus = document.getElementById("lineStatus");
  if (mainLineStatus) {
    mainLineStatus.innerHTML = `<span class="pulse-dot"></span> ${escapeHtml(statusLabel)}`;
    mainLineStatus.className = `status ${tabletopState === "DOWNTIME" ? "stopped" : "running"}`;
  }
  const last = document.getElementById("trialLastEvent");
  if (last) {
    last.textContent = data.last_station
      ? `${data.last_station} · ${formatDateTime(data.last_event_time)}`
      : "No events yet";
  }
  const activePanel = document.getElementById("trialActiveDowntime");
  if (activePanel) activePanel.hidden = !data.active_downtime;
  const noActiveDowntime = document.getElementById("trialNoActiveDowntime");
  if (noActiveDowntime) noActiveDowntime.hidden = Boolean(data.active_downtime);
  const downtimeValues = {
    trialDowntimeStation: data.affected_station?.replaceAll("_", " ") || "--",
    trialDowntimeReason: data.downtime_reason || "--",
    trialDowntimeElapsed: formatElapsedSeconds(data.elapsed_downtime_seconds || 0),
    trialDowntimeStartedAt: data.downtime_start_time ? formatDateTime(data.downtime_start_time) : "--",
    trialExpectedStation: data.expected_next_station?.replaceAll("_", " ") || "--"
  };
  Object.entries(downtimeValues).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  });
  document.querySelectorAll("[data-machine-card]").forEach(card => {
    const station = card.dataset.machineCard;
    const isAffected = data.active_downtime && data.affected_station === station;
    card.classList.toggle("is-downtime", Boolean(isAffected));
    const detail = card.querySelector("[data-machine-downtime]");
    if (detail) detail.textContent = isAffected
      ? `DOWNTIME ${formatElapsedSeconds(data.elapsed_downtime_seconds || 0)}`
      : "";
  });
  renderTrialOEE(data.trial_oee || {});
  renderTrialDowntimeHistory(data.recent_downtime_events || []);
}

function formatElapsedSeconds(value) {
  const total = Math.max(Math.floor(Number(value) || 0), 0);
  const hours = String(Math.floor(total / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const seconds = String(total % 60).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

function renderTrialOEE(oee) {
  latestTrialOEE = { ...oee, synchronized_at: Date.now() };
  const percent = value => value == null ? "--" : `${(Number(value) * 100).toFixed(2)}%`;
  const notStarted = oee.status === "NOT_STARTED";
  const invalid = oee.status === "INVALID_SEQUENCE";
  const values = {
    availabilityValue: notStarted ? "0%" : percent(oee.availability),
    performanceValue: notStarted ? "0%" : percent(oee.performance),
    qualityValue: notStarted ? "0%" : percent(oee.quality),
    trialPlannedMinutes: Number(oee.planned_production_minutes || 0).toFixed(2),
    trialRuntimeMinutes: `${Number(oee.runtime_minutes || 0).toFixed(2)} min`,
    trialDetectedDowntime: `${Number(oee.detected_downtime_minutes || 0).toFixed(2)} min`,
    trialIdealCycleDisplay: `${Number(oee.ideal_cycle_time_seconds || 2).toFixed(2)} seconds`,
    trialPotentialUnaccounted: oee.potential_unaccounted ?? 0
  };
  Object.entries(values).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  });
  const rejectInput = document.getElementById("trialRejectCount");
  if (rejectInput && document.activeElement !== rejectInput) {
    rejectInput.value = oee.confirmed_reject_count ?? 0;
  }
  const idealInput = document.getElementById("trialIdealCycleTime");
  if (idealInput && document.activeElement !== idealInput) {
    idealInput.value = oee.ideal_cycle_time_seconds ?? 2;
  }
  const startingInput = document.getElementById("trialStartingInputQuantity");
  if (startingInput && document.activeElement !== startingInput && latestTrialStatus) {
    startingInput.value = latestTrialStatus.starting_input_quantity ?? 50;
  }
  const oeeDisplay = document.getElementById("oeeDisplay");
  const oeeState = document.getElementById("trialOeeState");
  const warning = document.getElementById("trialSequenceWarning");
  if (oeeDisplay) {
    oeeDisplay.textContent = notStarted ? "Not started" : invalid ? "Invalid sequence" : percent(oee.oee);
  }
  if (oeeState) oeeState.textContent = oee.validation_message || "Calculated from the current tabletop run.";
  if (warning) {
    warning.hidden = !invalid;
    warning.textContent = invalid ? oee.validation_message : "";
  }
  const fills = [
    [".availability-fill", oee.availability],
    [".performance-fill", invalid ? 0 : oee.performance],
    [".quality-fill", invalid ? 0 : oee.quality]
  ];
  fills.forEach(([selector, value]) => {
    const fill = document.querySelector(selector);
    if (fill) fill.style.width = `${Math.min(Math.max(Number(value) || 0, 0) * 100, 100)}%`;
  });
  const overallProgress = document.getElementById("oeeProgress");
  if (overallProgress) overallProgress.style.width = `${invalid ? 0 : Math.min((Number(oee.oee) || 0) * 100, 100)}%`;
  updateTrialTimingDisplay();
}

function updateTrialTimingDisplay() {
  const oee = latestTrialOEE;
  if (!oee) return;
  const started = Boolean(oee.is_started && oee.trial_start_time);
  const backendElapsed = Number(oee.planned_production_minutes || 0) * 60;
  const localAdvance = started ? Math.max((Date.now() - oee.synchronized_at) / 1000, 0) : 0;
  const elapsed = backendElapsed + localAdvance;
  const downtime = Number(oee.detected_downtime_minutes || 0) * 60;
  const runtime = Math.max(elapsed - downtime, 0);
  const values = {
    trialStartedAt: started ? formatDateTime(oee.trial_start_time) : "Not started",
    trialElapsedTime: formatElapsedSeconds(elapsed),
    trialPlannedMinutes: (elapsed / 60).toFixed(2),
    trialRuntimeMinutes: `${(runtime / 60).toFixed(2)} min`,
    trialRuntimePrimary: formatElapsedSeconds(runtime)
  };
  Object.entries(values).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  });
}

function renderTrialDowntimeHistory(events) {
  const container = document.getElementById("trialDowntimeHistory");
  if (!container) return;
  if (!events.length) {
    container.innerHTML = "<p>No trial downtime recorded.</p>";
    return;
  }
  container.innerHTML = `<div class="table-responsive"><table class="trial-history-table">
    <thead><tr><th>Station</th><th>Start</th><th>End</th><th>Duration</th><th>Status</th><th>Approval</th></tr></thead>
    <tbody>${events.map(event => `<tr>
      <td>${escapeHtml(event.station?.replaceAll("_", " "))}</td>
      <td>${escapeHtml(formatDateTime(event.start_time))}</td>
      <td>${escapeHtml(event.end_time ? formatDateTime(event.end_time) : "Active")}</td>
      <td>${escapeHtml(formatElapsedSeconds(event.duration_seconds || 0))}</td>
      <td>${escapeHtml(event.status)}</td>
      <td>${escapeHtml(event.approval_state)}</td>
    </tr>`).join("")}</tbody></table></div>`;
}

async function loadTrialStatus() {
  if (!document.getElementById("trialInputTubeCount")) return;
  try {
    const response = await authenticatedFetch(
      `${API_BASE}/plc/trial-status/${encodeURIComponent(getTrialLineId())}`
    );
    await requireSuccessfulResponse(response);
    renderTrialStatus(await response.json());
  } catch (error) {
    console.error("Trial status error:", error);
  }
}

async function simulateNextTrialEvent() {
  const resultBox = document.getElementById("trialResult");
  const button = document.getElementById("simulateTrialButton");
  const mapping = TRIAL_SEQUENCE[trialSimulatorIndex];
  try {
    setButtonLoading(button, true, "Submitting…");
    const response = await authenticatedFetch(`${API_BASE}/plc/production-event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_id: crypto.randomUUID(),
        line_id: getTrialLineId(),
        ...mapping,
        event_time: new Date().toISOString(),
        source: "DEVELOPMENT_SIMULATOR"
      })
    });
    await requireSuccessfulResponse(response);
    const result = await response.json();
    renderTrialStatus(result.status);
    showAlert(resultBox, `${mapping.station} event accepted.`, "success");
    trialSimulatorIndex = (trialSimulatorIndex + 1) % TRIAL_SEQUENCE.length;
  } catch (error) {
    showAlert(resultBox, `Production event failed: ${error.message || getFriendlyError(500)}`, "error");
  } finally {
    setButtonLoading(button, false);
  }
}

async function submitTrialStation(mapping) {
  const response = await authenticatedFetch(`${API_BASE}/plc/production-event`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_id: crypto.randomUUID(), line_id: getTrialLineId(), ...mapping,
      event_time: new Date().toISOString(),
      source: "DEVELOPMENT_SIMULATOR"
    })
  });
  await requireSuccessfulResponse(response);
  const result = await response.json();
  renderTrialStatus(result.status);
  return result;
}

async function simulateTrialEvent(eventName) {
  const mapping = TRIAL_EVENTS[eventName];
  const resultBox = document.getElementById("trialResult");
  try {
    await submitTrialStation(mapping);
    trialSimulatorIndex = (TRIAL_SEQUENCE.indexOf(mapping) + 1) % TRIAL_SEQUENCE.length;
    showAlert(resultBox, `${eventName.replaceAll("_", " ")} accepted.`, "success");
  } catch (error) {
    showAlert(resultBox, `Production event failed: ${error.message || getFriendlyError(500)}`, "error");
  }
}

async function simulateCompleteSequence() {
  const resultBox = document.getElementById("trialResult");
  try {
    for (const mapping of TRIAL_SEQUENCE) await submitTrialStation(mapping);
    trialSimulatorIndex = 0;
    showAlert(resultBox, "Complete product sequence accepted.", "success");
  } catch (error) {
    showAlert(resultBox, `Complete sequence failed: ${error.message || getFriendlyError(500)}`, "error");
  }
}

async function saveTrialConfiguration() {
  const resultBox = document.getElementById("trialResult");
  const count = Number(document.getElementById("trialRejectCount")?.value);
  const idealCycle = Number(document.getElementById("trialIdealCycleTime")?.value);
  const startingInputQuantity = Number(document.getElementById("trialStartingInputQuantity")?.value);
  if (!Number.isInteger(count) || count < 0) {
    showAlert(resultBox, "Confirmed rejects must be a non-negative whole number.", "warning");
    return false;
  }
  if (!Number.isFinite(idealCycle) || idealCycle <= 0) {
    showAlert(resultBox, "Ideal cycle time must be greater than zero seconds.", "warning");
    return false;
  }
  if (!Number.isInteger(startingInputQuantity) || startingInputQuantity <= 0) {
    showAlert(resultBox, "Starting input quantity must be a positive whole number.", "warning");
    return false;
  }
  try {
    const response = await authenticatedFetch(
      `${API_BASE}/plc/trial-config/${encodeURIComponent(getTrialLineId())}`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmed_reject_count: count, ideal_cycle_time_seconds: idealCycle, starting_input_quantity: startingInputQuantity }) }
    );
    await requireSuccessfulResponse(response);
    renderTrialStatus(await response.json());
    showAlert(resultBox, "Trial configuration saved.", "success");
    return true;
  } catch (error) {
    showAlert(resultBox, `Save OEE inputs failed: ${error.message || getFriendlyError(500)}`, "error");
    return false;
  }
}

async function startTabletopTrial() {
  const resultBox = document.getElementById("trialResult");
  const button = document.querySelector("[data-trial-start]");
  try {
    if (!await saveTrialConfiguration()) return;
    setButtonLoading(button, true, "Starting…");
    const response = await authenticatedFetch(
      `${API_BASE}/plc/trial-start/${encodeURIComponent(getTrialLineId())}`,
      { method: "POST" }
    );
    await requireSuccessfulResponse(response);
    renderTrialStatus(await response.json());
    showAlert(resultBox, "Tabletop trial run started. Conveyor control remains manual.", "success");
  } catch (error) {
    showAlert(resultBox, `Start trial failed: ${error.message || getFriendlyError(500)}`, "error");
  } finally {
    setButtonLoading(button, false);
  }
}

async function finalizeTabletopTrial() {
  const resultBox = document.getElementById("trialResult");
  const button = document.querySelector("[data-trial-finalize]");
  try {
    setButtonLoading(button, true, "Finalizing…");
    const response = await authenticatedFetch(
      `${API_BASE}/plc/trial-finalize/${encodeURIComponent(getTrialLineId())}`,
      { method: "POST" }
    );
    await requireSuccessfulResponse(response);
    renderTrialStatus(await response.json());
    showAlert(resultBox, "Trial finalized in SPTS. No conveyor command was issued.", "success");
  } catch (error) {
    showAlert(resultBox, `Finalize trial failed: ${error.message || getFriendlyError(500)}`, "error");
  } finally {
    setButtonLoading(button, false);
  }
}

async function resetTabletopTrial() {
  const resultBox = document.getElementById("trialResult");
  try {
    const response = await authenticatedFetch(
      `${API_BASE}/plc/trial-reset/${encodeURIComponent(getTrialLineId())}`,
      { method: "POST" }
    );
    await requireSuccessfulResponse(response);
    renderTrialStatus(await response.json());
    trialSimulatorIndex = 0;
    showAlert(resultBox, "Tabletop trial data reset.", "success");
  } catch (error) {
    showAlert(resultBox, `Reset trial failed: ${error.message || getFriendlyError(500)}`, "error");
  }
}

// -----------------------------
// Supervisor Dashboard
// -----------------------------
let supervisorPendingEventsCache = [];
let supervisorMessagesCache = [];
let supervisorAllEventsCache = [];

async function loadSupervisorDashboard() {
  await loadSupervisorAllEvents();
  await loadPendingEvents();
  await loadSupervisorMessages();
  await loadSupervisorOEE();
  loadSupervisorActivityFeed();
  updateSupervisorKPIs();
}

async function loadSupervisorAllEvents() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/downtime`, {
      method: "GET"
    });

    supervisorAllEventsCache = await response.json();
  } catch (error) {
    supervisorAllEventsCache = [];
    console.error("Supervisor all events error:", error);
  }
}

async function loadPendingEvents() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/downtime/pending`, {
      method: "GET"
    });
    await requireSuccessfulResponse(response);
    const events = await response.json();
    supervisorPendingEventsCache = events;

    const pendingCountEl = document.getElementById("supervisorPendingCount");
    const longestPendingEl = document.getElementById("longestPending");

    if (pendingCountEl) pendingCountEl.textContent = events.length;

    if (longestPendingEl) {
      longestPendingEl.textContent = events.length
        ? `${Math.max(...events.map(event => event.minutes))} min`
        : "—";
    }

    if (!events.length) {
      const pendingBox = document.getElementById("pendingEvents");
      if (pendingBox) {
        pendingBox.innerHTML = "<p class='empty-state'>No pending downtime events.</p>";
      }
      return;
    }

    let html = `
      <table class="supervisor-table">
        <tr>
          <th>Event ID</th>
          <th>Line</th>
          <th>Machine</th>
          <th>Reason</th>
          <th>Minutes</th>
          <th>Status</th>
          <th>Action</th>
        </tr>
    `;

    events.forEach(event => {
      html += `
        <tr>
          <td>${escapeHtml(event.event_id)}</td>
          <td>${escapeHtml(event.line_id)}</td>
          <td>${escapeHtml(event.machine_id)}</td>
          <td>${escapeHtml(event.reason_code)}</td>
          <td>${escapeHtml(event.minutes)} min</td>
          <td><span class="status-badge pending">Pending Approval</span></td>
          <td><button class="approve-btn" onclick="approveEvent(${event.event_id})">Approve</button></td>
        </tr>
      `;
    });

    html += "</table>";

    const pendingBox = document.getElementById("pendingEvents");
    if (pendingBox) pendingBox.innerHTML = html;
  } catch (error) {
    const resultBox = document.getElementById("supervisorResult");
    showAlert(resultBox, error.message || getFriendlyError(500), "error");
  }
}

async function approveEvent(eventId) {
  const resultBox = document.getElementById("supervisorResult");
  const button = document.querySelector(`button[onclick="approveEvent(${eventId})"]`);
  try {
    setButtonLoading(button, true, "Approving…");
    const response = await authenticatedFetch(`${API_BASE}/downtime/${eventId}/approve`, {
      method: "POST"
    });

    await requireSuccessfulResponse(response);
    await response.json();
    showAlert(resultBox, "Downtime event approved.", "success", [
      { label: "Event", value: `#${eventId}` },
      { label: "Status", value: "Approved" }
    ]);

    await loadSupervisorDashboard();
  } catch (error) {
    showAlert(resultBox, error.message || getFriendlyError(500), "error");
  } finally {
    setButtonLoading(button, false);
  }
}

async function loadSupervisorMessages() {
  try {
    const response = await authenticatedFetch(`${API_BASE}/messages/supervisor`, {
      method: "GET"
    });

    const messages = await response.json();
    supervisorMessagesCache = messages;

    const messageCountEl = document.getElementById("supervisorMessageCount");
    if (messageCountEl) messageCountEl.textContent = messages.length;

    if (!messages.length) {
      const messageBox = document.getElementById("supervisorMessages");
      if (messageBox) {
        messageBox.innerHTML = "<p class='empty-state'>No supervisor messages.</p>";
      }
      return;
    }

    let html = "";

    messages.forEach(message => {
      html += `
        <div class="message-card">
          <strong>Event ${escapeHtml(message.event_id)} · ${escapeHtml(message.line_id)} · ${escapeHtml(message.machine_id)}</strong>
          <p>${escapeHtml(message.message)}</p>
          <p><strong>Duration:</strong> ${escapeHtml(message.minutes)} minutes</p>
          <p><strong>Read:</strong> ${message.is_read ? "Yes" : "No"}</p>
          <p><strong>Received:</strong> ${escapeHtml(formatDateTime(message.created_at))}</p>
        </div>
      `;
    });

    const messageBox = document.getElementById("supervisorMessages");
    if (messageBox) messageBox.innerHTML = html;
  } catch (error) {
    const resultBox = document.getElementById("supervisorResult");
    showAlert(resultBox, error.message || getFriendlyError(500), "error");
  }
}

async function loadSupervisorOEE() {
  try {
    const selectedLine = document.getElementById("supervisorLineFilter")?.value;
    const tabletopLine = !selectedLine || selectedLine === "all"
      ? getTrialLineId()
      : selectedLine;
    const response = await authenticatedFetch(
      `${API_BASE}/supervisor/summary?line_id=${encodeURIComponent(tabletopLine)}`,
      { method: "GET" }
    );
    await requireSuccessfulResponse(response);

    const result = await response.json();
    const tabletop = result.tabletop || {};

    const oeePercent = Number(tabletop.overall_oee_percent || 0);
    const availabilityPercent = Number(tabletop.availability_percent || 0);
    const performancePercent = Number(tabletop.performance_percent || 0);
    const qualityPercent = Number(tabletop.quality_percent || 0);
    const wastePercent = Number(tabletop.waste_percent || 0);

    const supervisorOee = document.getElementById("supervisorOee");
    const availabilityValue = document.getElementById("supervisorAvailability");
    const performanceValue = document.getElementById("supervisorPerformance");
    const qualityValue = document.getElementById("supervisorQuality");
    const wasteValue = document.getElementById("supervisorWaste");

    const availabilityBar = document.getElementById("supervisorAvailabilityBar");
    const performanceBar = document.getElementById("supervisorPerformanceBar");
    const qualityBar = document.getElementById("supervisorQualityBar");

    if (supervisorOee) supervisorOee.textContent = `${oeePercent.toFixed(2)}%`;
    if (availabilityValue) availabilityValue.textContent = `${availabilityPercent.toFixed(2)}%`;
    if (performanceValue) performanceValue.textContent = `${performancePercent.toFixed(2)}%`;
    if (qualityValue) qualityValue.textContent = `${qualityPercent.toFixed(2)}%`;
    if (wasteValue) wasteValue.textContent = `${wastePercent.toFixed(2)}%`;

    if (availabilityBar) availabilityBar.style.width = `${Math.min(availabilityPercent, 100)}%`;
    if (performanceBar) performanceBar.style.width = `${Math.min(performancePercent, 100)}%`;
    if (qualityBar) qualityBar.style.width = `${Math.min(qualityPercent, 100)}%`;

    if (supervisorOee) {
      if (oeePercent >= 85) {
        supervisorOee.style.color = "#22c55e";
      } else if (oeePercent >= 60) {
        supervisorOee.style.color = "#f59e0b";
      } else {
        supervisorOee.style.color = "#ef4444";
      }
    }
  } catch (error) {
    console.error("Supervisor OEE error:", error);
  }
}

function loadSupervisorActivityFeed() {
  const activityFeed = document.getElementById("supervisorActivityFeed");
  if (!activityFeed) return;

  const activities = [];

  supervisorPendingEventsCache.slice(0, 3).forEach(event => {
    activities.push(
      `PLC/Line event ${event.event_id} from ${event.machine_id} is waiting for supervisor approval.`
    );
  });

  const recentlyApproved = supervisorAllEventsCache
    .filter(event => event.status === "Approved")
    .slice(-2);

  recentlyApproved.forEach(event => {
    activities.push(
      `Event ${event.event_id} on ${event.line_id} was approved and synchronized with reporting.`
    );
  });

  if (!activities.length) {
    activities.push("System waiting for new downtime events.");
    activities.push("Supervisor workflow is synchronized with current dashboard data.");
  }

  let html = "";

  activities.forEach(activity => {
    html += `
      <div class="activity-item">
        ${escapeHtml(activity)}
      </div>
    `;
  });

  activityFeed.innerHTML = html;
}

function updateSupervisorKPIs() {
  const openDowntimeEl = document.getElementById("openDowntimeMinutes");
  const avgApprovalEl = document.getElementById("avgApprovalTime");
  const waitingOverThirtyEl = document.getElementById("waitingOverThirty");
  const approvedEventsEl = document.getElementById("approvedTodayCount");

  const openDowntimeMinutes = supervisorPendingEventsCache.reduce(
    (sum, event) => sum + (event.minutes || 0),
    0
  );

  const waitingOverThirty = supervisorPendingEventsCache.filter(
    event => (event.minutes || 0) > 30
  ).length;

  const approvedEvents = supervisorAllEventsCache.filter(
    event => event.status === "Approved"
  );

  const approvedWithTimes = approvedEvents.filter(
    event => event.created_at && event.approved_at
  );

  let avgApprovalMinutes = null;

  if (approvedWithTimes.length) {
    const totalApprovalMinutes = approvedWithTimes.reduce((sum, event) => {
      const createdAt = new Date(event.created_at);
      const approvedAt = new Date(event.approved_at);
      const diffMinutes = (approvedAt - createdAt) / 60000;
      return sum + Math.max(diffMinutes, 0);
    }, 0);

    avgApprovalMinutes = totalApprovalMinutes / approvedWithTimes.length;
  }

  if (openDowntimeEl) {
    openDowntimeEl.textContent = `${Math.round(openDowntimeMinutes)} min`;
  }

  if (waitingOverThirtyEl) {
    waitingOverThirtyEl.textContent = waitingOverThirty;
  }

  if (approvedEventsEl) {
    approvedEventsEl.textContent = approvedEvents.length;
  }

  if (avgApprovalEl) {
    avgApprovalEl.textContent = avgApprovalMinutes === null
      ? "-- min"
      : `${avgApprovalMinutes.toFixed(1)} min`;
  }
}

// -----------------------------
// Manager Dashboard
// -----------------------------
async function loadManagerDashboard() {
  const lines = [getTrialLineId(), "Line1", "Line2", "Line3"];
  const summaries = [];

  for (const line of lines) {
    try {
      const response = await authenticatedFetch(`${API_BASE}/lines/${line}/summary`, {
        method: "GET"
      });

      const data = await response.json();
      summaries.push(data);
    } catch (error) {
      console.error(`Error loading ${line}:`, error);
    }
  }

  const totalDowntime = summaries.reduce((sum, line) => sum + (line.total_downtime_minutes || 0), 0);
  const totalPending = summaries.reduce((sum, line) => sum + (line.pending_events || 0), 0);
  const totalEvents = summaries.reduce((sum, line) => sum + (line.total_events || 0), 0);

  const managerDowntime = document.getElementById("managerDowntime");
  const managerPending = document.getElementById("managerPending");
  const riskLineEl = document.getElementById("riskLine");

  if (managerDowntime) managerDowntime.textContent = `${totalDowntime.toFixed(1)} min`;
  if (managerPending) managerPending.textContent = totalPending;

  const riskLine = getHighestRiskLine(summaries);
  if (riskLineEl) riskLineEl.textContent = riskLine ? riskLine.line_id : "--";

  await loadManagerOEE();
  renderLineComparison(summaries);
  renderReasonSummary(summaries);
  renderManagerInsight(summaries, totalPending, totalDowntime, totalEvents, riskLine);
}

async function loadManagerOEE() {
  try {
    const response = await authenticatedFetch(
      `${API_BASE}/manager/summary?line_id=${encodeURIComponent(getTrialLineId())}`,
      { method: "GET" }
    );
    await requireSuccessfulResponse(response);

    const result = await response.json();

    const managerOee = document.getElementById("managerOee");
    if (managerOee) managerOee.textContent = `${Number(result.overall_oee || 0).toFixed(2)}%`;

    const availabilityPercent = Number(result.availability || 0);
    const performancePercent = Number(result.performance || 0);
    const qualityPercent = Number(result.quality || 0);
    const wastePercent = Number(result.waste_percent || 0);

    const availabilityEl = document.getElementById("managerAvailability");
    const performanceEl = document.getElementById("managerPerformance");
    const qualityEl = document.getElementById("managerQuality");
    const wasteEl = document.getElementById("managerWaste");

    if (availabilityEl) availabilityEl.textContent = `${availabilityPercent.toFixed(2)}%`;
    if (performanceEl) performanceEl.textContent = `${performancePercent.toFixed(2)}%`;
    if (qualityEl) qualityEl.textContent = `${qualityPercent.toFixed(2)}%`;
    if (wasteEl) wasteEl.textContent = `${wastePercent.toFixed(2)}%`;

    const availabilityBar = document.getElementById("managerAvailabilityBar");
    const performanceBar = document.getElementById("managerPerformanceBar");
    const qualityBar = document.getElementById("managerQualityBar");

    if (availabilityBar) availabilityBar.style.width = `${Math.min(availabilityPercent, 100)}%`;
    if (performanceBar) performanceBar.style.width = `${Math.min(performancePercent, 100)}%`;
    if (qualityBar) qualityBar.style.width = `${Math.min(qualityPercent, 100)}%`;
  } catch (error) {
    const managerOee = document.getElementById("managerOee");
    if (managerOee) managerOee.textContent = "—";
  }
}

function getHighestRiskLine(summaries) {
  if (!summaries.length) return null;

  return summaries.reduce((highest, current) => {
    const currentScore = (current.total_downtime_minutes || 0) + ((current.pending_events || 0) * 50);
    const highestScore = (highest.total_downtime_minutes || 0) + ((highest.pending_events || 0) * 50);

    return currentScore > highestScore ? current : highest;
  });
}

function renderLineComparison(summaries) {
  const lineComparison = document.getElementById("lineComparison");
  if (!lineComparison) return;

  if (!summaries.length) {
    lineComparison.innerHTML = "<p class='empty-state'>No production data is available for the selected period.</p>";
    return;
  }

  let html = `
    <table class="manager-table">
      <tr>
        <th>Line</th>
        <th>Total Events</th>
        <th>Downtime Minutes</th>
        <th>Pending Approvals</th>
        <th>Latest Reason</th>
        <th>Status</th>
      </tr>
  `;

  summaries.forEach(line => {
    let badgeClass = "badge-good";
    let statusText = "Stable";

    if (line.pending_events > 0) {
      badgeClass = "badge-danger";
      statusText = "Needs Review";
    } else if (line.total_downtime_minutes > 0) {
      badgeClass = "badge-warning";
      statusText = "Monitor";
    }

    const latestReason = line.latest_event ? line.latest_event.reason_code : "None";

    html += `
      <tr>
        <td>${escapeHtml(line.line_id)}</td>
        <td>${escapeHtml(line.total_events)}</td>
        <td>${escapeHtml(line.total_downtime_minutes)} min</td>
        <td>${escapeHtml(line.pending_events)}</td>
        <td>${escapeHtml(latestReason)}</td>
        <td><span class="${badgeClass}">${statusText}</span></td>
      </tr>
    `;
  });

  html += "</table>";
  lineComparison.innerHTML = html;
}

function renderReasonSummary(summaries) {
  const reasonSummary = document.getElementById("reasonSummary");
  if (!reasonSummary) return;

  const reasons = {};

  summaries.forEach(line => {
    if (line.latest_event && line.latest_event.reason_code) {
      const reason = line.latest_event.reason_code;
      reasons[reason] = (reasons[reason] || 0) + 1;
    }
  });

  if (Object.keys(reasons).length === 0) {
    reasonSummary.innerHTML = "<p>No downtime reasons available yet.</p>";
    return;
  }

  let html = `<div class="reason-grid">`;

  Object.entries(reasons).forEach(([reason, count]) => {
    html += `
      <div class="reason-card">
        <span>${escapeHtml(reason)}</span>
        <strong>${count}</strong>
        <p>latest recorded occurrence(s)</p>
      </div>
    `;
  });

  html += "</div>";
  reasonSummary.innerHTML = html;
}

function renderManagerInsight(summaries, totalPending, totalDowntime, totalEvents, riskLine) {
  const insight = document.getElementById("managerInsight");
  if (!insight) return;

  if (!totalEvents) {
    insight.textContent =
      "No production downtime data has been recorded yet. Once line activity is captured, this dashboard will show performance and risk patterns.";
    return;
  }

  if (totalPending > 0 && riskLine) {
    insight.innerHTML = `
      <strong class="risk-high">${escapeHtml(riskLine.line_id)} needs attention.</strong>
      There are ${totalPending} pending downtime approval(s). Management should confirm supervisor review and watch for repeat downtime causes.
    `;
    return;
  }

  if (totalDowntime > 100 && riskLine) {
    insight.innerHTML = `
      <strong class="risk-medium">${escapeHtml(riskLine.line_id)} should be monitored.</strong>
      Total downtime is above the expected range. Review the latest downtime reason and compare line performance before the next shift review.
    `;
    return;
  }

  insight.innerHTML = `
    <strong class="risk-low">Operations appear stable.</strong>
    Downtime and approvals are currently under control based on the available line data.
  `;
}

// -----------------------------
// Auto Load
// -----------------------------
window.addEventListener("load", async () => {
  if (window.sptsAuthReady) {
    const authenticatedUser = await window.sptsAuthReady;
    if (!authenticatedUser) return;
    renderDashboardIdentity(authenticatedUser);
  }

  updateMachineOptions();
  loadLineUI();
  loadTrialStatus();
  updateCurrentTime();

  if (document.getElementById("pendingEvents")) {
    loadSupervisorDashboard();
  }

  if (document.getElementById("lineComparison")) {
    loadManagerDashboard();
  }

  setInterval(loadLineUI, 5000);
  setInterval(loadTrialStatus, 5000);
  setInterval(updateCurrentTime, 1000);
  setInterval(updateTrialTimingDisplay, 1000);

  if (document.getElementById("pendingEvents")) {
    setInterval(loadSupervisorDashboard, 10000);
  }
  if (document.getElementById("lineComparison")) {
    setInterval(loadManagerDashboard, 10000);
  }
});
