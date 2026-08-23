/**
 * DataOS — Modern Technical Web Workspace Application.
 * Consumes the API-First DataOS backend endpoints.
 */

const API_BASE = "";

// Global App State
const state = {
  activeTab: "objects",
  objects: [],
  relationships: [],
  health: null,
  selectedObject: null,
  graphNodes: [],
  graphEdges: []
};

// DOM Content Loaded Initializer
document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  loadSystemData();
  setupEventListeners();
});

// Navigation Handling
function initNavigation() {
  const navItems = document.querySelectorAll(".nav-item[data-tab]");
  navItems.forEach(item => {
    item.addEventListener("click", () => {
      const tab = item.getAttribute("data-tab");
      switchTab(tab);
    });
  });
}

function switchTab(tabName) {
  state.activeTab = tabName;
  document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".workspace-panel").forEach(el => el.classList.remove("active"));

  const activeNav = document.querySelector(`.nav-item[data-tab="${tabName}"]`);
  if (activeNav) activeNav.classList.add("active");

  const activePanel = document.getElementById(`panel-${tabName}`);
  if (activePanel) activePanel.classList.add("active");

  // Trigger tab-specific refresh
  if (tabName === "graph") {
    loadGraphVisualizer();
  } else if (tabName === "catalog") {
    loadCatalogView();
  } else if (tabName === "objects") {
    loadObjectsList();
  }
}

// Initial System Data Load
async function loadSystemData() {
  try {
    const [healthRes, objsRes, relsRes] = await Promise.all([
      fetch(`${API_BASE}/api/catalog/health`).then(r => r.json()),
      fetch(`${API_BASE}/api/objects/?limit=100`).then(r => r.json()),
      fetch(`${API_BASE}/api/relationships/?limit=100`).then(r => r.json())
    ]);

    state.health = healthRes;
    state.objects = objsRes.objects || [];
    state.relationships = relsRes.relationships || [];

    updateHeaderMetrics();
    renderObjectsTable();
    populateObjectSelects();
  } catch (err) {
    console.error("Failed to load initial system data:", err);
  }
}

function updateHeaderMetrics() {
  if (!state.health) return;
  document.getElementById("metric-objects-count").textContent = state.health.total_objects || state.objects.length;
  document.getElementById("metric-rels-count").textContent = state.health.total_relationships || state.relationships.length;
  document.getElementById("metric-health-score").textContent = `${state.health.data_health_score || 100}% (Grade ${state.health.health_grade || 'A'})`;
}

// =============================================================================
// OBJECTS WORKSPACE
// =============================================================================

async function loadObjectsList() {
  const typeFilter = document.getElementById("object-filter-type").value;
  let url = `${API_BASE}/api/objects/?limit=100`;
  if (typeFilter) url += `&object_type=${encodeURIComponent(typeFilter)}`;
  
  try {
    const res = await fetch(url).then(r => r.json());
    state.objects = res.objects || [];
    renderObjectsTable();
  } catch (e) {
    console.error(e);
  }
}

