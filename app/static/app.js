const form = document.querySelector("#scan-form");
const dynamicVerification = document.querySelector("#dynamic-verification");
const activeWarning = document.querySelector("#active-warning");
const submitButton = document.querySelector("#submit-button");
const statusCard = document.querySelector("#status-card");
const statusLabel = document.querySelector("#status-label");
const progressLabel = document.querySelector("#progress-label");
const progressBar = document.querySelector("#progress-bar");
const stageLabel = document.querySelector("#stage-label");
const results = document.querySelector("#results");

dynamicVerification.addEventListener("change", () => {
  activeWarning.classList.toggle("hidden", !dynamicVerification.checked);
});

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[character]));
}

function percentage(value) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function stateLabel(value) {
  return {
    queued: "QUEUED",
    started: "RUNNING",
    finished: "COMPLETE",
    failed: "FAILED",
    stopped: "STOPPED",
    canceled: "CANCELED",
  }[value] || String(value || "UNKNOWN").toUpperCase();
}

function renderResults(data) {
  const summary = data.summary;
  const pages = data.pages || [];
  const zapAlerts = data.zap?.alerts || [];
  const zapWarnings = data.zap?.warnings || [];
  const zapError = data.zap?.status === "failed" ? data.zap.error : "";

  const pageCards = pages.map((page) => {
    const ml = page.ml || {};
    const scored = ml.status === "scored";
    const riskClass = scored ? (ml.vulnerable ? "risk-high" : "risk-low") : "risk-unknown";
    const score = scored
      ? `SCORE ${percentage(ml.risk_score)}`
      : (ml.status === "insufficient_feature_coverage"
        ? "LOW COVERAGE"
        : "NOT SCORED");
    const decision = scored
      ? (ml.vulnerable ? "HIGH PRIORITY" : "LOW PRIORITY")
      : "NO ML DECISION";
    const collectionStatus = page.collection_status || "complete";
    const collectionBadge = collectionStatus === "partial"
      ? '<span class="collection-pill collection-partial">PARTIAL</span>'
      : (collectionStatus === "failed"
        ? '<span class="collection-pill collection-failed">COLLECTION FAILED</span>'
        : "");
    const features = (ml.top_matched_features || [])
      .slice(0, 8)
      .map((feature) => `<span>${escapeHtml(feature.token)} · ${feature.count}</span>`)
      .join("");

    return `
      <article class="result-card">
        <div class="result-heading">
          <h3>${escapeHtml(page.title || page.url)}</h3>
          <div class="result-badges">
            ${collectionBadge}
            <span class="decision-pill ${riskClass}">${decision}</span>
            <span class="risk-pill ${riskClass}">${score}</span>
          </div>
        </div>
        <a href="${escapeHtml(page.url)}" target="_blank" rel="noreferrer">${escapeHtml(page.url)}</a>
        <dl>
          <div><dt>Scripts</dt><dd>${page.scripts_found}</dd></div>
          <div><dt>Links</dt><dd>${page.links_found}</dd></div>
          <div><dt>Feature coverage</dt><dd>${percentage(ml.feature_coverage ?? 0)}</dd></div>
          <div><dt>Scored units</dt><dd>${ml.code_units_scored ?? 0}/${ml.code_units_analyzed ?? 0}</dd></div>
        </dl>
        ${features ? `<div class="features">${features}</div>` : ""}
        ${ml.reason ? `<p class="note">${escapeHtml(ml.reason)}</p>` : ""}
        ${(page.warnings || []).map((warning) => `<p class="note">${escapeHtml(warning)}</p>`).join("")}
      </article>
    `;
  }).join("");

  const alertCards = zapAlerts.map((alert) => `
    <article class="result-card ${alert.confirmed ? "verified" : "detected"}">
      <div class="result-heading">
        <h3>${escapeHtml(alert.name)}</h3>
        <div class="result-badges">
          <span class="decision-pill ${alert.confirmed ? "risk-high" : "risk-detected"}">
            ${alert.confirmed ? "ACTIVELY CONFIRMED" : "CLIENT-SIDE DETECTION"}
          </span>
          <span class="risk-pill risk-high">${escapeHtml(alert.risk)}</span>
        </div>
      </div>
      <a href="${escapeHtml(alert.url)}" target="_blank" rel="noreferrer">${escapeHtml(alert.url)}</a>
      <p><strong>Parameter:</strong> ${escapeHtml(alert.param || "n/a")}</p>
      <p><strong>Evidence:</strong> ${escapeHtml(alert.evidence || "n/a")}</p>
      <details>
        <summary>Technical details</summary>
        <p>${escapeHtml(alert.description)}</p>
        <p><strong>Recommended fix:</strong> ${escapeHtml(alert.solution)}</p>
      </details>
    </article>
  `).join("");

  results.innerHTML = `
    <div class="summary-grid">
      <div><strong>${summary.pages_collected}</strong><span>Pages collected</span></div>
      <div><strong>${summary.pages_scored}</strong><span>Pages scored</span></div>
      <div><strong>${summary.ml_high_risk_pages}</strong><span>High-priority pages</span></div>
      <div><strong>${summary.zap_dom_xss_findings ?? 0}</strong><span>ZAP findings / ${summary.verified_dom_xss_alerts ?? 0} confirmed</span></div>
    </div>
    <div class="section-heading">
      <h2>Analysis results</h2>
      <span>${escapeHtml(data.scope_mode)} · ${data.duration_seconds}s</span>
    </div>
    ${pageCards || '<p class="empty">No pages were collected.</p>'}
    ${data.dynamic_verification ? `
      <div class="section-heading"><h2>ZAP dynamic analysis</h2></div>
      ${zapWarnings.map((warning) => `<p class="note">${escapeHtml(warning)}</p>`).join("")}
      ${zapError
        ? `<p class="note error-note">ZAP verification failed: ${escapeHtml(zapError)}</p>`
        : (alertCards || '<p class="empty">ZAP did not report a DOM XSS finding.</p>')}
    ` : ""}
    <p class="disclaimer">${escapeHtml(data.disclaimer)}</p>
  `;
  results.classList.remove("hidden");
}

