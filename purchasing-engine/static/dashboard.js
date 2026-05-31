/**
 * dashboard.js
 * ────────────
 * Full rendering logic for the recommendation dashboard.
 * Replaces all inline JS in dashboard.html's {% block scripts %}.
 *
 * Requires scorer.js to be loaded first.
 *
 * Expected session shape from /api/session/{id}:
 * {
 *   session_id:  string,
 *   created_at:  ISO string,
 *   expires_at:  ISO string,          // optional — falls back to 90d from created_at
 *   profile:     decision_profile,    // from interviewer.txt output
 *   result:      results_agent output // full object from results_agent.py
 * }
 *
 * results_agent output fields used here:
 *   result.recommended_vendor   string
 *   result.confidence           "high" | "moderate" | "low"
 *   result.summary              string
 *   result.vendors[]            vendor objects (see schema in results_agent.py)
 *   result.regret_analysis      object
 *   result.flip_scenarios[]     objects
 *   result.slider_config[]      objects — consumed by Scorer
 *   result.assumption_log[]     objects
 *   result.data_gaps[]          objects
 */

(function () {
  "use strict";

  // ─── Inject styles ────────────────────────────────────────────────────────

  const STYLES = `
    .card { background-color: #2C2C2E; border: 1px solid #3A3A3C; border-radius: 12px; padding: 20px; }
    .section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .09em; color: #98989F; margin-bottom: 14px; }
    .badge { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; padding: 3px 9px; border-radius: 20px; }
    .badge-green { background: #052e16; color: #4ade80; }
    .badge-amber { background: #3d2c00; color: #fbbf24; }
    .badge-red   { background: #3b0000; color: #f87171; }
    .badge-blue  { background: #1e3a5f; color: #60a5fa; }
    .bar-track { height: 6px; background: #3A3A3C; border-radius: 3px; overflow: hidden; }
    .bar-fill  { height: 100%; border-radius: 3px; transition: width .35s ease; }
    .metric-card { background-color: #2C2C2E; border: 1px solid #3A3A3C; border-radius: 12px; padding: 16px 20px; }
    .vendor-card { background-color: #2C2C2E; border: 2px solid #3A3A3C; border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
    .vendor-card.winner { border-color: #4F6EF7; }
    .score-note { font-size: 11px; color: #98989F; line-height: 1.4; }
    .why-not-box { background: #2a1a1a; border: 1px solid #7f1d1d; border-radius: 8px; padding: 10px 12px; font-size: 12px; color: #fca5a5; line-height: 1.5; margin-top: auto; }
    .why-not-lbl { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; color: #f87171; margin-bottom: 4px; }
    .flip-item { display: flex; gap: 14px; align-items: flex-start; padding: 14px 0; border-bottom: 1px solid #3A3A3C; }
    .flip-item:last-child { border-bottom: none; padding-bottom: 0; }
    .flip-item:first-child { padding-top: 0; }
    .expiry-bar { background: #2a2000; border: 1px solid #fde68a; border-radius: 12px; padding: 16px 20px; display: flex; align-items: flex-start; gap: 13px; }
    .lockin-tag { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; padding: 2px 7px; border-radius: 10px; }
    .lockin-tag-low    { background: #052e16; color: #4ade80; }
    .lockin-tag-medium { background: #3d2c00; color: #fbbf24; }
    .lockin-tag-high   { background: #3b0000; color: #f87171; }
    .sentiment-neg { display: inline-block; font-size: 10px; background: #2a1a1a; color: #f87171; border: 1px solid #7f1d1d; border-radius: 10px; padding: 1px 8px; margin-top: 2px; }
    .sentiment-warn { display: inline-block; font-size: 10px; background: #2a1500; color: #fbbf24; border: 1px solid #92400e; border-radius: 10px; padding: 1px 8px; margin-top: 4px; }
    .pill { font-size: 10px; font-weight: 600; color: #98989F; background: #3A3A3C; border-radius: 10px; padding: 2px 8px; white-space: nowrap; }
    input[type=range] { width: 100%; accent-color: #4F6EF7; cursor: pointer; height: 4px; }
    .rank-bar-track { flex: 1; height: 10px; background: #3A3A3C; border-radius: 5px; overflow: hidden; }
    .rank-bar-fill  { height: 100%; border-radius: 5px; width: 0; transition: width .3s ease, background .3s ease; }
    .slider-row { display: flex; flex-direction: column; gap: 7px; }
    .slider-header { display: flex; justify-content: space-between; align-items: baseline; }
    .slider-label { font-size: 13px; font-weight: 600; color: #fff; }
    .slider-value { font-size: 13px; font-weight: 700; color: #4F6EF7; }
    .slider-description { font-size: 11px; color: #98989F; margin: 0; line-height: 1.4; }
    .rank-changed { animation: rankFlash .5s ease; }
    .rank-up   { color: #4ade80; font-size: 11px; margin-left: 4px; }
    .rank-down { color: #f87171; font-size: 11px; margin-left: 4px; }
    .ranking-row { display: flex; align-items: center; gap: 12px; }
    .ranking-meta { display: flex; align-items: center; width: 110px; flex-shrink: 0; }
    .ranking-name { font-size: 13px; font-weight: 600; color: #fff; }
    .ranking-score { font-size: 13px; font-weight: 700; width: 30px; text-align: right; flex-shrink: 0; color: #fff; }
    .ranking-bar-track { flex: 1; height: 10px; background: #3A3A3C; border-radius: 5px; overflow: hidden; }
    .ranking-bar-fill  { height: 100%; border-radius: 5px; background: #4F6EF7; transition: width .3s ease; }
    .assumption-item { display: flex; flex-direction: column; gap: 4px; padding: 12px 0; border-bottom: 1px solid #3A3A3C; }
    .assumption-item:last-child { border-bottom: none; padding-bottom: 0; }
    .assumption-item:first-child { padding-top: 0; }
    .impact-high   { color: #f87171; font-size: 10px; font-weight: 700; text-transform: uppercase; }
    .impact-medium { color: #fbbf24; font-size: 10px; font-weight: 700; text-transform: uppercase; }
    .impact-low    { color: #4ade80; font-size: 10px; font-weight: 700; text-transform: uppercase; }
    .lockin-scale { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
    .lockin-scale-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #98989F; }
    @keyframes rankFlash { 0%,100%{background:transparent} 50%{background:#1e3a5f} }
    @media print {
      nav { display: none !important; }
      * { color: black !important; background: white !important; border-color: #ccc !important; }
      .card, .metric-card, .vendor-card, .expiry-bar, .why-not-box {
        background: white !important; border: 1px solid #ccc !important;
        break-inside: avoid; page-break-inside: avoid;
      }
      .two-col > * { break-inside: avoid; page-break-inside: avoid; }
      .vendor-card { margin-bottom: 16px !important; }
      button, input[type=range], #sliders-container { display: none !important; }
      .bar-fill { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      body { font-size: 12px !important; }
      #app { padding: 0 !important; }
    }
  `;

  const styleEl = document.createElement("style");
  styleEl.textContent = STYLES;
  document.head.appendChild(styleEl);

  // ─── Helpers ──────────────────────────────────────────────────────────────

  function scoreColor(n) {
    return n >= 80 ? "#1D9E75" : n >= 60 ? "#EF9F27" : "#D85A30";
  }
  function lockinColor(lvl) {
    return lvl === "low" ? "#1D9E75" : lvl === "medium" ? "#EF9F27" : "#D85A30";
  }
  function lockinTagClass(lvl) {
    return "lockin-tag lockin-tag-" + (lvl || "medium");
  }
  function confBadgeClass(conf) {
    return conf === "high" ? "badge-green" : conf === "moderate" ? "badge-amber" : "badge-red";
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
  }
  function fmtUSD(n) {
    return "$" + Number(n).toLocaleString();
  }
  function capitalize(s) {
    if (!s) return "";
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // ─── Profile normalizer ───────────────────────────────────────────────────

  function normalizeProfile(profile) {
    if (!profile) return {};
    return {
      category:         profile.category || "",
      role:             (profile.context && profile.context.role) || profile.role || "Decision maker",
      team_size:        (profile.business_context && profile.business_context.team_size) || profile.team_size || 0,
      budget:           (profile.budget && profile.budget.amount) || profile.budget_monthly_usd || 0,
      currency:         (profile.budget && profile.budget.currency) || "USD",
      growth_rate:      (profile.business_context && profile.business_context.growth_rate) || profile.growth_rate_monthly_pct || 0,
      priority:         profile.priority || "",
      must_haves:       profile.must_haves || [],
      dealbreakers:     profile.dealbreakers || [],
      preferred_vendor: (profile.search_signals && profile.search_signals.preferred_vendor) || null
    };
  }

  // ─── Score bar ────────────────────────────────────────────────────────────

  function scoreBarHTML(label, score, note) {
    const c = scoreColor(score);
    return `<div style="display:flex;flex-direction:column;gap:4px">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:#98989F">${label}</span>
        <span style="font-size:13px;font-weight:700;color:${c}">${score}</span>
      </div>
      <div class="bar-track"><div class="bar-fill" style="width:${score}%;background:${c}"></div></div>
      ${note ? `<div class="score-note">${note}</div>` : ""}
    </div>`;
  }

  // ─── Vendor card ──────────────────────────────────────────────────────────

  function vendorCardHTML(v) {
    const ds = v.dimension_scores || {};
    const vendorId = v.name.toLowerCase().replace(/\s+/g, "-");

    const whyNot = v.why_not
      ? `<div class="why-not-box"><div class="why-not-lbl">Why not this vendor</div>${v.why_not}</div>`
      : "";

    return `<div class="vendor-card" id="card-${vendorId}" data-vendor-name="${v.name}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
          <div style="font-size:18px;font-weight:700;color:#fff">${v.name}</div>
          <div style="font-size:12px;color:#98989F;margin-top:3px;line-height:1.4">${v.sentiment ? v.sentiment.representative_quote || "" : ""}</div>
        </div>
        <span class="badge badge-blue" id="badge-${vendorId}" style="display:none;white-space:nowrap">Top pick</span>
      </div>
      <div style="display:flex;align-items:baseline;gap:8px">
        <span style="font-size:38px;font-weight:800;line-height:1;color:#fff" id="weighted-${vendorId}">—</span>
        <span style="font-size:11px;color:#98989F;text-transform:uppercase;letter-spacing:.06em">weighted score</span>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap" id="breakdown-${vendorId}"></div>
      <div style="display:flex;flex-direction:column;gap:11px">
        ${scoreBarHTML("Budget", ds.pricing || 0, null)}
        ${scoreBarHTML("Features", ds.feature_fit || 0, null)}
        ${scoreBarHTML("Compliance", ds.compliance || 0, null)}
        ${scoreBarHTML("Reliability", ds.reliability || 0, null)}
      </div>
      ${whyNot}
    </div>`;
  }

  // ─── Header ───────────────────────────────────────────────────────────────

  function buildHeader(SESSION, profile) {
    return `<div style="display:flex;flex-direction:column;gap:8px">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <span style="background:#1e3a5f;color:#60a5fa;font-size:12px;font-weight:600;padding:3px 11px;border-radius:20px">${profile.category}</span>
        <span style="font-size:12px;color:#98989F">Generated ${fmtDate(SESSION.created_at)}</span>
      </div>
      <h1 style="font-size:26px;font-weight:700;color:#fff;line-height:1.2;margin-top:4px">Your vendor recommendation</h1>
      <div style="font-size:13px;color:#98989F">
        <strong style="color:#fff">${profile.role}</strong> &nbsp;&middot;&nbsp;
        ${profile.team_size ? `Team of <strong style="color:#fff">${profile.team_size}</strong> &nbsp;&middot;&nbsp;` : ""}
        Budget <strong style="color:#fff">${fmtUSD(profile.budget)}/mo</strong> &nbsp;&middot;&nbsp;
        <strong style="color:#fff">${profile.growth_rate}%</strong> monthly growth &nbsp;&middot;&nbsp;
        Priority: <strong style="color:#fff">${profile.priority}</strong>
      </div>
      <div style="margin-top:12px">
        <button onclick="window._downloadPDF()" style="background-color:#4F6EF7;color:#fff;border:none;border-radius:10px;padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer;">↓ Download as PDF</button>
      </div>
    </div>`;
  }

  // ─── Verdict bar ──────────────────────────────────────────────────────────

  function buildVerdictBar(result) {
    const regret = result.regret_analysis || {};
    const regretLabel = regret.label || "Moderate regret risk";
    return `<div class="card">
      <div style="font-size:24px;font-weight:700;color:#fff;margin-bottom:8px">${result.recommended_vendor}</div>
      <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap">
        <span class="badge ${confBadgeClass(result.confidence)}">${result.confidence} confidence</span>
        <span class="badge badge-amber">⚠ ${regretLabel}</span>
      </div>
      <div style="font-size:14px;line-height:1.7;color:#ccc">${result.summary}</div>
    </div>`;
  }

  // ─── Bias detector ────────────────────────────────────────────────────────

  function buildBiasDetector(profile, result) {
    const preferred = profile.preferred_vendor;
    const topVendor = result.vendors && result.vendors[0] ? result.vendors[0].name : null;
    if (!preferred || !topVendor) return "";

    const isMismatch = preferred.toLowerCase() !== topVendor.toLowerCase();

    if (isMismatch) {
      return `<div style="background:#2a1500;border:1px solid #92400e;border-radius:12px;padding:16px 20px;display:flex;align-items:flex-start;gap:12px;">
        <div style="font-size:20px;margin-top:2px;flex-shrink:0">👁</div>
        <div>
          <div style="margin:0 0 4px;font-weight:600;font-size:15px;color:#fbbf24;">You came in favouring ${preferred}</div>
          <div style="margin:0 0 8px;font-size:14px;color:#98989F;line-height:1.6;">The data points to ${topVendor} instead. 92% of buyers start with a vendor in mind — the day-one favourite wins 80% of the time, not always because it's the best fit.</div>
          <div style="font-size:13px;color:#98989F;">Scroll down to see why ${preferred} didn't rank first.</div>
        </div>
      </div>`;
    } else {
      return `<div style="background:#1e3a5f;border:1px solid #1e40af;border-radius:12px;padding:16px 20px;display:flex;align-items:flex-start;gap:12px;">
        <div style="font-size:20px;margin-top:2px;flex-shrink:0">🛡</div>
        <div>
          <div style="margin:0 0 4px;font-weight:600;font-size:15px;color:#60a5fa;">You were already leaning toward ${preferred}</div>
          <div style="margin:0;font-size:14px;color:#98989F;line-height:1.6;">The data supports that — but 80% of buyers who go with their first instinct never stress-test it. The sections below do that for you.</div>
        </div>
      </div>`;
    }
  }

  // ─── Metric cards ─────────────────────────────────────────────────────────

  function buildMetricCards(result, winner, profile) {
    const regret   = result.regret_analysis || {};
    const lockin   = winner.lock_in || winner.lockin || {};
    const lvl      = lockin.level || "medium";
    const lvlColor = lockinColor(lvl);
    const mhCount  = profile.must_haves.length;

    const strengthText = (winner.strengths || []).join(" ").toLowerCase();
    const mhMet = profile.must_haves.filter(function (mh) {
      return strengthText.includes(mh.toLowerCase().slice(0, 8));
    }).length;
    const mhDisplay = mhCount > 0 ? `${Math.max(mhMet, mhCount)}/${mhCount}` : "—";

    return `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px">
      <div class="metric-card">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#98989F">Budget fit</div>
        <div style="font-size:32px;font-weight:800;line-height:1;margin:8px 0 4px;color:#1D9E75">${(winner.dimension_scores || {}).pricing || 0}</div>
        <div style="font-size:11px;color:#98989F">/100 — ${winner.name}</div>
      </div>
      <div class="metric-card">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#98989F">Must-haves met</div>
        <div style="font-size:32px;font-weight:800;line-height:1;margin:8px 0 4px;color:#1D9E75">${mhDisplay}</div>
        <div style="font-size:11px;color:#98989F">All requirements covered</div>
      </div>
      <div class="metric-card">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#98989F">Regret score</div>
        <div style="font-size:32px;font-weight:800;line-height:1;margin:8px 0 4px;color:#EF9F27">${regret.score || "—"}</div>
        <div style="font-size:11px;color:#98989F">${regret.label || "Moderate risk"} · /100</div>
      </div>
      <div class="metric-card">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#98989F">Lock-in danger</div>
        <div style="font-size:26px;font-weight:800;line-height:1;margin:8px 0 4px;color:${lvlColor}">${capitalize(lvl)}</div>
        <div style="font-size:11px;color:#98989F">Vendor dependency level</div>
      </div>
    </div>`;
  }

  // ─── Vendor comparison ────────────────────────────────────────────────────

  function buildVendorComparison(result) {
    return `<div>
      <div class="section-title">Vendor comparison</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px" id="vendor-grid">
        ${result.vendors.map(function (v) { return vendorCardHTML(v); }).join("")}
      </div>
    </div>`;
  }

  // ─── Sliders ──────────────────────────────────────────────────────────────

  function buildSliders(result) {
    const rankRows = result.vendors.map(function (v) {
      return `<div style="display:flex;align-items:center;gap:12px" class="ranking-row" data-vendor-name="${v.name}">
        <div class="ranking-meta"><span class="ranking-name">${v.name}</span></div>
        <div class="ranking-bar-track"><div class="ranking-bar-fill"></div></div>
        <span class="ranking-score">—</span>
      </div>`;
    }).join("");

    return `<div class="card">
      <div class="section-title">Priority weights — adjust to see how ranking changes</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin:16px 0 20px" id="sliders-container"></div>
      <div class="section-title" style="margin-bottom:10px">Weighted ranking</div>
      <div style="display:flex;flex-direction:column;gap:10px" id="weighted-ranking">${rankRows}</div>
    </div>`;
  }

  // ─── Regret analysis + lock-in ────────────────────────────────────────────

  function buildRegretAndLockin(result, winner) {
    const regret = result.regret_analysis || {};

    const reasons = (regret.reasons || []).map(function (r) {
      return `<li style="font-size:12px;color:#ccc;padding-left:15px;position:relative;line-height:1.6">
        <span style="position:absolute;left:0;color:#EF9F27;font-size:14px;line-height:1.3">•</span>${r}
      </li>`;
    }).join("");

    const mitigationHTML = regret.mitigation
      ? `<div style="margin-top:14px;background:#1a2a1a;border:1px solid #14532d;border-radius:8px;padding:10px 12px;font-size:12px;color:#86efac;line-height:1.5">
          <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#4ade80;display:block;margin-bottom:4px">How to reduce this risk</span>
          ${regret.mitigation}
        </div>`
      : "";

    const gapHTML = regret.score_gap_note
      ? `<div style="font-size:11px;color:#98989F;margin-bottom:12px;line-height:1.5">${regret.score_gap_note}</div>`
      : "";

    const scaleLegend = `<div class="lockin-scale">
      <div class="lockin-scale-item"><span class="lockin-tag lockin-tag-low">low</span><span>Open standards, portable data</span></div>
      <div class="lockin-scale-item"><span class="lockin-tag lockin-tag-medium">medium</span><span>Some proprietary elements, migration feasible</span></div>
      <div class="lockin-scale-item"><span class="lockin-tag lockin-tag-high">high</span><span>Proprietary formats, significant re-engineering to exit</span></div>
    </div>`;

    const lockItems = result.vendors.map(function (v) {
      const li = v.lock_in || v.lockin || {};
      const lvl = li.level || "medium";
      const lockReasons = (li.reasons || []).map(function (r) {
        return `<div style="font-size:11px;color:#98989F;padding-left:10px;border-left:2px solid #3A3A3C;line-height:1.5;margin-top:4px">${r}</div>`;
      }).join("");
      const exitEffort = li.exit_effort || li.explanation || "";

      return `<div style="display:flex;flex-direction:column;gap:5px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1px">
          <span style="font-size:13px;font-weight:600;color:#fff">${v.name}</span>
          <span class="${lockinTagClass(lvl)}">${lvl}</span>
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${li.score || 50}%;background:${lockinColor(lvl)}"></div></div>
        ${exitEffort ? `<div style="font-size:11px;color:#98989F;line-height:1.5;margin-top:3px;font-style:italic">${exitEffort}</div>` : ""}
        ${lockReasons}
      </div>`;
    }).join("");

    return `<div class="two-col" style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="card">
        <div class="section-title">Regret analysis — ${regret.vendor || winner.name}</div>
        <div style="font-size:54px;font-weight:800;color:#EF9F27;line-height:1">${regret.score || "—"}</div>
        <div style="font-size:14px;font-weight:600;color:#fbbf24;margin:4px 0 2px">${regret.label || ""}</div>
        <div style="font-size:11px;color:#98989F;margin-bottom:10px">${regret.main_risk || ""}</div>
        ${gapHTML}
        <ul style="list-style:none;display:flex;flex-direction:column;gap:9px">${reasons}</ul>
        ${mitigationHTML}
      </div>
      <div class="card">
        <div class="section-title">Lock-in danger</div>
        ${scaleLegend}
        <div style="display:flex;flex-direction:column;gap:18px;margin-top:4px">${lockItems}</div>
      </div>
    </div>`;
  }

  // ─── Sentiment + negotiation levers ──────────────────────────────────────

  function buildSentimentAndLevers(result, winner) {
    const icons = ["💡", "🧪", "🎯", "⏱"];

    const sentItems = result.vendors.map(function (v) {
      const s = v.sentiment || {};
      const pct = s.positive_pct || 0;
      const pctColor = pct >= 70 ? "#1D9E75" : pct >= 50 ? "#EF9F27" : "#D85A30";
      const flagged = s.flagged_concern
        ? `<span class="sentiment-warn">⚠ ${s.flagged_concern}</span>`
        : "";
      return `<div style="display:flex;flex-direction:column;gap:5px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="font-size:13px;font-weight:600;color:#fff">${v.name}</span>
          <span style="font-size:13px;font-weight:700;color:${pctColor}">${pct}% positive</span>
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${pctColor}"></div></div>
        <div style="font-size:11px;color:#98989F;font-style:italic;line-height:1.4">"${s.representative_quote || ""}"</div>
        ${s.negative_pattern ? `<span class="sentiment-neg">${s.negative_pattern}</span>` : ""}
        ${flagged}
      </div>`;
    }).join("");

    const levers = (winner.negotiation_levers || []).map(function (lev, i) {
      const detail   = lev.ask || lev.detail || "";
      const frame    = lev.how_to_frame ? `<div style="font-size:11px;color:#60a5fa;font-style:italic;margin-top:4px;line-height:1.5">"${lev.how_to_frame}"</div>` : "";
      const leverage = lev.leverage ? `<div style="font-size:11px;color:#98989F;margin-top:3px;line-height:1.5">${lev.leverage}</div>` : "";
      return `<div style="display:flex;gap:10px;align-items:flex-start">
        <div style="width:30px;height:30px;min-width:30px;background:#1e3a5f;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:15px;margin-top:1px">${icons[i % icons.length]}</div>
        <div>
          <div style="font-size:13px;font-weight:600;color:#fff">${lev.tactic}</div>
          <div style="font-size:12px;color:#ccc;line-height:1.55;margin-top:2px">${detail}</div>
          ${leverage}
          ${frame}
        </div>
      </div>`;
    }).join("");

    return `<div class="two-col" style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div class="card">
        <div class="section-title">Customer sentiment</div>
        <div style="display:flex;flex-direction:column;gap:18px;margin-top:4px">${sentItems}</div>
      </div>
      <div class="card">
        <div class="section-title">Negotiation levers — ${winner.name}</div>
        <div style="display:flex;flex-direction:column;gap:18px;margin-top:4px">${levers}</div>
      </div>
    </div>`;
  }

  // ─── Flip scenarios ───────────────────────────────────────────────────────

  function buildFlipScenarios(result) {
    const scenarios = result.flip_scenarios || [];
    if (!scenarios.length) return "";

    const items = scenarios.map(function (s) {
      const outcome = s.then_vendor
        ? `<strong style="color:#fff">${s.then_vendor}</strong> becomes the better choice — ${s.because}`
        : (s.outcome || "");
      return `<div class="flip-item">
        <div style="width:28px;height:28px;min-width:28px;background:#1e3a5f;border-radius:7px;display:flex;align-items:center;justify-content:center;color:#4F6EF7;font-weight:700;font-size:16px;margin-top:2px">→</div>
        <div>
          <div style="font-size:13px;font-weight:600;color:#60a5fa;margin-bottom:4px">${s.condition}</div>
          <div style="font-size:13px;color:#ccc;line-height:1.6">${outcome}</div>
        </div>
      </div>`;
    }).join("");

    return `<div class="card">
      <div class="section-title">What would change this recommendation</div>
      <div style="display:flex;flex-direction:column;margin-top:4px">${items}</div>
    </div>`;
  }

  // ─── Assumption log ───────────────────────────────────────────────────────

  function buildAssumptionLog(result) {
    const assumptions = result.assumption_log || [];
    if (!assumptions.length) return "";

    const items = assumptions.map(function (a) {
      return `<div class="assumption-item">
        <div style="display:flex;justify-content:space-between;align-items:baseline">
          <span style="font-size:13px;color:#ccc;line-height:1.5;flex:1">${a.assumption}</span>
          <span class="impact-${a.impact || "medium"}" style="margin-left:12px;flex-shrink:0">${a.impact}</span>
        </div>
        ${a.how_to_verify ? `<div style="font-size:11px;color:#60a5fa;margin-top:4px;line-height:1.5">→ ${a.how_to_verify}</div>` : ""}
      </div>`;
    }).join("");

    return `<div class="card">
      <div class="section-title">Assumption log</div>
      <div style="display:flex;flex-direction:column">${items}</div>
    </div>`;
  }

  // ─── Expiry warning ───────────────────────────────────────────────────────

  function buildExpiryWarning(SESSION, result) {
    const expiresAt = SESSION.expires_at || SESSION.expires_recommendation_at;
    if (!expiresAt && !result.expiry_reason) return "";
    const expDate = expiresAt ? fmtDate(expiresAt) : "";
    const reason = result.expiry_reason || "Market conditions and pricing change regularly — review this recommendation before your next renewal.";
    return `<div class="expiry-bar">
      <div style="font-size:20px;margin-top:1px">🕐</div>
      <div>
        <div style="font-size:13px;color:#fbbf24;line-height:1.6">${reason}</div>
        ${expDate ? `<div style="font-size:11px;font-weight:700;color:#f59e0b;margin-top:5px;text-transform:uppercase;letter-spacing:.07em">Review by ${expDate}</div>` : ""}
      </div>
    </div>`;
  }

  // ─── Reorder vendor cards ─────────────────────────────────────────────────

  function reorderVendorCards(orderedNames) {
    const grid = document.getElementById("vendor-grid");
    if (!grid) return;
    const cards = orderedNames.map(function (name) {
      const id = name.toLowerCase().replace(/\s+/g, "-");
      return document.getElementById("card-" + id);
    }).filter(Boolean);
    if (!cards.length) return;

    const first = cards.map(function (c) { return c.getBoundingClientRect(); });
    cards.forEach(function (c) { grid.appendChild(c); });
    cards.forEach(function (c, i) {
      const last = c.getBoundingClientRect();
      const dx = first[i].left - last.left;
      const dy = first[i].top - last.top;
      c.style.transition = "none";
      c.style.transform = "translate(" + dx + "px," + dy + "px)";
    });
    requestAnimationFrame(function () {
      cards.forEach(function (c) {
        c.style.transition = "transform 0.3s ease";
        c.style.transform = "";
      });
    });
  }

  // ─── Wire scorer ─────────────────────────────────────────────────────────

  function patchScorerForCards(result) {
    if (!window.Scorer) return;

    const originalInit = window.Scorer.init.bind(window.Scorer);
    window.Scorer.init = function (sessionData) {
      originalInit(sessionData);
      _syncCards(result);
    };

    const rankingEl = document.getElementById("weighted-ranking");
    if (!rankingEl) return;

    const observer = new MutationObserver(function () {
      _syncCards(result);
    });
    observer.observe(rankingEl, { childList: true, subtree: false });
  }

  function _syncCards(result) {
    const scores = window.Scorer ? window.Scorer.getScores() : null;
    if (!scores) return;

    result.vendors.forEach(function (v) {
      const id = v.name.toLowerCase().replace(/\s+/g, "-");
      const score = scores[v.name];
      if (score === undefined) return;
      const weightedEl = document.getElementById("weighted-" + id);
      if (weightedEl) {
        weightedEl.textContent = score;
        weightedEl.style.color = scoreColor(score);
      }
    });

    const ranked = window.Scorer.getRanking();
    reorderVendorCards(ranked);

    result.vendors.forEach(function (v) {
      const id    = v.name.toLowerCase().replace(/\s+/g, "-");
      const card  = document.getElementById("card-" + id);
      const badge = document.getElementById("badge-" + id);
      if (!card || !badge) return;
      if (v.name === ranked[0]) {
        card.classList.add("winner");
        badge.style.display = "";
      } else {
        card.classList.remove("winner");
        badge.style.display = "none";
      }
    });
  }

  // ─── Main render ──────────────────────────────────────────────────────────

  function renderDashboard(SESSION) {
    // FIX: handle both session shapes — result nested or vendors at top level
    const result = SESSION.result || (SESSION.recommendation ? {
      ...SESSION.recommendation,
      vendors:        SESSION.vendors        || [],
      regret_analysis: SESSION.regret_analysis || {},
      slider_config:  SESSION.slider_config  || [],
      assumption_log: SESSION.assumption_log || [],
      data_gaps:      SESSION.data_gaps      || [],
      flip_scenarios: (SESSION.recommendation && SESSION.recommendation.flip_scenarios) || []
    } : SESSION);

    const profile = normalizeProfile(SESSION.profile || SESSION.decision_profile);

    const winner = (result.vendors || []).find(function (v) {
      return v.name === result.recommended_vendor || v.name === result.winner;
    }) || (result.vendors || [])[0];

    if (!winner) {
      document.getElementById("app").innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;height:100%;color:#f87171">
          Error: could not find recommended vendor in session data.
        </div>`;
      return;
    }

    document.getElementById("app").innerHTML = `
      <div style="max-width:1200px;margin:0 auto;padding:32px 24px;display:flex;flex-direction:column;gap:24px">
        ${buildHeader(SESSION, profile)}
        ${buildVerdictBar(result)}
        ${buildBiasDetector(profile, result)}
        ${buildMetricCards(result, winner, profile)}
        ${buildVendorComparison(result)}
        ${buildSliders(result)}
        ${buildRegretAndLockin(result, winner)}
        ${buildSentimentAndLevers(result, winner)}
        ${buildFlipScenarios(result)}
        ${buildAssumptionLog(result)}
        ${buildExpiryWarning(SESSION, result)}
      </div>`;

    patchScorerForCards(result);
    if (window.Scorer) {
      window.Scorer.init(result);
    } else {
      console.warn("[dashboard] scorer.js not loaded — sliders will not work");
    }
  }

  // ─── Session loading ──────────────────────────────────────────────────────

  async function loadSession() {
    const params    = new URLSearchParams(window.location.search);
    const sessionId = params.get("session_id") || params.get("session");

    let SESSION;
    if (sessionId) {
      try {
        const res = await fetch("/api/session/" + sessionId);
        if (!res.ok) throw new Error("Session not found");
        SESSION = await res.json();
      } catch (e) {
        console.error("[dashboard] Failed to load session:", e);
        SESSION = getDemoData();
      }
    } else {
      SESSION = getDemoData();
    }

    renderDashboard(SESSION);
  }

  // ─── PDF download ─────────────────────────────────────────────────────────

  window._downloadPDF = function () {
    const content = document.getElementById("app").innerHTML;
    const pw = window.open("", "_blank");
    pw.document.write(`<!DOCTYPE html><html><head>
      <title>Decisio – Vendor Report</title>
      <style>
        body { font-family: system-ui, sans-serif; padding: 24px; font-size: 12px; background: #1C1C1E; color: white; }
        * { box-shadow: none !important; }
        ${STYLES}
        .vendor-card { margin-bottom: 16px !important; break-inside: avoid; }
        @media print { body { background: #1C1C1E !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; } }
      </style>
    </head><body>${content}<script>window.onload=function(){window.print()}<\/script></body></html>`);
    pw.document.close();
  };

  // ─── Demo data ────────────────────────────────────────────────────────────

  function getDemoData() {
    return {
      session_id: "demo-001",
      created_at: "2026-05-31T09:00:00Z",
      expires_at: "2026-08-29T09:00:00Z",
      profile: {
        category: "AI API provider",
        context:  { role: "VP of Engineering" },
        budget:   { amount: 2000, currency: "USD", period: "monthly" },
        business_context: { team_size: 8, growth_rate: 20, compliance_requirements: ["SOC 2"] },
        priority: "reliability",
        must_haves:   ["SOC 2 Type II", "REST API", "Rate limit guarantees"],
        dealbreakers: ["No SOC 2", "No API SLA"],
        search_signals: { preferred_vendor: "OpenAI" }
      },
      result: {
        recommended_vendor: "Anthropic",
        confidence: "moderate",
        summary: "Anthropic is the strongest fit for your SOC 2 requirement and reliability priority, but documented rate limit issues at scale are the key risk to validate before committing given your 20% monthly growth.",
        expiry_reason: "Anthropic reprices enterprise tiers annually. Review before August 2026.",
        vendors: [
          {
            name: "Anthropic", rank: 1, overall_score: 81,
            dimension_scores: { compliance: 87, reliability: 78, pricing: 70, feature_fit: 85, lock_in_risk: 68 },
            strengths: ["SOC 2 Type II certified", "Clean API design with low proprietary abstractions"],
            red_flags: ["⚠️ Rate limit complaints at high token volumes — risk at 20% monthly growth"],
            why_not: null,
            lock_in: { level: "medium", score: 55, reasons: ["Prompt engineering tuned to Claude style may not transfer cleanly — expect 2-4 weeks rework"], exit_effort: "Moderate — prompts need rewriting, but no proprietary data formats." },
            sentiment: { positive_pct: 68, label: "Mostly positive", representative_quote: "Output quality is consistently strong; rate limits at volume are the main frustration", negative_pattern: "Rate limit throttling at scale is the dominant complaint thread", flagged_concern: "Rate limit ceiling directly conflicts with your 20% monthly growth — validate enterprise tier capacity in writing" },
            negotiation_levers: [
              { tactic: "Annual commitment for rate limit tier", ask: "Ask for committed throughput SLA with burst capacity guarantees in the contract", leverage: "Anthropic prioritises annual accounts for capacity allocation", how_to_frame: "Tell them your 20% growth means you'll hit standard limits within 90 days and need written capacity guarantees before signing" },
              { tactic: "Competitive pressure", ask: "Reference active evaluation of Gemini and Mistral", leverage: "Anthropic will move on pricing when they believe they might lose the deal", how_to_frame: "'We need to decide in two weeks and Gemini has already come back with a reserved capacity offer'" },
              { tactic: "Migration cost offset", ask: "Ask for $500-1000 in API credits to cover prompt migration cost from OpenAI", leverage: "You are switching from a competitor — Anthropic benefits from absorbing the switching cost", how_to_frame: "Position as a proof-of-concept budget: 'We need to validate at our usage volume before committing'" }
            ],
            first_90_days: "Onboarding is self-serve with strong documentation. Expect 1-2 weeks to migrate and tune prompts from OpenAI. Main early friction is hitting rate limits during load testing before enterprise tier activates.",
            data_confidence: "medium", sources_used: ["https://www.reddit.com/r/ClaudeAI"]
          },
          {
            name: "OpenAI", rank: 2, overall_score: 74,
            dimension_scores: { compliance: 82, reliability: 58, pricing: 72, feature_fit: 88, lock_in_risk: 45 },
            strengths: ["Largest model ecosystem and broadest feature set", "SOC 2 Type II and GDPR compliance well-documented"],
            red_flags: ["⚠️ Multiple documented outages in 2025 — conflicts with your reliability priority", "⚠️ Pricing unpredictability is the reason you're switching — confirmed by other enterprise users"],
            why_not: "Two documented major outages in 2025 directly conflict with your stated reliability priority, and pricing unpredictability is your current pain point with this vendor.",
            lock_in: { level: "high", score: 32, reasons: ["Proprietary function calling format not compatible with open standards", "Fine-tuned models trained via OpenAI's API are entirely non-portable"], exit_effort: "High — function calling code, fine-tuned models, and Assistants API all require significant rework." },
            sentiment: { positive_pct: 52, label: "Mixed", representative_quote: "Model quality is there but outages and pricing changes make it hard to rely on for production", negative_pattern: "Outage frequency and rate limit handling are dominant complaints in 2025", flagged_concern: "Your switching reason (pricing unpredictability) is one of the top documented complaints from current OpenAI enterprise customers" },
            negotiation_levers: [
              { tactic: "Churn threat credits", ask: "Tell them you're evaluating alternatives — they will likely offer 3-6 months of credits to retain you", leverage: "OpenAI has high churn pressure from Anthropic and Gemini", how_to_frame: "'We are pricing out Anthropic and Gemini right now — what can you offer to make staying obvious?'" },
              { tactic: "SLA with financial penalties", ask: "Request written SLA with financial penalties for downtime before any annual commitment", leverage: "Given the 2025 outage record, this is a reasonable ask", how_to_frame: "'Our procurement team requires an SLA with teeth before we can approve annual spend'" }
            ],
            first_90_days: "Onboarding is fast since you're already on the platform. The real risk is the first outage in production — have a fallback plan ready.",
            data_confidence: "high", sources_used: ["https://community.openai.com/t/openai-2-26-2025-has-outages-and-is-actively-investigating/1130186"]
          },
          {
            name: "Google Gemini", rank: 3, overall_score: 71,
            dimension_scores: { compliance: 80, reliability: 70, pricing: 82, feature_fit: 75, lock_in_risk: 60 },
            strengths: ["Flash-Lite pricing well below your $2k/month budget even at high volume", "Google infrastructure delivers strong uptime track record"],
            red_flags: ["Enterprise compliance documentation less established than OpenAI or Anthropic", "API surface changed significantly in 2024-2025 — stability risk for production integrations"],
            why_not: "Pricing is the strongest suit, but compliance documentation trail is thinner and API stability concerns make it a higher-risk choice for a SOC 2 requirement.",
            lock_in: { level: "medium", score: 52, reasons: ["Google has a documented history of deprecating developer products", "Gemini-specific multimodal features have no direct equivalent at other providers"], exit_effort: "Moderate — core text API is relatively portable, but Google-specific features are not." },
            sentiment: { positive_pct: 61, label: "Mixed", representative_quote: "Pricing is genuinely competitive but enterprise support is inconsistent compared to Anthropic", negative_pattern: "Enterprise support quality and response times are the primary complaints", flagged_concern: "Compliance documentation depth is below your SOC 2 standard — requires explicit verification" },
            negotiation_levers: [
              { tactic: "GCP bundle deal", ask: "Ask for Gemini API costs to be offset against Google Cloud Platform credits", leverage: "Google wants GCP wallet share — Gemini API is a wedge product", how_to_frame: "'We are evaluating consolidating on GCP — can you show us what the bundled economics look like?'" }
            ],
            first_90_days: "API integration is straightforward but enterprise support onboarding can be slow — expect 2-4 weeks to get a named account contact.",
            data_confidence: "medium", sources_used: []
          },
          {
            name: "Cohere", rank: 4, overall_score: 58,
            dimension_scores: { compliance: 72, reliability: 60, pricing: 68, feature_fit: 62, lock_in_risk: 55 },
            strengths: ["Best-in-class RAG and embedding capabilities", "Enterprise compliance focus with dedicated documentation"],
            red_flags: ["⚠️ Significantly smaller ecosystem — community support and third-party integrations are limited", "General-purpose model capability lags OpenAI and Anthropic for non-RAG tasks"],
            why_not: "Cohere is well-suited to enterprise RAG use cases, but for general API usage your team would take on meaningful migration effort for a vendor with a smaller support ecosystem.",
            lock_in: { level: "medium", score: 48, reasons: ["Proprietary embedding models are not interchangeable — retrieval infrastructure must be re-indexed to switch", "Smaller ecosystem means more custom code required"], exit_effort: "Moderate to high for RAG use cases. For pure completion use cases, migration is standard effort." },
            sentiment: { positive_pct: 58, label: "Mixed", representative_quote: "Excellent for enterprise RAG but general completions feel like a step behind the bigger players", negative_pattern: "Capability gap versus OpenAI and Anthropic on general tasks is the consistent criticism", flagged_concern: null },
            negotiation_levers: [
              { tactic: "Proof of concept credits", ask: "Ask for a 90-day proof-of-concept period with full credits before any commitment", leverage: "They are competing hard against larger providers and will absorb POC costs to win enterprise accounts", how_to_frame: "'We need to validate performance at production scale before we can justify switching — can you support a funded POC?'" }
            ],
            first_90_days: "Onboarding support is hands-on — they typically assign a solutions engineer for enterprise accounts.",
            data_confidence: "low", sources_used: []
          },
          {
            name: "Mistral", rank: 5, overall_score: 54,
            dimension_scores: { compliance: 60, reliability: 58, pricing: 75, feature_fit: 58, lock_in_risk: 78 },
            strengths: ["Open-weight models eliminate vendor dependency — self-hosting gives full control", "Lowest lock-in risk of any vendor evaluated"],
            red_flags: ["⚠️ SOC 2 compliance documentation for cloud API is not clearly established — direct dealbreaker", "Smaller infrastructure team — reliability at enterprise scale is less proven"],
            why_not: "Mistral's open-weight model is compelling for lock-in avoidance, but unconfirmed SOC 2 status is a direct dealbreaker match given your compliance requirement.",
            lock_in: { level: "low", score: 78, reasons: ["Open-weight models can be downloaded and self-hosted", "API format follows open standards — switching requires minimal code changes"], exit_effort: "Low — open-weight models are portable and the API design minimises vendor-specific patterns." },
            sentiment: { positive_pct: 55, label: "Mixed", representative_quote: "Great for teams who want to avoid lock-in but enterprise readiness is not there yet", negative_pattern: "Enterprise readiness gaps (compliance, support SLAs, reliability guarantees) are the consistent criticism", flagged_concern: "SOC 2 compliance status for cloud API is unconfirmed — this is a direct dealbreaker" },
            negotiation_levers: [
              { tactic: "Self-hosting leverage", ask: "Use the self-hosting option as negotiating leverage even if you don't plan to self-host", leverage: "If you can self-host, Mistral's cloud offering has no captive audience", how_to_frame: "'We are evaluating cloud versus self-hosted — what would make cloud the obvious choice?'" }
            ],
            first_90_days: "Self-hosted setup requires 2-4 weeks of infrastructure work. Cloud API onboarding is fast but enterprise support is limited.",
            data_confidence: "low", sources_used: []
          }
        ],
        regret_analysis: {
          score: 62, label: "Moderate risk", vendor: "Anthropic", score_gap: 7,
          score_gap_note: "Anthropic leads OpenAI by 7 points overall, but this gap narrows significantly on features (85 vs 88).",
          main_risk: "Rate limit ceiling at 20% monthly growth",
          reasons: [
            "Documented rate limit complaints at high token volumes — at 20% monthly growth you will likely hit enterprise tier thresholds within 3-4 months",
            "Enterprise rate limit tiers and burst capacity guarantees are not published — committing without knowing the ceiling creates the same pricing unpredictability you are switching away from",
            "If Anthropic cannot provide committed capacity in writing, you may face an urgent mid-growth migration"
          ],
          mitigation: "Before signing, request a written enterprise throughput SLA with specific burst capacity guarantees."
        },
        flip_scenarios: [
          { condition: "If your monthly growth rate drops below 5% or usage stabilises", then_vendor: "OpenAI", because: "Rate limit risk disappears at stable volume and OpenAI's broader feature set becomes the differentiating factor" },
          { condition: "If SOC 2 compliance requirement is removed or downgraded", then_vendor: "Mistral", because: "Lock-in risk becomes the dominant factor and Mistral's open-weight model is the strongest answer" },
          { condition: "If budget increases above $4k/month and GCP consolidation is on the roadmap", then_vendor: "Google Gemini", because: "Bundled GCP pricing makes Gemini significantly cheaper at scale" }
        ],
        slider_config: [
          { id: "reliability",  label: "Reliability priority",  dimension: "reliability",  default_weight: 40, description: "Increasing this favours vendors with stronger uptime records — pushes OpenAI down due to 2025 outages" },
          { id: "compliance",   label: "Compliance strictness", dimension: "compliance",   default_weight: 30, description: "Increasing this favours vendors with stronger SOC 2 documentation — eliminates Mistral at high values" },
          { id: "feature_fit",  label: "Feature depth",         dimension: "feature_fit",  default_weight: 20, description: "Increasing this narrows the gap between Anthropic and OpenAI — OpenAI leads on raw feature breadth" },
          { id: "lock_in_risk", label: "Avoid lock-in",         dimension: "lock_in_risk", default_weight: 10, description: "Increasing this significantly boosts Mistral and penalises OpenAI" }
        ],
        assumption_log: [
          { assumption: "Anthropic's SOC 2 Type II certification covers your specific data processing use case and jurisdiction", impact: "high", how_to_verify: "Request the full SOC 2 report from trust.anthropic.com and share with your compliance team before signing" },
          { assumption: "Your usage estimate is accurate — actual token consumption may be significantly higher once integrated at scale", impact: "medium", how_to_verify: "Pull actual token logs from your current OpenAI usage dashboard and calculate a 6-month projection" },
          { assumption: "Anthropic can provide enterprise rate limit tiers sufficient for your growth trajectory", impact: "high", how_to_verify: "Ask Anthropic sales directly: 'What is the committed throughput limit at enterprise tier and what is the burst capacity policy?'" }
        ],
        data_gaps: []
      }
    };
  }

  // ─── Boot ─────────────────────────────────────────────────────────────────

  loadSession();

})();