function renderObjectsTable() {
  const tbody = document.getElementById("objects-table-body");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (state.objects.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:2rem;">No DataOS objects in storage. Ingest sample data to get started.</td></tr>`;
    return;
  }

  state.objects.forEach(obj => {
    const tr = document.createElement("tr");
    const filename = obj.properties.filename || obj.properties.title || "—";
    const typeBadge = `<span class="type-badge ${obj.type}">${obj.type}</span>`;
    
    tr.innerHTML = `
      <td><code>${obj.id.slice(0, 8)}...</code></td>
      <td>${typeBadge}</td>
      <td><strong>${escapeHtml(filename)}</strong></td>
      <td><code>${obj.schema}</code></td>
      <td>v${obj.version}</td>
      <td>
        <button class="dataos-btn btn-secondary" style="padding:0.25rem 0.6rem; font-size:0.75rem;" onclick="inspectObject('${obj.id}')">Inspect</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function inspectObject(objId) {
  const obj = state.objects.find(o => o.id === objId);
  if (!obj) return;
  state.selectedObject = obj;

  document.getElementById("inspector-title").textContent = `Object: ${obj.properties.filename || obj.id}`;
  document.getElementById("inspector-json").textContent = JSON.stringify(obj, null, 2);
  document.getElementById("inspector-modal").style.display = "block";
}

function closeInspector() {
  document.getElementById("inspector-modal").style.display = "none";
}

// =============================================================================
// INTERACTIVE GRAPH VISUALIZER
// =============================================================================

function loadGraphVisualizer() {
  const canvas = document.getElementById("graphCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  // Resize canvas to fit container
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width;
  canvas.height = 540;

  // Build nodes and edges
  const nodes = state.objects.map((obj, i) => ({
    id: obj.id,
    label: obj.properties.filename || obj.properties.title || obj.id.slice(0, 8),
    type: obj.type,
    x: (canvas.width / 2) + Math.cos(i * (2 * Math.PI / Math.max(1, state.objects.length))) * 180 + (Math.random() * 40 - 20),
    y: (canvas.height / 2) + Math.sin(i * (2 * Math.PI / Math.max(1, state.objects.length))) * 180 + (Math.random() * 40 - 20),
    vx: 0,
    vy: 0,
    radius: obj.type === "dataset" ? 18 : 14
  }));

  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const edges = state.relationships
    .filter(r => nodeMap.has(r.source) && nodeMap.has(r.target))
    .map(r => ({
      source: nodeMap.get(r.source),
      target: nodeMap.get(r.target),
      type: r.relation_type,
      confidence: r.confidence
    }));

  state.graphNodes = nodes;
  state.graphEdges = edges;

  // Simple Spring Simulation Loop
  let animId;
  function animate() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw Edges
    edges.forEach(e => {
      ctx.beginPath();
      ctx.moveTo(e.source.x, e.source.y);
      ctx.lineTo(e.target.x, e.target.y);
      ctx.strokeStyle = "rgba(106, 155, 204, 0.4)";
      ctx.lineWidth = Math.max(1, e.confidence * 2);
      ctx.stroke();

      // Edge Label
      const midX = (e.source.x + e.target.x) / 2;
      const midY = (e.source.y + e.target.y) / 2;
      ctx.fillStyle = "rgba(176, 174, 165, 0.7)";
      ctx.font = "9px monospace";
      ctx.fillText(e.type, midX, midY);
    });

    // Draw Nodes
    nodes.forEach(n => {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
      if (n.type === "dataset") ctx.fillStyle = "#788c5d";
      else if (n.type === "document") ctx.fillStyle = "#d97757";
      else if (n.type === "code") ctx.fillStyle = "#f0ad4e";
      else ctx.fillStyle = "#6a9bcc";
      ctx.fill();
      ctx.strokeStyle = "#1e1e26";
      ctx.lineWidth = 2;
      ctx.stroke();

      // Label
      ctx.fillStyle = "#faf9f5";
      ctx.font = "11px -apple-system, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(n.label.slice(0, 18), n.x, n.y + n.radius + 14);
    });
  }

  animate();
}

// =============================================================================
// QUERY & COMPUTATION RUNNERS
// =============================================================================

async function runSQLQuery() {
  const query = document.getElementById("sql-query-input").value;
  const resultContainer = document.getElementById("sql-result-output");
  resultContainer.innerHTML = `<span style="color:var(--text-muted);">Executing query...</span>`;

  try {
    const res = await fetch(`${API_BASE}/api/compute/sql`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query })
    }).then(r => r.json());

    if (!res.success) {
      resultContainer.innerHTML = `<div style="color:var(--state-error); font-family:var(--font-mono);">Error: ${escapeHtml(res.error)}</div>`;
      return;
    }

    if (res.rows.length === 0) {
      resultContainer.innerHTML = `<div style="color:var(--text-muted);">Query executed successfully. 0 rows returned (${res.execution_time_ms} ms).</div>`;
      return;
    }

    // Build Table
    let html = `<div style="margin-bottom:0.5rem; font-size:0.8rem; color:var(--text-muted);">Executed in <strong>${res.execution_time_ms} ms</strong>. Returned <strong>${res.row_count}</strong> rows.</div>`;
    html += `<div class="dataos-table-wrapper"><table class="dataos-table"><thead><tr>`;
    res.columns.forEach(c => html += `<th>${escapeHtml(c)}</th>`);
    html += `</tr></thead><tbody>`;
    res.rows.forEach(row => {
      html += `<tr>`;
      res.columns.forEach(c => html += `<td>${escapeHtml(String(row[c]))}</td>`);
      html += `</tr>`;
    });
    html += `</tbody></table></div>`;
    resultContainer.innerHTML = html;
  } catch (err) {
    resultContainer.innerHTML = `<div style="color:var(--state-error);">Network error: ${err.message}</div>`;
  }
}

async function runPythonCode() {
  const code = document.getElementById("python-code-input").value;
  const outputEl = document.getElementById("python-result-output");
  outputEl.textContent = "Executing Python sandbox...";

  try {
    const res = await fetch(`${API_BASE}/api/compute/python`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: code })
    }).then(r => r.json());

    outputEl.textContent = JSON.stringify(res, null, 2);
  } catch (err) {
    outputEl.textContent = `Error: ${err.message}`;
  }
}

async function runUnifiedNLQuery() {
  const query = document.getElementById("nl-query-input").value;
  const outputEl = document.getElementById("nl-result-output");
  outputEl.innerHTML = `<span style="color:var(--text-muted);">Grounding query against data graph...</span>`;

  try {
    const res = await fetch(`${API_BASE}/api/query/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query, query_type: "natural_language" })
    }).then(r => r.json());

    let html = `<div style="margin-bottom:1rem; font-size:1.05rem; font-weight:600; color:var(--text-primary);">${escapeHtml(res.grounded_answer || "Query Grounded")}</div>`;

    if (res.claims && res.claims.length > 0) {
      html += `<div style="font-weight:600; font-size:0.85rem; color:var(--accent-primary); margin-bottom:0.5rem;">VERIFIED CLAIMS:</div>`;
      res.claims.forEach(claim => {
        html += `<div class="proof-card"><div class="proof-claim">✓ ${escapeHtml(claim)}</div></div>`;
      });
    }

    if (res.evidence && res.evidence.length > 0) {
      html += `<div style="font-weight:600; font-size:0.85rem; color:var(--accent-blue); margin:1rem 0 0.5rem;">SUPPORTING EVIDENCE:</div>`;
      html += `<pre class="code-preview">${escapeHtml(JSON.stringify(res.evidence, null, 2))}</pre>`;
    }

    outputEl.innerHTML = html;
  } catch (err) {
    outputEl.innerHTML = `<div style="color:var(--state-error);">Error: ${err.message}</div>`;
  }
}

