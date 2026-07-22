const form = document.querySelector("#scan-form");
const dynamicVerification = document.querySelector("#dynamic-verification");
const authorizationRow = document.querySelector("#authorization-row");
const authorized = document.querySelector("#authorized");
const activeWarning = document.querySelector("#active-warning");
const submitButton = document.querySelector("#submit-button");
const statusCard = document.querySelector("#status-card");
const statusLabel = document.querySelector("#status-label");
const progressLabel = document.querySelector("#progress-label");
const progressBar = document.querySelector("#progress-bar");
const stageLabel = document.querySelector("#stage-label");
const results = document.querySelector("#results");

dynamicVerification.addEventListener("change", () => {
  const enabled = dynamicVerification.checked;
  authorizationRow.classList.toggle("hidden", !enabled);
  activeWarning.classList.toggle("hidden", !enabled);
  if (!enabled) authorized.checked = false;
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

function renderResults(data) {
  const summary = data.summary;
  const pages = data.pages || [];
  const zapAlerts = data.zap?.alerts || [];
  const zapError = data.zap?.status === "failed" ? data.zap.error : "";

  const pageCards = pages.map((page) => {
    const ml = page.ml || {};
    const riskClass = ml.vulnerable ? "risk-high" : "risk-low";
    const score = ml.status === "scored" ? percentage(ml.probability) : "Not scored";
    const features = (ml.top_matched_features || [])
      .slice(0, 8)
      .map((feature) => `<span>${escapeHtml(feature.token)} · ${feature.count}</span>`)
      .join("");

    return `
      <article class="result-card">
        <div class="result-heading">
          <h3>${escapeHtml(page.title || page.url)}</h3>
          <span class="risk-pill ${riskClass}">${score}</span>
        </div>
        <a href="${escapeHtml(page.url)}" target="_blank" rel="noreferrer">${escapeHtml(page.url)}</a>
        <dl>
          <div><dt>Scripts</dt><dd>${page.scripts_found}</dd></div>
          <div><dt>Links</dt><dd>${page.links_found}</dd></div>
          <div><dt>Matched tokens</dt><dd>${ml.matched_tokens ?? 0}</dd></div>
        </dl>
        ${features ? `<div class="features">${features}</div>` : ""}
        ${(page.warnings || []).map((warning) => `<p class="note">${escapeHtml(warning)}</p>`).join("")}
      </article>
    `;
  }).join("");

  const alertCards = zapAlerts.map((alert) => `
    <article class="result-card verified">
      <div class="result-heading">
        <h3>${escapeHtml(alert.name)}</h3>
        <span class="risk-pill risk-high">${escapeHtml(alert.risk)}</span>
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
      <div><strong>${summary.ml_high_risk_pages}</strong><span>ML high-risk pages</span></div>
      <div><strong>${summary.verified_dom_xss_alerts}</strong><span>Verified alerts</span></div>
    </div>
    <div class="section-heading">
      <h2>Page analysis</h2>
      <span>${escapeHtml(data.scope_mode)} · ${data.duration_seconds}s</span>
    </div>
    ${pageCards || '<p class="empty">No pages were collected.</p>'}
    ${data.dynamic_verification ? `
      <div class="section-heading"><h2>ZAP verification</h2></div>
      ${zapError
        ? `<p class="note error-note">ZAP verification failed: ${escapeHtml(zapError)}</p>`
        : (alertCards || '<p class="empty">No DOM XSS alert was verified by ZAP.</p>')}
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

    statusLabel.textContent = payload.state;
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

  if (dynamicVerification.checked && !authorized.checked) {
    window.alert("Confirm that you are authorized to actively test this target.");
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "Submitting…";
  statusCard.classList.remove("hidden");
  statusLabel.textContent = "queued";
  progressLabel.textContent = "0%";
  progressBar.style.width = "0%";
  progressBar.classList.remove("failed");
  stageLabel.textContent = "creating job";

  try {
    const response = await fetch("/api/scans", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        target_url: document.querySelector("#target-url").value,
        scope_mode: document.querySelector("#scope-mode").value,
        dynamic_verification: dynamicVerification.checked,
        authorized: authorized.checked,
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
    statusLabel.textContent = "failed";
    stageLabel.textContent = error.message;
    progressBar.style.width = "100%";
    progressBar.classList.add("failed");
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Start analysis";
  }
});
