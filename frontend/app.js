const API_BASE = window.API_BASE || "/api";

const themeToggle = document.getElementById("themeToggle");
const themeIcon = document.getElementById("themeIcon");

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  themeIcon.textContent = theme === "dark" ? "☀️" : "🌙";
  localStorage.setItem("steppy-theme", theme);
}

(function initTheme() {
  const saved = localStorage.getItem("steppy-theme") || localStorage.getItem("stl2step-theme");
  if (saved) {
    applyTheme(saved);
  } else {
    applyTheme(window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
})();

themeToggle.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme");
  applyTheme(current === "dark" ? "light" : "dark");
});

function viewerUnavailable(container, msg) {
  container.innerHTML =
    `<p style="padding:16px;color:var(--text-muted);font-size:13px;">${msg}</p>`;
}

function createSTLViewer(container, arrayBuffer, opts = {}) {
  if (typeof THREE === "undefined" || !THREE.STLLoader || !THREE.OrbitControls) {
    console.error("steppy: THREE.js / STLLoader / OrbitControls not available");
    viewerUnavailable(container, "3D preview unavailable (viewer library didn't load) — conversion still works, this is just the picture.");
    return null;
  }

  let geometry;
  try {
    geometry = new THREE.STLLoader().parse(arrayBuffer);
  } catch (err) {
    console.error("steppy: failed to parse STL for preview", err);
    viewerUnavailable(container, "Couldn't render a preview of this file.");
    return null;
  }

  container.innerHTML = "";
  const width = container.clientWidth || 320;
  const height = container.clientHeight || 220;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100000);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(width, height);
  container.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
  dirLight.position.set(1, 1, 1);
  scene.add(dirLight);

  geometry.computeBoundingBox();
  geometry.computeVertexNormals();

  const material = new THREE.MeshStandardMaterial({
    color: opts.color || 0x4f5eff,
    flatShading: true,
    side: THREE.DoubleSide,
  });
  const mesh = new THREE.Mesh(geometry, material);

  const box = geometry.boundingBox;
  const center = new THREE.Vector3();
  box.getCenter(center);
  mesh.position.sub(center);
  scene.add(mesh);

  const size = new THREE.Vector3();
  box.getSize(size);
  const diag = size.length();

  const dist = diag * 1.5;
  camera.position.set(dist, dist, dist);
  camera.lookAt(0, 0, 0);

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  let alive = true;
  (function animate() {
    if (!alive) return;
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  })();

  return {
    diag,
    dispose() {
      alive = false;
      controls.dispose();
      renderer.dispose();
      geometry.dispose();
      material.dispose();
      container.innerHTML = "";
    },
  };
}

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const previewEl = document.getElementById("preview");
const convertBtn = document.getElementById("convertBtn");

let selectedFile = null;
let inputViewer = null;

function updateConvertButtonState() {
  convertBtn.disabled = !selectedFile;
}

window.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("dragover");
});
window.addEventListener("dragleave", (e) => {
  if (!e.relatedTarget) dropzone.classList.remove("dragover");
});
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer && e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});

dropzone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", (e) => {
  if (e.target.files.length) handleFile(e.target.files[0]);
});

function handleFile(file) {
  if (!file.name.toLowerCase().endsWith(".stl")) {
    alert("Please choose a .stl file");
    return;
  }
  selectedFile = file;
  updateConvertButtonState();
  previewEl.classList.remove("hidden");

  const reader = new FileReader();
  reader.onload = (event) => {
    requestAnimationFrame(() => {
      if (inputViewer) inputViewer.dispose();
      inputViewer = createSTLViewer(previewEl, event.target.result);
    });
  };
  reader.readAsArrayBuffer(file);
}

const jobList = document.getElementById("jobList");
let firstJobRendered = false;
const MODE = "faceted";

convertBtn.addEventListener("click", () => startConversion());

