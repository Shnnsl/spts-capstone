const API_BASE = "http://127.0.0.1:8000";

// -----------------------------
// Line UI
// -----------------------------
async function quickDowntime() {
  const minutes = Number(document.getElementById("minutes").value);
  const reason = document.getElementById("reason_code").value;
  const line = document.getElementById("selectedLine").value;
  const machine = document.getElementById("selectedMachine").value;

  if (!line || !machine) {
    document.getElementById("lineResult").textContent = "Please select a line and machine.";
    return;
  }

  if (!minutes || minutes <= 0) {
    document.getElementById("lineResult").textContent = "Please enter valid downtime minutes.";
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
    const response = await fetch(`${API_BASE}/downtime`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-user": "operator1"
      },
      body: JSON.stringify(data)
    });

    const result = await response.json();
    document.getElementById("lineResult").textContent = JSON.stringify(result, null, 2);
    loadLineUI();
  } catch (error) {
    document.getElementById("lineResult").textContent = String(error);
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
    const response = await fetch(`${API_BASE}/lines/${selectedLine}/summary`, {
      method: "GET",
      headers: { "x-user": "operator1" }
    });

    const data = await response.json();

    totalEventsEl.textContent = data.total_events;
    downtimeEl.textContent = data.total_downtime_minutes;
    pendingEl.textContent = data.pending_events;

    if (data.pending_events > 0) {
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
          <p><strong>Machine:</strong> ${data.latest_event.machine_id}</p>
          <p><strong>Reason:</strong> ${data.latest_event.reason_code}</p>
          <p><strong>Minutes:</strong> ${data.latest_event.minutes}</p>
          <p><strong>Status:</strong> ${data.latest_event.status}</p>
        `;
      } else {
        latestEventBox.innerHTML = "<p>No downtime event recorded yet.</p>";
      }
    }

    const alertsBox = document.getElementById("alertsBox");
    if (alertsBox) {
      alertsBox.innerHTML = data.pending_events > 0
        ? `<p>${data.pending_events} downtime event(s) need supervisor review.</p>`
        : "<p>No active alerts.</p>";
    }

    const lastUpdated = document.getElementById("lastUpdated");
    if (lastUpdated) {
      lastUpdated.textContent = "Last updated: " + new Date().toLocaleTimeString();
    }
  } catch (error) {
    console.error("Line summary error:", error);
  }

  await loadOEEForLine();
}

async function loadOEEForLine() {
  const oeeEl = document.getElementById("oeeDisplay");
  if (!oeeEl) return;

  try {
    const response = await fetch(`${API_BASE}/oee/calculate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-user": "operator1"
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
    const response = await fetch(`${API_BASE}/downtime`, {
      method: "GET",
      headers: { "x-user": "supervisor1" }
    });

    supervisorAllEventsCache = await response.json();
  } catch (error) {
    supervisorAllEventsCache = [];
    console.error("Supervisor all events error:", error);
  }
}