async function poll(statusUrl) {
  while (true) {
    const response = await fetch(statusUrl, { headers: { Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Failed to read scan status");

    statusLabel.textContent = stateLabel(payload.state);
    progressLabel.textContent = `${payload.progress}%`;
    progressBar.style.width = `${payload.progress}%`;
    stageLabel.textContent = payload.stage || "";

    if (payload.state === "finished") {
      renderResults(payload.result);
      return;
    }
    if (["failed", "stopped", "canceled"].includes(payload.state)) {
      throw new Error(payload.error || `Scan ${payload.state}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  results.classList.add("hidden");
  results.innerHTML = "";

  submitButton.disabled = true;
  submitButton.textContent = "Submitting…";
  statusCard.classList.remove("hidden");
    statusLabel.textContent = "QUEUED";
  progressLabel.textContent = "0%";
  progressBar.style.width = "0%";
  progressBar.classList.remove("failed");
    stageLabel.textContent = "Creating job";

  try {
    const response = await fetch("/api/scans", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        target_url: document.querySelector("#target-url").value,
        scope_mode: document.querySelector("#scope-mode").value,
        dynamic_verification: dynamicVerification.checked,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      const message = Array.isArray(payload.detail)
        ? payload.detail.map((item) => item.msg).join(", ")
        : payload.detail;
      throw new Error(message || "Failed to create scan");
    }
    await poll(payload.status_url);
  } catch (error) {
    statusLabel.textContent = "FAILED";
    stageLabel.textContent = error.message;
    progressBar.style.width = "100%";
    progressBar.classList.add("failed");
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Start analysis";
  }
});
