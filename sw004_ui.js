(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const token = document.querySelector('meta[name="csrf-token"]').content;
  let last = null;
  let lastComparison = null;
  let currentLogsCsv = "";

  /* -------------------------------------------------------------
     Tab Switching Navigation
  ------------------------------------------------------------- */
  function switchTab(tabId) {
    document.querySelectorAll(".nav-tab").forEach(tab => {
      tab.classList.toggle("active", tab.dataset.tab === tabId);
    });
    document.querySelectorAll(".tab-panel").forEach(panel => {
      panel.classList.toggle("active", panel.id === `tab-${tabId}`);
    });
  }

  document.querySelectorAll(".nav-tab").forEach(tab => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  const gotoGatewayBtn = el("goto-gateway-cta");
  if (gotoGatewayBtn) {
    gotoGatewayBtn.addEventListener("click", () => switchTab("gateway"));
  }

  /* -------------------------------------------------------------
     Utility Helpers
  ------------------------------------------------------------- */
  function status(message, isError = false) {
    const node = el("status");
    if (node) {
      node.textContent = message;
      node.classList.toggle("error", isError);
    }
  }

  function scanStatus(message, isError = false) {
    const node = el("scan-status");
    if (node) {
      node.textContent = message;
      node.classList.toggle("error", isError);
    }
  }

  function download(name, content, type) {
    const url = URL.createObjectURL(new Blob([content], {type}));
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  /* -------------------------------------------------------------
     Tab 1: Log Scanner Diagnostic (The Trojan Horse Lead Gen)
  ------------------------------------------------------------- */
  const dropzone = el("scan-dropzone");
  const fileInput = el("scan-file");

  if (dropzone && fileInput) {
    dropzone.addEventListener("click", () => fileInput.click());
    dropzone.addEventListener("dragover", e => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", async e => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      const file = e.dataTransfer.files[0];
      if (file) {
        currentLogsCsv = await file.text();
        scanStatus(`Loaded ${file.name} (${(file.size / 1024).toFixed(1)} KB). Ready to audit.`);
      }
    });
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files[0];
      if (file) {
        currentLogsCsv = await file.text();
        scanStatus(`Loaded ${file.name} (${(file.size / 1024).toFixed(1)} KB). Ready to audit.`);
      }
    });
  }

  const loadSampleLogsBtn = el("load-sample-logs");
  if (loadSampleLogsBtn) {
    loadSampleLogsBtn.addEventListener("click", async () => {
      try {
        scanStatus("Fetching 8,028 synthetic sample production logs...");
        const res = await fetch("/sample-logs", { cache: "no-store" });
        if (!res.ok) throw new Error("Could not load sample logs");
        currentLogsCsv = await res.text();
        scanStatus("✅ Loaded 8,028 production logs across US, EU, and ASIA (71.8 hours). Click Run Audit below.");
      } catch (err) {
        scanStatus("Error: " + err.message, true);
      }
    });
  }

  const btnScanLogs = el("btn-scan-logs");
  if (btnScanLogs) {
    btnScanLogs.addEventListener("click", async () => {
      if (!currentLogsCsv) {
        scanStatus("Please drop a log file or click 'Load 8,028 Sample Logs' first.", true);
        return;
      }
      btnScanLogs.disabled = true;
      scanStatus("Evaluating multi-region contractual avoidability waterfall...");
      try {
        const resp = await fetch("/scan-logs", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-SW004-Token": token },
          body: JSON.stringify({ logs_csv: currentLogsCsv })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Log audit failed");

        // Populate Waterfall Results
        el("scan-results").hidden = false;
        el("scan-pct").textContent = `${data.savings_percentage}%`;
        el("scan-baseline").textContent = `$${data.baseline_compute_usd.toLocaleString("en-US", {minimumFractionDigits: 2})} USD`;
        el("scan-candidate").textContent = `$${data.inferacap_compute_usd.toLocaleString("en-US", {minimumFractionDigits: 2})} USD`;
        el("scan-savings").textContent = `+$${data.net_savings_usd.toLocaleString("en-US", {minimumFractionDigits: 2})} USD`;
        el("scan-annual").textContent = `$${data.annualized_projected_savings_usd.toLocaleString("en-US", {minimumFractionDigits: 2})} USD / yr`;
        el("scan-meta").textContent = `Evaluated ${data.total_requests.toLocaleString()} requests (${data.total_tokens.toLocaleString()} tokens) over ${data.time_span_hours.toFixed(1)} hours`;

        // Populate Region Distribution Bars
        const barContainer = el("scan-region-bars");
        if (barContainer) {
          barContainer.replaceChildren();
          const colors = { US: "#0284c7", EU: "#10b981", ASIA: "#f59e0b" };
          for (const reg of data.unique_regions) {
            const row = document.createElement("div");
            const color = colors[reg] || "#64748b";
            row.innerHTML = `
              <div style="display:flex; justify-content:space-between; font-size:12px; font-weight:600; margin-bottom:2px;">
                <span>Region ${reg}</span>
                <span style="color:${color};">Active Cluster</span>
              </div>
              <div style="background:#e2e8f0; border-radius:4px; height:8px; width:100%; overflow:hidden;">
                <div style="background:${color}; height:100%; width:100%;"></div>
              </div>
            `;
            barContainer.append(row);
          }
        }
        scanStatus("✅ Financial Audit complete. Results calculated from verified contract avoidability.");
      } catch (err) {
        scanStatus("Audit Error: " + err.message, true);
      } finally {
        btnScanLogs.disabled = false;
      }
    });
  }

  /* -------------------------------------------------------------
     Tab 2: Live Prompt Tester
  ------------------------------------------------------------- */
  const btnSendPrompt = el("btn-send-test-prompt");
  if (btnSendPrompt) {
    btnSendPrompt.addEventListener("click", async () => {
      const promptText = el("test-prompt").value || "Analyze multi-region GPU fleet economics";
      const origin = el("test-origin").value;
      const budget = parseFloat(el("test-budget").value);
      const resultsDiv = el("test-prompt-results");

      btnSendPrompt.disabled = true;
      resultsDiv.style.display = "block";
      resultsDiv.innerHTML = `<span style="color:#38bdf8;">⚡ Dispatching request through InferaCap router (Origin: ${origin}, TTFT Budget: ${budget}ms)...</span>`;

      try {
        const resp = await fetch("/test-gateway-prompt", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-SW004-Token": token },
          body: JSON.stringify({ prompt: promptText, origin_region: origin, ttft_budget_ms: budget })
        });
        const res = await resp.json();
        if (!resp.ok) throw new Error(res.error || "Gateway test failed");

        const routeColor = res.route_type === "LOCAL" ? "#4ade80" : "#facc15";
        resultsDiv.innerHTML = `
<div style="border-bottom:1px solid #334155; padding-bottom:8px; margin-bottom:10px;">
  <span style="color:${routeColor}; font-weight:700;">[ROUTE DECISION: ${res.route_type}]</span>
  <span style="color:#94a3b8; margin-left:12px;">Served by: <strong style="color:#fff;">[${res.served_region}]</strong></span>
  <span style="color:#94a3b8; margin-left:12px;">Measured TTFT: <strong style="color:#38bdf8;">${res.ttft_ms}ms</strong> (Budget: ${budget}ms)</span>
  <span style="color:#4ade80; margin-left:12px;">Avoided On-Demand Spend: <strong>+$${res.avoided_compute_usd} USD</strong></span>
</div>
<div style="color:#e2e8f0; line-height:1.5;">
  <span style="color:#38bdf8;">OpenAI Ingress Response:</span> "${res.response_text}"
</div>
`;
      } catch (err) {
        resultsDiv.innerHTML = `<span style="color:#f87171;">Gateway Error: ${err.message}</span>`;
      } finally {
        btnSendPrompt.disabled = false;
      }
    });
  }

  /* -------------------------------------------------------------
     Tab 3: Offline Simulator (Preserving Original Tests)
  ------------------------------------------------------------- */
  function fileToText(input, target) {
    if (!input || !target) return;
    input.addEventListener("change", async () => {
      const file = input.files[0];
      if (file) target.value = await file.text();
    });
  }
  fileToText(el("scenario-file"), el("scenario"));
  fileToText(el("observations-file"), el("observations"));

  const loadSampleBtn = el("load-sample");
  if (loadSampleBtn) {
    loadSampleBtn.addEventListener("click", async () => {
      try {
        const [config, observations] = await Promise.all([
          fetch("/sample-config", {cache: "no-store"}),
          fetch("/sample-observations", {cache: "no-store"})
        ]);
        if (!config.ok || !observations.ok) throw new Error("Bundled sample is unavailable");
        el("scenario").value = await config.text();
        el("observations").value = await observations.text();
        status("Synthetic example loaded. Review and run it when ready.");
      } catch (error) { status(error.message, true); }
    });
  }

  const saveScenarioBtn = el("save-scenario");
  if (saveScenarioBtn) {
    saveScenarioBtn.addEventListener("click", () => {
      try {
        JSON.parse(el("scenario").value);
        download("sw004_scenario.json", el("scenario").value, "application/json");
        status("Scenario JSON saved through your browser.");
      } catch (error) { status("Scenario JSON is invalid: " + error.message, true); }
    });
  }

  const saveObsBtn = el("save-observations");
  if (saveObsBtn) {
    saveObsBtn.addEventListener("click", () => {
      download("sw004_observations.csv", el("observations").value, "text/csv");
      status("Observations CSV saved through your browser.");
    });
  }

  const runBtn = el("run");
  if (runBtn) {
    runBtn.addEventListener("click", async () => {
      el("results").hidden = true;
      last = null;
      const scenarioJson = el("scenario").value;
      try { JSON.parse(scenarioJson); }
      catch (error) { status("Scenario JSON is invalid: " + error.message, true); return; }
      const observations = el("observations").value.trim();
      const payload = {scenario_json: scenarioJson};
      if (observations) payload.observations_csv = observations;
      runBtn.disabled = true;
      status("Calculating locally…");
      try {
        const response = await fetch("/run", {
          method: "POST", headers: {"Content-Type": "application/json", "X-SW004-Token": token},
          body: JSON.stringify(payload), cache: "no-store"
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Calculation failed");
        last = data;
        const report = data.report;
        el("run-meta").textContent = `${report.scenario_id} · ${report.hours} hours · ${report.status} · exported ${report.exported_utc}`;
        const metrics = [
          ["Baseline compute", report.baseline_compute_usd + " USD"],
          ["Constrained candidate compute", report.candidate_compute_usd + " USD"],
          ["Fixed reservation invoice (exact)", report.billing_breakdown_usd_exact.fixed_commitment + " USD"],
          ["Baseline variable usage (exact)", report.billing_breakdown_usd_exact.baseline_variable_usage + " USD"],
          ["Candidate variable usage (exact)", report.billing_breakdown_usd_exact.candidate_variable_usage + " USD"],
          ["Perfect-pooling compute lower bound", report.perfect_pooling_compute_lower_bound_usd + " USD"],
          ["Network", report.network_usd + " USD"],
          ["Software", report.software_usd + " USD"],
          ["Operations", report.operations_usd + " USD"],
          ["Migration", report.migration_usd + " USD"],
          ["Rounding adjustment", report.rounding_adjustment_usd + " USD"],
          ["Net current cash delta", report.net_current_cash_delta_usd + " USD"],
          ["Theoretical GPU-hours reduction", String(report.theoretical_gpu_hours_reduction)]
        ];
        const rows = el("metrics"); rows.replaceChildren();
        for (const [label, value] of metrics) {
          const row = document.createElement("tr"), head = document.createElement("th"), cell = document.createElement("td");
          head.textContent = label; cell.textContent = value; row.append(head, cell); rows.append(row);
        }
        const warnings = el("limitations"); warnings.replaceChildren();
        for (const warning of report.limitations) {
          const item = document.createElement("li"); item.textContent = warning; warnings.append(item);
        }
        el("results").hidden = false;
        status("Calculation complete. Download the reports for the full assignments and provenance.");
      } catch (error) { status(error.message, true); }
      finally { runBtn.disabled = false; }
    });
  }

  function reportName(extension) {
    const report = last.report;
    return `${report.scenario_id}_report_${report.exported_utc.replace(/[-:]/g, "").replace(".000000", "")}.${extension}`;
  }
  const dlJson = el("download-json");
  if (dlJson) dlJson.addEventListener("click", () => {
    if (last) download(reportName("json"), JSON.stringify(last.report, null, 2) + "\n", "application/json");
  });
  const dlCsv = el("download-csv");
  if (dlCsv) dlCsv.addEventListener("click", () => {
    if (last) download(reportName("csv"), last.report_csv, "text/csv");
  });

  const compareBtn = el("compare");
  if (compareBtn) {
    compareBtn.addEventListener("click", async () => {
      lastComparison = null;
      el("compare-results").hidden = true;
      const files = Array.from(el("compare-files").files);
      const message = el("compare-status");
      function compareStatus(value, error = false) {
        message.textContent = value;
        message.classList.toggle("error", error);
      }
      if (files.length < 2 || files.length > 10) {
        compareStatus("Select 2–10 complete scenario JSON files.", true); return;
      }
      if (files.some(file => file.size > 10_000_000) || files.reduce((total, file) => total + file.size, 0) > 20_000_000) {
        compareStatus("Each file must be at most 10 MB and the selection at most 20 MB.", true); return;
      }
      compareBtn.disabled = true;
      compareStatus("Comparing locally…");
      try {
        const cases = await Promise.all(files.map(async file => {
          const scenarioJson = await file.text();
          JSON.parse(scenarioJson);
          return {name: file.name.replace(/\.json$/i, ""), scenario_json: scenarioJson};
        }));
        const response = await fetch("/compare", {
          method: "POST", headers: {"Content-Type": "application/json", "X-SW004-Token": token},
          body: JSON.stringify({cases}), cache: "no-store"
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Comparison failed");
        lastComparison = data.comparison;
        const report = lastComparison;
        el("compare-range").textContent = `Modeled net range: ${report.minimum_net_current_cash_delta_usd} to ${report.maximum_net_current_cash_delta_usd} ${report.currency}. ${report.includes_nonpositive_case ? "At least one case is zero or negative." : "All supplied cases are positive."}`;
        const rows = el("compare-cases"); rows.replaceChildren();
        for (const item of report.cases) {
          const row = document.createElement("tr"), name = document.createElement("td"), value = document.createElement("td");
          name.textContent = item.case; value.textContent = `${item.net_current_cash_delta_usd} ${report.currency}`;
          row.append(name, value); rows.append(row);
        }
        el("compare-limit").textContent = report.limitations.join(" ");
        el("compare-results").hidden = false;
        compareStatus("Comparison complete. Download JSON for input hashes, assumptions and cost components.");
      } catch (error) { compareStatus(error.message, true); }
      finally { compareBtn.disabled = false; }
    });
  }

  const dlComp = el("download-comparison");
  if (dlComp) dlComp.addEventListener("click", () => {
    if (lastComparison) download(`sw004_comparison_${lastComparison.exported_utc.replace(/[-:]/g, "").replace(".000000", "")}.json`, JSON.stringify(lastComparison, null, 2) + "\n", "application/json");
  });

  /* -------------------------------------------------------------
     Tab 4: Telemetry & Feature Drop/Merge Analytics
  ------------------------------------------------------------- */
  async function loadAnalytics() {
    try {
      const resp = await fetch("/analytics", {cache: "no-store"});
      if (!resp.ok) return;
      const data = await resp.json();
      const container = el("chart-bars");
      if (!container) return;
      container.replaceChildren();

      const colors = {
        live_routing: "#0284c7",
        offline_simulator: "#059669",
        log_scanner: "#d97706",
        cloud_worker: "#7c3aed"
      };

      const labels = {
        live_routing: "⚡ Live Intelligent Gateway Routing",
        offline_simulator: "🧪 Pre-Sales Offline Capacity Simulator",
        log_scanner: "📁 Historical Telemetry Log Scanner",
        cloud_worker: "🖥️ Kaggle / Colab Cloud GPU Federation"
      };

      for (const [key, pct] of Object.entries(data.feature_distribution_pct || {})) {
        const count = (data.feature_counts && data.feature_counts[key]) || 0;
        const color = colors[key] || "#64748b";
        const label = labels[key] || key;

        const row = document.createElement("div");
        row.innerHTML = `
          <div style="display:flex; justify-content:space-between; font-size:13px; font-weight:600; margin-bottom:4px;">
            <span>${label}</span>
            <span>${pct}% (${count} interactions)</span>
          </div>
          <div style="background:#e2e8f0; border-radius:4px; height:18px; width:100%; overflow:hidden;">
            <div style="background:${color}; height:100%; width:${Math.max(pct, 2)}%; border-radius:4px; transition: width 0.3s ease;"></div>
          </div>
        `;
        container.append(row);
      }

      const recs = el("analytics-recommendations");
      if (recs && data.recommendations) {
        recs.replaceChildren();
        for (const rec of data.recommendations) {
          const li = document.createElement("li");
          li.textContent = rec;
          recs.append(li);
        }
      }
    } catch (e) {
      console.warn("Could not load telemetry analytics", e);
    }
  }

  const refreshBtn = el("refresh-analytics");
  if (refreshBtn) refreshBtn.addEventListener("click", loadAnalytics);
  loadAnalytics();
})();