// =============================================================================
// PROFILING & QUALITY WORKSPACE
// =============================================================================

async function runDatasetProfile() {
  const select = document.getElementById("profiler-object-select");
  const objId = select.value;
  const outputEl = document.getElementById("profiler-result-output");
  if (!objId) return;

  outputEl.innerHTML = `<span style="color:var(--text-muted);">Computing verified profile...</span>`;

  try {
    const res = await fetch(`${API_BASE}/api/profiling/${objId}`).then(r => r.json());
    if (res.detail) {
      outputEl.innerHTML = `<div style="color:var(--state-error);">${res.detail}</div>`;
      return;
    }

    let html = `
      <div class="grid-4" style="margin-bottom:1.25rem;">
        <div class="stat-card"><div class="stat-label">Rows</div><div class="stat-value">${res.row_count}</div></div>
        <div class="stat-card"><div class="stat-label">Columns</div><div class="stat-value">${res.column_count}</div></div>
        <div class="stat-card"><div class="stat-label">Completeness</div><div class="stat-value">${(res.completeness_ratio * 100).toFixed(1)}%</div></div>
        <div class="stat-card"><div class="stat-label">Numeric Cols</div><div class="stat-value">${res.numeric_columns.length}</div></div>
      </div>
    `;

    html += `<div class="card-title">Column Statistics & Distributions</div>`;
    html += `<div class="dataos-table-wrapper"><table class="dataos-table"><thead><tr>
      <th>Column</th><th>Type</th><th>Null Ratio</th><th>Unique</th><th>Mean</th><th>Median</th><th>Std</th><th>Outliers</th>
    </tr></thead><tbody>`;

    for (const [colName, meta] of Object.entries(res.columns)) {
      html += `<tr>
        <td><strong>${escapeHtml(colName)}</strong></td>
        <td><code>${meta.dtype}</code></td>
        <td>${(meta.null_ratio * 100).toFixed(1)}%</td>
        <td>${meta.unique_count}</td>
        <td>${meta.mean !== undefined ? meta.mean : "—"}</td>
        <td>${meta.median !== undefined ? meta.median : "—"}</td>
        <td>${meta.std !== undefined ? meta.std : "—"}</td>
        <td>${meta.outlier_count !== undefined ? meta.outlier_count : "—"}</td>
      </tr>`;
    }
    html += `</tbody></table></div>`;

    outputEl.innerHTML = html;
  } catch (err) {
    outputEl.innerHTML = `<div style="color:var(--state-error);">Error: ${err.message}</div>`;
  }
}