async function startConversion() {
  if (!selectedFile || convertBtn.disabled) return;

  const form = new FormData();
  form.append("file", selectedFile);

  convertBtn.disabled = true;
  convertBtn.textContent = "Uploading…";

  try {
    const res = await fetch(`${API_BASE}/convert`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const displayName = (data.output_names && data.output_names[MODE]) || selectedFile.name;
    addJobCard(data.job_id, displayName, [MODE]);
    pollJob(data.job_id);
  } catch (err) {
    alert("Upload failed: " + err.message);
  } finally {
    updateConvertButtonState();
    convertBtn.textContent = "Convert";
  }
}

function confirmDelete(message) {
  if (localStorage.getItem("steppy-skip-delete-confirm") === "yes") return true;
  if (!confirm(message)) return false;
  if (confirm("Got it. Stop asking for confirmation when deleting jobs from now on?")) {
    localStorage.setItem("steppy-skip-delete-confirm", "yes");
  }
  return true;
}

const clearJobsBtn = document.getElementById("clearJobsBtn");
clearJobsBtn.addEventListener("click", async () => {
  if (!confirmDelete("Delete all completed jobs and their files? This can't be undone.")) {
    return;
  }
  try {
    const res = await fetch(`${API_BASE}/jobs`, { method: "DELETE" });
    if (!res.ok) throw new Error(await res.text());
    Object.values(jobPreviewViewers).forEach((v) => v.dispose());
    for (const k in jobPreviewViewers) delete jobPreviewViewers[k];
    jobList.innerHTML = '<p class="empty-state">Converted files will show up here.</p>';
    firstJobRendered = false;
  } catch (err) {
    alert("Failed to clear jobs: " + err.message);
  }
});

async function deleteJob(jobId) {
  if (!confirmDelete("Delete this job and its files? This can't be undone.")) return;
  try {
    const res = await fetch(`${API_BASE}/jobs/${jobId}`, { method: "DELETE" });
    if (res.status === 409) {
      alert("This job is still converting — wait for it to finish first.");
      return;
    }
    if (!res.ok) throw new Error(await res.text());
    for (const key of Object.keys(jobPreviewViewers)) {
      if (key.startsWith(`${jobId}/`)) {
        jobPreviewViewers[key].dispose();
        delete jobPreviewViewers[key];
      }
    }
    const card = document.getElementById(`job-${jobId}`);
    if (card) card.remove();
    if (!jobList.querySelector(".job-card")) {
      jobList.innerHTML = '<p class="empty-state">Converted files will show up here.</p>';
      firstJobRendered = false;
    }
  } catch (err) {
    alert("Failed to delete job: " + err.message);
  }
}

const jobPreviewViewers = {};

function closeJobPreview(jobId, mode) {
  const card = document.getElementById(`job-${jobId}`);
  if (!card) return;
  const holder = card.querySelector(`.job-preview[data-mode="${mode}"]`);
  const key = `${jobId}/${mode}`;
  if (jobPreviewViewers[key]) {
    jobPreviewViewers[key].dispose();
    delete jobPreviewViewers[key];
  }
  if (holder) holder.remove();
  const btn = card.querySelector(`.preview-btn[data-mode="${mode}"]`);
  if (btn) btn.textContent = "Preview";
}

async function openJobPreview(jobId, mode) {
  const card = document.getElementById(`job-${jobId}`);
  if (!card) return;
  if (card.querySelector(`.job-preview[data-mode="${mode}"]`)) return;
  const btn = card.querySelector(`.preview-btn[data-mode="${mode}"]`);
  if (btn) btn.textContent = "Loading…";
  try {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/preview/${mode}`);
    if (!res.ok) throw new Error(await res.text());
    const buf = await res.arrayBuffer();

    const holder = document.createElement("div");
    holder.className = "job-preview";
    holder.dataset.mode = mode;
    card.appendChild(holder);

    const viewer = createSTLViewer(holder, buf, { color: 0x34c98e });
    if (viewer) jobPreviewViewers[`${jobId}/${mode}`] = viewer;
    if (btn) btn.textContent = "Hide preview";
  } catch (err) {
    if (btn) btn.textContent = "Preview";
    console.error("steppy: couldn't load output preview", err);
  }
}

jobList.addEventListener("click", (e) => {
  const closeBtn = e.target.closest(".card-close");
  if (closeBtn) {
    deleteJob(closeBtn.dataset.job);
    return;
  }
  const btn = e.target.closest(".preview-btn");
  if (!btn) return;
  const jobId = btn.dataset.job;
  const mode = btn.dataset.mode;
  const card = document.getElementById(`job-${jobId}`);
  const isOpen = !!card.querySelector(`.job-preview[data-mode="${mode}"]`);
  if (isOpen) {
    closeJobPreview(jobId, mode);
  } else {
    openJobPreview(jobId, mode);
  }
});

function addJobCard(jobId, filename, modes) {
  if (!firstJobRendered) {
    jobList.innerHTML = "";
    firstJobRendered = true;
  }
  const card = document.createElement("div");
  card.className = "job-card";
  card.id = `job-${jobId}`;
  card.innerHTML = `
    <div class="job-card-header">
      <span class="job-filename">${escapeHtml(filename)}</span>
      <span class="job-header-right">
        <span class="job-status status-queued">queued</span>
        <button class="card-close" data-job="${jobId}" title="Delete this job and its files">✕</button>
      </span>
    </div>
    <div class="job-body"><span class="mode-detail">Waiting to start…</span></div>
  `;
  jobList.prepend(card);
}

async function pollJob(jobId) {
  const card = document.getElementById(`job-${jobId}`);
  try {
    const res = await fetch(`${API_BASE}/jobs/${jobId}`);
    const job = await res.json();
    renderJob(card, job);
    if (job.status === "queued" || job.status === "running") {
      setTimeout(() => pollJob(jobId), 2000);
    }
  } catch (err) {
    setTimeout(() => pollJob(jobId), 3000);
  }
}

function renderJob(card, job, autoPreview = true) {
  const statusEl = card.querySelector(".job-status");
  statusEl.textContent = job.status;
  statusEl.className = `job-status status-${job.status}`;

  if (job.output_names && job.modes.length) {
    const nameEl = card.querySelector(".job-filename");
    if (nameEl) nameEl.textContent = job.output_names[job.modes[0]] || job.filename;
  }

  const body = card.querySelector(".job-body");
  if (job.status === "failed") {
    body.innerHTML = `<span class="mode-detail" style="color:var(--danger)">${escapeHtml(job.error || "conversion failed")}</span>`;
    return;
  }
  if (job.status !== "done" || !job.report) {
    body.innerHTML = `<span class="mode-detail">Repairing mesh and fitting surfaces…</span>`;
    return;
  }

  const report = job.report;
  let html = "";
  for (const mode of job.modes) {
    const r = report.modes[mode] || {};
    if (r.error) {
      html += `<div class="mode-result"><span class="mode-name">${mode}</span><span class="mode-detail" style="color:var(--danger)">${escapeHtml(r.error)}</span></div>`;
      continue;
    }
    let detail = r.is_closed_solid ? "closed solid" : "open shell";
    if (r.body_count > 1) detail = `${r.body_count} bodies, ` + detail;
    if (r.faces_after_merge != null && r.triangle_count != null && r.faces_after_merge < r.triangle_count) {
      detail = `${r.faces_after_merge} faces (merged from ${r.triangle_count} triangles), ` + detail;
    }
    const previewBtn = r.preview
      ? `<button class="preview-btn ghost-btn" data-job="${job.id}" data-mode="${mode}">Preview</button>`
      : "";
    html += `
      <div class="mode-result">
        <span class="mode-detail">${detail}</span>
        <span class="mode-actions">
          ${previewBtn}
          <a class="download-link" href="${API_BASE}/jobs/${job.id}/download/${mode}">Download STEP</a>
        </span>
      </div>`;
  }
  body.innerHTML = html;

  if (autoPreview) {
    for (const mode of job.modes) {
      const r = report.modes[mode] || {};
      if (r.preview) openJobPreview(job.id, mode);
    }
  }
}

(async function loadHistory() {
  try {
    const res = await fetch(`${API_BASE}/jobs`);
    if (!res.ok) return;
    const history = await res.json();
    for (const job of [...history].reverse()) {
      if (document.getElementById(`job-${job.id}`)) continue;
      const name = (job.output_names && job.output_names[job.modes[0]]) || job.filename;
      addJobCard(job.id, name, job.modes);
      const card = document.getElementById(`job-${job.id}`);
      renderJob(card, job, false);
      if (job.status === "queued" || job.status === "running") pollJob(job.id);
    }
  } catch (err) {
    console.warn("steppy: couldn't load job history", err);
  }
})();

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
