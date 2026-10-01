/**
 * CampusCare — Frontend Application Controller
 * Handles report submission, live search, filtering, statistics,
 * drag-and-drop file upload, submission progress timeline, and modals.
 */

(function () {
  "use strict";

  // State
  let allReports = [];
  let currentFilter = "All";
  let currentSort = "newest";
  let searchQuery = "";
  let selectedFile = null;

  // Configuration helper
  function getApiBaseUrl() {
    if (window.CAMPUSCARE_CONFIG && typeof window.CAMPUSCARE_CONFIG.getActiveApiUrl === "function") {
      return window.CAMPUSCARE_CONFIG.getActiveApiUrl();
    }
    return "http://127.0.0.1:5000/api/reports";
  }

  function getImageUrl(report) {
    if (!report || !report.image) return null;
    // If the backend already provided a direct S3 or presigned URL:
    if (report.imageUrl) return report.imageUrl;
    // Otherwise fallback to canonical REST image endpoint:
    const base = getApiBaseUrl().replace(/\/+$/, "");
    return `${base}/${encodeURIComponent(report.reportId)}/image`;
  }

  // DOM Elements
  const form = document.querySelector("#report-form");
  const message = document.querySelector("#message");
  const submitButton = document.querySelector("#submit-button");
  const submitSpinner = document.querySelector("#submit-spinner");
  const submitText = document.querySelector("#submit-text");
  const submitArrow = document.querySelector("#submit-arrow");
  const reportsContainer = document.querySelector("#reports");
  const refreshButton = document.querySelector("#refresh-button");
  const refreshIcon = document.querySelector("#refresh-icon");

  // Inputs
  const inputType = document.querySelector("#input-type");
  const inputTitle = document.querySelector("#input-title");
  const inputLocation = document.querySelector("#input-location");
  const inputDescription = document.querySelector("#input-description");
  const inputReporterName = document.querySelector("#input-reporterName");
  const inputReporterEmail = document.querySelector("#input-reporterEmail");
  const fileInput = document.querySelector("#file-input");
  const dropzone = document.querySelector("#dropzone");
  const browseBtn = document.querySelector("#browse-btn");
  const imagePreviewCard = document.querySelector("#image-preview-card");
  const previewImage = document.querySelector("#preview-image");
  const previewFilename = document.querySelector("#preview-filename");
  const previewFilesize = document.querySelector("#preview-filesize");
  const removeImageBtn = document.querySelector("#remove-image-btn");

  // Counters
  const titleCounter = document.querySelector("#title-counter");
  const descCounter = document.querySelector("#desc-counter");

  // Search & Filter
  const searchInput = document.querySelector("#search-input");
  const clearSearchBtn = document.querySelector("#clear-search-btn");
  const sortSelect = document.querySelector("#sort-select");
  const filterChips = document.querySelectorAll(".filter-chip");
  const reportsCountBadge = document.querySelector("#reports-count-badge");

  // Modals
  const submissionModal = document.querySelector("#submission-modal");
  const submissionInProgress = document.querySelector("#submission-in-progress");
  const submissionSuccess = document.querySelector("#submission-success");
  const successReportId = document.querySelector("#success-report-id");
  const successSummary = document.querySelector("#success-summary");
  const copyReportIdBtn = document.querySelector("#copy-report-id-btn");
  const btnSubmitAnother = document.querySelector("#btn-submit-another");
  const btnViewSubmitted = document.querySelector("#btn-view-submitted");

  const detailsModal = document.querySelector("#details-modal");
  const closeDetailsBtn = document.querySelector("#close-details-btn");
  const detailsDoneBtn = document.querySelector("#details-done-btn");

  // Endpoint Modal
  const endpointModal = document.querySelector("#endpoint-modal");
  const endpointTrigger = document.querySelector("#endpoint-trigger");
  const closeEndpointBtn = document.querySelector("#close-endpoint-btn");
  const customEndpointInput = document.querySelector("#custom-endpoint-input");
  const presetLocal = document.querySelector("#preset-local");
  const presetLambda = document.querySelector("#preset-lambda");
  const testEndpointBtn = document.querySelector("#test-endpoint-btn");
  const saveEndpointBtn = document.querySelector("#save-endpoint-btn");
  const endpointTestResult = document.querySelector("#endpoint-test-result");
  const endpointLabel = document.querySelector("#endpoint-label");

  // ========================================================================
  // UTILITY FUNCTIONS
  // ========================================================================

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    const element = document.createElement("div");
    element.textContent = String(value);
    return element.innerHTML;
  }

  function formatTimestamp(value) {
    if (!value) return "Just now";
    try {
      const date = new Date(value);
      if (isNaN(date.getTime())) return value;
      return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      });
    } catch {
      return value;
    }
  }

  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  }

  function getCategoryBadgeClass(category) {
    switch (category) {
      case "Maintenance": return "badge-maintenance";
      case "Cleanliness": return "badge-cleanliness";
      case "Complaint": return "badge-complaint";
      case "Suggestion": return "badge-suggestion";
      case "Lost & Found": return "badge-lost-found";
      default: return "badge-other";
    }
  }

  // Toast Notification
  function showToast(title, msg, type = "info") {
    const container = document.querySelector("#toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.setAttribute("role", "alert");

    const iconSvg = type === "success"
      ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>'
      : type === "error"
      ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
      : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0284c7" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';

    toast.innerHTML = `
      <div class="toast-icon">${iconSvg}</div>
      <div class="toast-content">
        <div class="toast-title">${escapeHtml(title)}</div>
        <div class="toast-message">${escapeHtml(msg)}</div>
      </div>
      <button type="button" class="toast-close" aria-label="Close">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    `;

    toast.querySelector(".toast-close").addEventListener("click", () => toast.remove());
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(40px)";
      setTimeout(() => toast.remove(), 250);
    }, 4500);
  }

  // Preserved for test compatibility
  function showMessage(text, kind) {
    if (message) {
      message.textContent = text;
      message.className = kind;
    }
    if (kind === "error") {
      showToast("Submission Error", text, "error");
    } else if (kind === "success") {
      showToast("Success", text, "success");
    }
  }

  function clearErrors() {
    document.querySelectorAll(".error-text").forEach(el => el.remove());
    document.querySelectorAll(".field-error").forEach(el => el.classList.remove("field-error"));
    if (message) {
      message.className = "";
      message.textContent = "";
    }
  }

  function showErrors(errors) {
    Object.entries(errors).forEach(([name, text]) => {
      const input = form.elements[name];
      if (!input) return;
      input.classList.add("field-error");

      const parent = input.closest(".form-group") || input.parentElement;
      const error = document.createElement("span");
      error.className = "error-text";
      error.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> ${escapeHtml(text)}`;
      parent.appendChild(error);
    });
  }

  function clientErrors() {
    const errors = {};
    const required = {
      type: "Type",
      title: "Title",
      location: "Location",
      description: "Description",
      reporterName: "Reporter Name",
      reporterEmail: "Reporter Email"
    };

    for (const [field, label] of Object.entries(required)) {
      if (!form.elements[field] || !form.elements[field].value.trim()) {
        errors[field] = `${label} is required.`;
      }
    }

    const email = form.elements.reporterEmail ? form.elements.reporterEmail.value.trim() : "";
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      errors.reporterEmail = "Please enter a valid email address.";
    }

    if (selectedFile) {
      const allowed = ["image/jpeg", "image/png", "image/webp", "image/jpg"];
      const ext = selectedFile.name.split(".").pop().toLowerCase();
      if (!allowed.includes(selectedFile.type) && !["jpg", "jpeg", "png", "webp"].includes(ext)) {
        errors.image = "Please select a supported image format (JPG, PNG, WEBP).";
      }
      if (selectedFile.size > 5 * 1024 * 1024) {
        errors.image = "Image must be 5 MB or smaller.";
      }
    }

    return errors;
  }

  // ========================================================================
  // FILE UPLOAD & PREVIEW
  // ========================================================================

  function handleFileSelected(file) {
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
      showToast("File Too Large", "Selected image exceeds the 5 MB limit. Please choose a smaller photo.", "error");
      return;
    }

    selectedFile = file;
    previewFilename.textContent = file.name;
    previewFilesize.textContent = formatBytes(file.size);

    const reader = new FileReader();
    reader.onload = function (e) {
      previewImage.src = e.target.result;
      dropzone.classList.add("hidden");
      imagePreviewCard.classList.remove("hidden");
    };
    reader.readAsDataURL(file);
  }

  function removeSelectedFile() {
    selectedFile = null;
    fileInput.value = "";
    previewImage.src = "";
    imagePreviewCard.classList.add("hidden");
    dropzone.classList.remove("hidden");
  }

  if (browseBtn) {
    browseBtn.addEventListener("click", e => {
      e.stopPropagation();
      fileInput.click();
    });
  }

  if (dropzone) {
    dropzone.addEventListener("click", () => fileInput.click());
    dropzone.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        fileInput.click();
      }
    });

    ["dragenter", "dragover"].forEach(eventName => {
      dropzone.addEventListener(eventName, e => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add("dragover");
      });
    });

    ["dragleave", "drop"].forEach(eventName => {
      dropzone.addEventListener(eventName, e => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove("dragover");
      });
    });

    dropzone.addEventListener("drop", e => {
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files && files.length > 0) {
        handleFileSelected(files[0]);
      }
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files[0]) {
        handleFileSelected(fileInput.files[0]);
      }
    });
  }

  if (removeImageBtn) {
    removeImageBtn.addEventListener("click", removeSelectedFile);
  }

  // ========================================================================
  // CHARACTER COUNTERS & INPUT EVENTS
  // ========================================================================

  if (inputTitle && titleCounter) {
    inputTitle.addEventListener("input", () => {
      titleCounter.textContent = `${inputTitle.value.length} / 100`;
    });
  }

  if (inputDescription && descCounter) {
    inputDescription.addEventListener("input", () => {
      descCounter.textContent = `${inputDescription.value.length} / 1000`;
    });
  }

  // ========================================================================
  // CATEGORY CARDS INTERACTION
  // ========================================================================

  document.querySelectorAll(".category-card").forEach(card => {
    card.addEventListener("click", () => {
      const category = card.getAttribute("data-category");
      if (inputType && category) {
        inputType.value = category;
        const target = document.querySelector("#submit-section");
        if (target) {
          target.scrollIntoView({ behavior: "smooth" });
          setTimeout(() => {
            inputType.focus();
            inputType.classList.add("field-highlight");
            setTimeout(() => inputType.classList.remove("field-highlight"), 1200);
          }, 400);
        }
      }
    });
  });

  // ========================================================================
  // FORM SUBMISSION & PROGRESS TIMELINE
  // ========================================================================

  async function updateTimelineStep(stepId, state) {
    const stepEl = document.querySelector(`#${stepId}`);
    if (!stepEl) return;
    if (state === "active") {
      stepEl.className = "timeline-step active";
    } else if (state === "completed") {
      stepEl.className = "timeline-step completed";
      const bullet = stepEl.querySelector(".step-bullet");
      if (bullet) bullet.innerHTML = "✓";
    }
  }

  function resetTimeline() {
    ["step-validate", "step-upload", "step-save", "step-notify"].forEach((id, idx) => {
      const el = document.querySelector(`#${id}`);
      if (el) {
        el.className = idx === 0 ? "timeline-step active" : "timeline-step";
        const bullet = el.querySelector(".step-bullet");
        if (bullet) bullet.textContent = String(idx + 1);
      }
    });
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    clearErrors();

    const errors = clientErrors();
    if (Object.keys(errors).length) {
      showErrors(errors);
      showMessage("Please correct the highlighted fields.", "error");
      return;
    }

    // Prepare FormData
    const formData = new FormData(form);
    // Explicitly append the selected file if chosen via drag-and-drop
    if (selectedFile) {
      formData.set("image", selectedFile);
    }

    // Open submission modal
    submissionInProgress.classList.remove("hidden");
    submissionSuccess.classList.add("hidden");
    submissionModal.classList.remove("hidden");
    resetTimeline();

    // Button loading state
    submitButton.disabled = true;
    submitSpinner.classList.remove("hidden");
    submitText.textContent = "Submitting...";
    submitArrow.classList.add("hidden");

    try {
      const stepText = document.querySelector("#submission-step-text");

      // Step 1: Validating
      await updateTimelineStep("step-validate", "completed");
      await updateTimelineStep("step-upload", "active");
      if (stepText) stepText.textContent = selectedFile ? "Uploading image to secure storage..." : "Processing submission...";
      await new Promise(r => setTimeout(r, 200));

      // Step 2: Saving & Uploading
      await updateTimelineStep("step-upload", "completed");
      await updateTimelineStep("step-save", "active");
      if (stepText) stepText.textContent = "Allocating Report ID & writing records...";

      const targetUrl = getApiBaseUrl();
      const response = await fetch(targetUrl, {
        method: "POST",
        body: formData
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        if (data.errors) showErrors(data.errors);
        throw new Error(data.message || `Server responded with status ${response.status}`);
      }

      // Step 3: Saved & Notify
      await updateTimelineStep("step-save", "completed");
      await updateTimelineStep("step-notify", "active");
      if (stepText) stepText.textContent = "Dispatching staff notification via Amazon SNS...";
      await new Promise(r => setTimeout(r, 300));
      await updateTimelineStep("step-notify", "completed");

      // Success Display
      const assignedId = data.reportId || "CC-001";
      successReportId.textContent = assignedId;

      // Populate summary
      successSummary.innerHTML = `
        <div><strong>Type:</strong> ${escapeHtml(formData.get("type"))}</div>
        <div><strong>Title:</strong> ${escapeHtml(formData.get("title"))}</div>
        <div><strong>Location:</strong> ${escapeHtml(formData.get("location"))}</div>
        <div><strong>Reported By:</strong> ${escapeHtml(formData.get("reporterName"))} (${escapeHtml(formData.get("reporterEmail"))})</div>
      `;

      // Show success in modal
      submissionInProgress.classList.add("hidden");
      submissionSuccess.classList.remove("hidden");

      // Reset form
      form.reset();
      removeSelectedFile();
      if (titleCounter) titleCounter.textContent = "0 / 100";
      if (descCounter) descCounter.textContent = "0 / 1000";

      showMessage(`Report submitted successfully. Your Report ID is ${assignedId}.`, "success");
      await loadReports();
    } catch (error) {
      submissionModal.classList.add("hidden");
      const errText = error.message || "Could not connect to CampusCare backend. Please check your connection.";
      showMessage(errText, "error");
    } finally {
      submitButton.disabled = false;
      submitSpinner.classList.add("hidden");
      submitText.textContent = "Submit Report";
      submitArrow.classList.remove("hidden");
    }
  });

  // Modal actions
  if (copyReportIdBtn) {
    copyReportIdBtn.addEventListener("click", () => {
      const id = successReportId.textContent;
      navigator.clipboard.writeText(id).then(() => {
        showToast("Copied!", `Report ID ${id} copied to clipboard.`, "info");
      }).catch(() => {
        showToast("Report ID", id, "info");
      });
    });
  }

  if (btnSubmitAnother) {
    btnSubmitAnother.addEventListener("click", () => {
      submissionModal.classList.add("hidden");
      const submitSec = document.querySelector("#submit-section");
      if (submitSec) submitSec.scrollIntoView({ behavior: "smooth" });
    });
  }

  if (btnViewSubmitted) {
    btnViewSubmitted.addEventListener("click", () => {
      submissionModal.classList.add("hidden");
      const reportsSec = document.querySelector("#reports-section");
      if (reportsSec) reportsSec.scrollIntoView({ behavior: "smooth" });
    });
  }

  // ========================================================================
  // LOAD & RENDER REPORTS
  // ========================================================================

  async function loadReports() {
    if (refreshIcon) refreshIcon.classList.add("spin-animation");
    reportsContainer.innerHTML = `
      <div class="empty-state">
        <div class="circular-spinner" style="width:36px;height:36px;border-width:3px;"></div>
        <p class="empty-state-text">Loading reports from CampusCare...</p>
      </div>
    `;

    try {
      const targetUrl = getApiBaseUrl();
      const response = await fetch(targetUrl);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const reports = await response.json();

      allReports = Array.isArray(reports) ? reports : [];
      updateDashboardStatistics(allReports);
      renderReports();
    } catch (err) {
      console.error("Failed to load reports:", err);
      reportsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          </div>
          <h3 class="empty-state-title">Unable to connect to CampusCare</h3>
          <p class="empty-state-text">Could not load reports from <code>${escapeHtml(getApiBaseUrl())}</code>. Verify the backend service or check your connection.</p>
          <button type="button" id="btn-retry-load" class="btn btn-secondary btn-sm">Try Again</button>
        </div>
      `;
      const retry = document.querySelector("#btn-retry-load");
      if (retry) retry.addEventListener("click", loadReports);
    } finally {
      if (refreshIcon) {
        setTimeout(() => refreshIcon.classList.remove("spin-animation"), 400);
      }
    }
  }

  function updateDashboardStatistics(reports) {
    const counts = {
      total: reports.length,
      Maintenance: 0,
      Cleanliness: 0,
      Complaint: 0,
      Suggestion: 0,
      "Lost & Found": 0,
      Other: 0
    };

    reports.forEach(r => {
      if (counts[r.type] !== undefined) {
        counts[r.type]++;
      } else {
        counts.Other++;
      }
    });

    const setVal = (id, val) => {
      const el = document.querySelector(id);
      if (el) el.textContent = String(val);
    };

    setVal("#stat-total", counts.total);
    setVal("#stat-maintenance", counts.Maintenance);
    setVal("#stat-cleanliness", counts.Cleanliness);
    setVal("#stat-complaints", counts.Complaint);
    setVal("#stat-suggestions", counts.Suggestion);
    setVal("#stat-lostfound", counts["Lost & Found"]);

    const countAll = document.querySelector("#count-all");
    if (countAll) countAll.textContent = String(counts.total);
  }

  function getFilteredAndSortedReports() {
    let result = [...allReports];

    // Filter by Category
    if (currentFilter && currentFilter !== "All") {
      result = result.filter(r => (r.type || "").toLowerCase() === currentFilter.toLowerCase());
    }

    // Search Filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      result = result.filter(r => {
        const idMatch = (r.reportId || "").toLowerCase().includes(q);
        const titleMatch = (r.title || "").toLowerCase().includes(q);
        const locMatch = (r.location || "").toLowerCase().includes(q);
        const reporterMatch = (r.reporterName || "").toLowerCase().includes(q);
        return idMatch || titleMatch || locMatch || reporterMatch;
      });
    }

    // Sort
    result.sort((a, b) => {
      const timeA = new Date(a.timestamp || 0).getTime();
      const timeB = new Date(b.timestamp || 0).getTime();
      return currentSort === "oldest" ? timeA - timeB : timeB - timeA;
    });

    return result;
  }

  function renderReports() {
    const list = getFilteredAndSortedReports();

    if (reportsCountBadge) {
      reportsCountBadge.textContent = `${list.length} ${list.length === 1 ? "report" : "reports"}`;
    }

    // Empty state 1: No reports in system at all
    if (allReports.length === 0) {
      reportsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </div>
          <h3 class="empty-state-title">No reports yet</h3>
          <p class="empty-state-text">Be the first person to help improve our campus.</p>
          <a href="#submit-section" class="btn btn-primary btn-sm">Submit a Report</a>
        </div>
      `;
      return;
    }

    // Empty state 2: Search/Filter yielded 0 results
    if (list.length === 0) {
      reportsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
          </div>
          <h3 class="empty-state-title">No matching reports</h3>
          <p class="empty-state-text">No reports match "${escapeHtml(searchQuery)}" in ${escapeHtml(currentFilter)}. Try clearing filters or search terms.</p>
          <button type="button" id="btn-reset-filters" class="btn btn-secondary btn-sm">Reset Filters</button>
        </div>
      `;
      const btnReset = document.querySelector("#btn-reset-filters");
      if (btnReset) {
        btnReset.addEventListener("click", () => {
          searchQuery = "";
          if (searchInput) searchInput.value = "";
          if (clearSearchBtn) clearSearchBtn.classList.add("hidden");
          currentFilter = "All";
          filterChips.forEach(c => c.classList.toggle("active", c.getAttribute("data-filter") === "All"));
          renderReports();
        });
      }
      return;
    }

    // Render Cards
    reportsContainer.innerHTML = list.map(report => {
      const badgeClass = getCategoryBadgeClass(report.type);
      const imgUrl = getImageUrl(report);

      return `
        <article class="card" id="card-${escapeHtml(report.reportId)}">
          <div class="card-top-bar">
            <div class="card-badges">
              <span class="badge badge-id">${escapeHtml(report.reportId)}</span>
              <span class="badge ${badgeClass}">${escapeHtml(report.type || "Other")}</span>
            </div>
            <div class="card-time">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              <span>${formatTimestamp(report.timestamp)}</span>
            </div>
          </div>

          <h3 class="card-title">${escapeHtml(report.title)}</h3>

          <div class="card-meta-row">
            <span class="meta-item">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>
              <strong>${escapeHtml(report.location)}</strong>
            </span>
          </div>

          <p class="card-desc">${escapeHtml(report.description)}</p>

          ${imgUrl ? `
            <div class="card-image-wrap" data-report-id="${escapeHtml(report.reportId)}">
              <img class="report-image" src="${imgUrl}" alt="Photo for ${escapeHtml(report.reportId)}" loading="lazy">
              <div class="card-image-overlay">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                <span>View Photo Evidence</span>
              </div>
            </div>
          ` : ""}

          <div class="card-footer">
            <span class="card-reporter">
              Reported by: <strong>${escapeHtml(report.reporterName || "Anonymous")}</strong>
            </span>
            <button type="button" class="btn btn-secondary btn-sm btn-view-details" data-report-id="${escapeHtml(report.reportId)}">
              View Details
            </button>
          </div>
        </article>
      `;
    }).join("");

    // Attach click handlers to View Details buttons and images
    reportsContainer.querySelectorAll(".btn-view-details, .card-image-wrap").forEach(el => {
      el.addEventListener("click", () => {
        const id = el.getAttribute("data-report-id");
        const found = allReports.find(r => r.reportId === id);
        if (found) openDetailsModal(found);
      });
    });
  }

  // ========================================================================
  // REPORT DETAILS MODAL
  // ========================================================================

  function openDetailsModal(report) {
    if (!detailsModal || !report) return;

    const idBadge = document.querySelector("#details-id-badge");
    const typeBadge = document.querySelector("#details-type-badge");
    const titleEl = document.querySelector("#details-title");
    const locEl = document.querySelector("#details-location");
    const timeEl = document.querySelector("#details-timestamp");
    const repEl = document.querySelector("#details-reporter");
    const emailEl = document.querySelector("#details-email");
    const descEl = document.querySelector("#details-description");
    const imgContainer = document.querySelector("#details-image-container");
    const detailsImg = document.querySelector("#details-image");
    const imgLink = document.querySelector("#details-image-link");

    if (idBadge) idBadge.textContent = report.reportId;
    if (typeBadge) {
      typeBadge.textContent = report.type;
      typeBadge.className = `badge ${getCategoryBadgeClass(report.type)}`;
    }
    if (titleEl) titleEl.textContent = report.title;
    if (locEl) locEl.textContent = report.location;
    if (timeEl) timeEl.textContent = formatTimestamp(report.timestamp);
    if (repEl) repEl.textContent = report.reporterName || "Not provided";
    if (emailEl) emailEl.textContent = report.reporterEmail || "Not provided";
    if (descEl) descEl.textContent = report.description || "";

    const imgUrl = getImageUrl(report);
    if (imgUrl && imgContainer && detailsImg) {
      detailsImg.src = imgUrl;
      if (imgLink) imgLink.href = imgUrl;
      imgContainer.classList.remove("hidden");
    } else if (imgContainer) {
      imgContainer.classList.add("hidden");
    }

    detailsModal.classList.remove("hidden");
  }

  function closeDetailsModal() {
    if (detailsModal) detailsModal.classList.add("hidden");
  }

  if (closeDetailsBtn) closeDetailsBtn.addEventListener("click", closeDetailsModal);
  if (detailsDoneBtn) detailsDoneBtn.addEventListener("click", closeDetailsModal);
  if (detailsModal) {
    detailsModal.addEventListener("click", e => {
      if (e.target === detailsModal) closeDetailsModal();
    });
  }

  // ESC key closes any open modal
  window.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      closeDetailsModal();
      if (submissionModal) submissionModal.classList.add("hidden");
      if (endpointModal) endpointModal.classList.add("hidden");
    }
  });

  // ========================================================================
  // SEARCH, FILTER, AND SORT CONTROLS
  // ========================================================================

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      searchQuery = searchInput.value;
      if (clearSearchBtn) {
        clearSearchBtn.classList.toggle("hidden", !searchQuery);
      }
      renderReports();
    });
  }

  if (clearSearchBtn) {
    clearSearchBtn.addEventListener("click", () => {
      searchQuery = "";
      searchInput.value = "";
      clearSearchBtn.classList.add("hidden");
      searchInput.focus();
      renderReports();
    });
  }

  if (sortSelect) {
    sortSelect.addEventListener("change", () => {
      currentSort = sortSelect.value;
      renderReports();
    });
  }

  filterChips.forEach(chip => {
    chip.addEventListener("click", () => {
      filterChips.forEach(c => {
        c.classList.remove("active");
        c.setAttribute("aria-selected", "false");
      });
      chip.classList.add("active");
      chip.setAttribute("aria-selected", "true");
      currentFilter = chip.getAttribute("data-filter") || "All";
      renderReports();
    });
  });

  if (refreshButton) {
    refreshButton.addEventListener("click", loadReports);
  }

  // ========================================================================
  // ENDPOINT SETTINGS MODAL
  // ========================================================================

  function updateEndpointBadgeUI() {
    const current = getApiBaseUrl();
    if (!endpointLabel) return;
    if (current.includes("lambda-url") || current.includes("amazonaws.com")) {
      endpointLabel.textContent = "AWS Lambda";
      const dot = document.querySelector(".status-dot");
      if (dot) dot.className = "status-dot cloud";
    } else {
      endpointLabel.textContent = "Local API";
      const dot = document.querySelector(".status-dot");
      if (dot) dot.className = "status-dot active";
    }
  }

  if (endpointTrigger) {
    endpointTrigger.addEventListener("click", () => {
      if (!endpointModal) return;
      if (customEndpointInput) customEndpointInput.value = getApiBaseUrl();
      if (endpointTestResult) endpointTestResult.classList.add("hidden");
      endpointModal.classList.remove("hidden");
    });
  }

  if (closeEndpointBtn) {
    closeEndpointBtn.addEventListener("click", () => {
      if (endpointModal) endpointModal.classList.add("hidden");
    });
  }

  if (endpointModal) {
    endpointModal.addEventListener("click", e => {
      if (e.target === endpointModal) endpointModal.classList.add("hidden");
    });
  }

  if (presetLocal) {
    presetLocal.addEventListener("click", () => {
      if (customEndpointInput) customEndpointInput.value = "http://127.0.0.1:5000/api/reports";
    });
  }

  if (presetLambda) {
    presetLambda.addEventListener("click", () => {
      if (customEndpointInput) {
        customEndpointInput.value = "https://<your-id>.lambda-url.ap-south-1.on.aws";
        customEndpointInput.focus();
        customEndpointInput.select();
      }
    });
  }

  if (testEndpointBtn) {
    testEndpointBtn.addEventListener("click", async () => {
      const url = (customEndpointInput ? customEndpointInput.value : "").trim();
      if (!url) return;

      endpointTestResult.className = "endpoint-test-box";
      endpointTestResult.innerHTML = `
        <span class="btn-spinner" style="border-color:rgba(0,0,0,0.2);border-top-color:#333;"></span>
        <span>Connecting to ${escapeHtml(url)}...</span>
      `;
      endpointTestResult.classList.remove("hidden");

      const start = Date.now();
      try {
        const res = await fetch(url, { method: "GET" });
        const latency = Date.now() - start;
        if (res.ok) {
          endpointTestResult.className = "endpoint-test-box success";
          endpointTestResult.innerHTML = `
            <span>✓ Connected successfully (${latency}ms). Endpoint is healthy.</span>
          `;
        } else {
          endpointTestResult.className = "endpoint-test-box error";
          endpointTestResult.innerHTML = `
            <span>Server returned HTTP ${res.status}. Check endpoint configuration.</span>
          `;
        }
      } catch (err) {
        endpointTestResult.className = "endpoint-test-box error";
        endpointTestResult.innerHTML = `
          <span>Connection failed. Verify the URL and CORS headers.</span>
        `;
      }
    });
  }

  if (saveEndpointBtn) {
    saveEndpointBtn.addEventListener("click", () => {
      const url = (customEndpointInput ? customEndpointInput.value : "").trim();
      if (url && window.CAMPUSCARE_CONFIG) {
        window.CAMPUSCARE_CONFIG.setActiveApiUrl(url);
        updateEndpointBadgeUI();
        endpointModal.classList.add("hidden");
        showToast("Endpoint Updated", `CampusCare is now connected to: ${url}`, "success");
        loadReports();
      }
    });
  }

  // ========================================================================
  // INITIALIZATION
  // ========================================================================

  updateEndpointBadgeUI();
  loadReports();

})();