// =============================================================================
// INGESTION & IMPORT WORKSPACE
// =============================================================================

async function runTextIngest() {
  const filename = document.getElementById("ingest-filename").value;
  const content = document.getElementById("ingest-content").value;
  const outputEl = document.getElementById("ingest-result-output");

  if (!filename || !content) {
    alert("Please provide both filename and content.");
    return;
  }

  outputEl.innerHTML = `<span style="color:var(--text-muted);">Ingesting file and extracting relations...</span>`;

  try {
    const formData = new FormData();
    formData.append("filename", filename);
    formData.append("content", content);

    const res = await fetch(`${API_BASE}/api/io/ingest_text`, {
      method: "POST",
      body: formData
    }).then(r => r.json());

    outputEl.innerHTML = `<div style="color:var(--state-success); font-weight:600; margin-bottom:0.5rem;">✓ Ingestion successful! Object ID: <code>${res.object_id}</code></div>
    <div style="font-size:0.85rem; color:var(--text-muted); margin-bottom:0.75rem;">Discovered <strong>${res.relationships_discovered_count}</strong> automatic relationships.</div>
    <pre class="code-preview">${escapeHtml(JSON.stringify(res, null, 2))}</pre>`;

    // Refresh state
    loadSystemData();
  } catch (err) {
    outputEl.innerHTML = `<div style="color:var(--state-error);">Error: ${err.message}</div>`;
  }
}

// Ingest Predefined Rule #72 Sample Set
async function ingestScenarioSample(type) {
  if (type === "students_csv") {
    document.getElementById("ingest-filename").value = "students.csv";
    document.getElementById("ingest-content").value = `student_id,name,gpa,major,email\n101,Alice Smith,3.85,Computer Science,alice@univ.edu\n102,Bob Jones,3.42,Data Science,bob@univ.edu\n103,Charlie Brown,3.91,Mathematics,charlie@univ.edu\n104,Diana Prince,3.78,Computer Science,diana@univ.edu\n105,Evan Wright,2.95,Economics,evan@univ.edu`;
  } else if (type === "research_notes_md") {
    document.getElementById("ingest-filename").value = "research_notes.md";
    document.getElementById("ingest-content").value = `# Statistical Analysis of Academic Performance\n\n## Overview\nThis paper examines GPA distributions from [students.csv](file://students.csv).\n\n## Citations\n[1] Smith et al., 2024. University Data Systems.\n\n## Observations\nStudents in Computer Science show high mean GPA.`;
  } else if (type === "analysis_py") {
    document.getElementById("ingest-filename").value = "gpa_analysis.py";
    document.getElementById("ingest-content").value = `import pandas as pd\n\ndef compute_metrics():\n    df = pd.read_csv('students.csv')\n    print("Average GPA:", df['gpa'].mean())\n\ncompute_metrics()`;
  }
}

// =============================================================================
// CATALOG & HEALTH
// =============================================================================

async function loadCatalogView() {
  const container = document.getElementById("catalog-summary-content");
  if (!container) return;
  try {
    const res = await fetch(`${API_BASE}/api/catalog/health`).then(r => r.json());
    container.innerHTML = `<pre class="code-preview">${escapeHtml(JSON.stringify(res, null, 2))}</pre>`;
  } catch (err) {
    container.innerHTML = `Error: ${err.message}`;
  }
}

// Populate Select Dropdowns with Datasets
function populateObjectSelects() {
  const profilerSelect = document.getElementById("profiler-object-select");
  if (!profilerSelect) return;
  profilerSelect.innerHTML = "";

  const datasets = state.objects.filter(o => o.type === "dataset" || o.type === "file");
  datasets.forEach(d => {
    const opt = document.createElement("option");
    opt.value = d.id;
    opt.textContent = `${d.properties.filename || d.id} (${d.type})`;
    profilerSelect.appendChild(opt);
  });
}

function setupEventListeners() {
  // Search Bar Filter
  const searchInput = document.getElementById("global-search-input");
  if (searchInput) {
    searchInput.addEventListener("keyup", (e) => {
      if (e.key === "Enter") {
        const q = searchInput.value;
        if (q) {
          switchTab("query");
          document.getElementById("nl-query-input").value = q;
          runUnifiedNLQuery();
        }
      }
    });
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