async function loadPendingEvents() {
  try {
    const response = await fetch(`${API_BASE}/downtime/pending`, {
      method: "GET",
      headers: { "x-user": "supervisor1" }
    });

    const events = await response.json();
    supervisorPendingEventsCache = events;

    const pendingCountEl = document.getElementById("supervisorPendingCount");
    const longestPendingEl = document.getElementById("longestPending");

    if (pendingCountEl) pendingCountEl.textContent = events.length;

    if (longestPendingEl) {
      longestPendingEl.textContent = events.length
        ? `${Math.max(...events.map(event => event.minutes))} min`
        : "-- min";
    }

    if (!events.length) {
      const pendingBox = document.getElementById("pendingEvents");
      if (pendingBox) {
        pendingBox.innerHTML =
          "<p style='color:#22c55e;font-weight:bold;'>✔ No pending approvals. All clear.</p>";
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
          <td>${event.event_id}</td>
          <td>${event.line_id}</td>
          <td>${event.machine_id}</td>
          <td>${event.reason_code}</td>
          <td>${event.minutes}</td>
          <td><span class="badge-danger">${event.status}</span></td>
          <td><button class="approve-btn" onclick="approveEvent(${event.event_id})">Approve</button></td>
        </tr>
      `;
    });

    html += "</table>";

    const pendingBox = document.getElementById("pendingEvents");
    if (pendingBox) pendingBox.innerHTML = html;
  } catch (error) {
    const resultBox = document.getElementById("supervisorResult");
    if (resultBox) resultBox.textContent = String(error);
  }
}

async function approveEvent(eventId) {
  try {
    const response = await fetch(`${API_BASE}/downtime/${eventId}/approve`, {
      method: "POST",
      headers: { "x-user": "supervisor1" }
    });

    const result = await response.json();

    const resultBox = document.getElementById("supervisorResult");
    if (resultBox) resultBox.textContent = JSON.stringify(result, null, 2);

    await loadSupervisorDashboard();
  } catch (error) {
    const resultBox = document.getElementById("supervisorResult");
    if (resultBox) resultBox.textContent = String(error);
  }
}

async function loadSupervisorMessages() {
  try {
    const response = await fetch(`${API_BASE}/messages/supervisor`, {
      method: "GET",
      headers: { "x-user": "supervisor1" }
    });

    const messages = await response.json();
    supervisorMessagesCache = messages;

    const messageCountEl = document.getElementById("supervisorMessageCount");
    if (messageCountEl) messageCountEl.textContent = messages.length;

    if (!messages.length) {
      const messageBox = document.getElementById("supervisorMessages");
      if (messageBox) {
        messageBox.innerHTML =
          "<p style='color:#94a3b8;'>No new alerts. System running normally.</p>";
      }
      return;
    }

    let html = "";

    messages.forEach(message => {
      html += `
        <div class="message-card">
          <strong>Event ${message.event_id} · ${message.line_id} · ${message.machine_id}</strong>
          <p>${message.message}</p>
          <p><strong>Minutes:</strong> ${message.minutes}</p>
          <p><strong>Read:</strong> ${message.is_read ? "Yes" : "No"}</p>
        </div>
      `;
    });

    const messageBox = document.getElementById("supervisorMessages");
    if (messageBox) messageBox.innerHTML = html;
  } catch (error) {
    const resultBox = document.getElementById("supervisorResult");
    if (resultBox) resultBox.textContent = String(error);
  }
}

async function loadSupervisorOEE() {
  try {
    const response = await fetch(`${API_BASE}/oee/calculate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-user": "supervisor1"
      },
      body: JSON.stringify({
        planned_production_minutes: 480,
        downtime_minutes: 60,
        ideal_cycle_time: 0.5,
        total_count: 700,
        good_count: 680
      })
    });

    const result = await response.json();

    const oeePercent = result.oee_percent;
    const availabilityPercent = Math.round(result.availability * 100);
    const performancePercent = Math.round(result.performance * 100);
    const qualityPercent = Math.round(result.quality * 100);

    const supervisorOee = document.getElementById("supervisorOee");
    const availabilityValue = document.getElementById("supervisorAvailability");
    const performanceValue = document.getElementById("supervisorPerformance");
    const qualityValue = document.getElementById("supervisorQuality");

    const availabilityBar = document.getElementById("supervisorAvailabilityBar");
    const performanceBar = document.getElementById("supervisorPerformanceBar");
    const qualityBar = document.getElementById("supervisorQualityBar");

    if (supervisorOee) supervisorOee.textContent = `${oeePercent}%`;
    if (availabilityValue) availabilityValue.textContent = `${availabilityPercent}%`;
    if (performanceValue) performanceValue.textContent = `${performancePercent}%`;
    if (qualityValue) qualityValue.textContent = `${qualityPercent}%`;

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
        ${activity}
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
  const lines = ["Line1", "Line2", "Line3"];
  const summaries = [];

  for (const line of lines) {
    try {
      const response = await fetch(`${API_BASE}/lines/${line}/summary`, {
        method: "GET",
        headers: { "x-user": "admin1" }
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

  if (managerDowntime) managerDowntime.textContent = `${totalDowntime} min`;
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
    const response = await fetch(`${API_BASE}/oee/calculate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-user": "admin1"
      },
      body: JSON.stringify({
        planned_production_minutes: 480,
        downtime_minutes: 60,
        ideal_cycle_time: 0.5,
        total_count: 700,
        good_count: 680
      })
    });

    const result = await response.json();

    const managerOee = document.getElementById("managerOee");
    if (managerOee) managerOee.textContent = `${result.oee_percent} %`;

    const availabilityPercent = Math.round(result.availability * 100);
    const performancePercent = Math.round(result.performance * 100);
    const qualityPercent = Math.round(result.quality * 100);

    const availabilityEl = document.getElementById("managerAvailability");
    const performanceEl = document.getElementById("managerPerformance");
    const qualityEl = document.getElementById("managerQuality");

    if (availabilityEl) availabilityEl.textContent = `${availabilityPercent}%`;
    if (performanceEl) performanceEl.textContent = `${performancePercent}%`;
    if (qualityEl) qualityEl.textContent = `${qualityPercent}%`;

    const availabilityBar = document.getElementById("managerAvailabilityBar");
    const performanceBar = document.getElementById("managerPerformanceBar");
    const qualityBar = document.getElementById("managerQualityBar");

    if (availabilityBar) availabilityBar.style.width = `${Math.min(availabilityPercent, 100)}%`;
    if (performanceBar) performanceBar.style.width = `${Math.min(performancePercent, 100)}%`;
    if (qualityBar) qualityBar.style.width = `${Math.min(qualityPercent, 100)}%`;
  } catch (error) {
    const managerOee = document.getElementById("managerOee");
    if (managerOee) managerOee.textContent = "Error";
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
        <td>${line.line_id}</td>
        <td>${line.total_events}</td>
        <td>${line.total_downtime_minutes}</td>
        <td>${line.pending_events}</td>
        <td>${latestReason}</td>
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
        <span>${reason}</span>
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
      <strong class="risk-high">${riskLine.line_id} needs attention.</strong>
      There are ${totalPending} pending downtime approval(s). Management should confirm supervisor review and watch for repeat downtime causes.
    `;
    return;
  }

  if (totalDowntime > 100 && riskLine) {
    insight.innerHTML = `
      <strong class="risk-medium">${riskLine.line_id} should be monitored.</strong>
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
window.addEventListener("load", () => {
  updateMachineOptions();
  loadLineUI();
  updateCurrentTime();

  if (document.getElementById("pendingEvents")) {
    loadSupervisorDashboard();
  }

  if (document.getElementById("lineComparison")) {
    loadManagerDashboard();
  }

  setInterval(loadLineUI, 5000);
  setInterval(updateCurrentTime, 1000);

  if (document.getElementById("pendingEvents")) {
    setInterval(loadSupervisorDashboard, 10000);
  }
});