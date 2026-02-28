import { app } from "../../scripts/app.js";

const EXT_NAME = "ComfyUI_PromptVault";
const EXT_ID = "ComfyUI_PromptVault.TopMenu";
const BASE_URL = `/extensions/${EXT_NAME}/`;
const GUARD_KEY = "__PROMPTVAULT_REGISTERED__";

function create(tag, attrs = {}, children = []) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") element.className = value;
    else if (key === "text") element.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") element.addEventListener(key.slice(2), value);
    else element.setAttribute(key, value);
  }
  for (const child of children) element.appendChild(child);
  return element;
}

function formatTimestamp(raw) {
  if (!raw) return "";
  try {
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return String(raw);
    const pad = (n) => String(n).padStart(2, "0");
    const y = d.getFullYear();
    const m = pad(d.getMonth() + 1);
    const day = pad(d.getDate());
    const h = pad(d.getHours());
    const min = pad(d.getMinutes());
    const s = pad(d.getSeconds());
    return `${y}-${m}-${day} ${h}:${min}:${s}`;
  } catch {
    return String(raw);
  }
}

function parseCommaList(value) {
  return (value || "")
    .replace(/[，、]/g, ",")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "readonly");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

/* ── Toast notification system ── */
let _toastContainer = null;
function _ensureToastContainer() {
  if (_toastContainer && document.body.contains(_toastContainer)) return _toastContainer;
  _toastContainer = create("div", { class: "pv-toast-container" });
  document.body.appendChild(_toastContainer);
  return _toastContainer;
}

function toast(message, type = "info", duration = 2800) {
  const container = _ensureToastContainer();
  const el = create("div", { class: `pv-toast pv-toast-${type}`, text: message });
  container.appendChild(el);
  const remove = () => {
    el.classList.add("pv-toast-exit");
    el.addEventListener("animationend", () => el.remove(), { once: true });
  };
  const timer = setTimeout(remove, duration);
  el.addEventListener("click", () => { clearTimeout(timer); remove(); });
}

function ensureStyle() {
  if (document.getElementById("promptvault-style")) return;
  const link = document.createElement("link");
  link.id = "promptvault-style";
  link.rel = "stylesheet";
  link.href = `${BASE_URL}promptvault.css`;
  document.head.appendChild(link);
}

async function request(path, options = {}) {
  const response = await fetch(`/promptvault${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status}: ${text}`);
  }
  return await response.json();
}

function ensureFloatingButton(openFn) {
  if (document.getElementById("pv-floating-btn")) return;
  const button = create("button", {
    id: "pv-floating-btn",
    class: "pv-floating-btn",
    text: "\u63d0\u793a\u8bcd\u5e93",
    onclick: openFn,
  });
  button.style.position = "fixed";
  button.style.right = "16px";
  button.style.top = "16px";
  button.style.zIndex = "9999";
  document.body.appendChild(button);
}

async function injectTopMenuButton(openFn) {
  try {
    if (!app.menu?.settingsGroup?.element) return false;
    if (document.getElementById("pv-menu-btn-group")) return true;
    const ButtonGroupModule = await import("../../scripts/ui/components/buttonGroup.js");
    const ButtonModule = await import("../../scripts/ui/components/button.js");
    const group = new ButtonGroupModule.ComfyButtonGroup(
      new ButtonModule.ComfyButton({
        icon: "book-open-variant",
        action: openFn,
        tooltip: "\u63d0\u793a\u8bcd\u5e93",
        content: "\u63d0\u793a\u8bcd\u5e93",
        classList: "comfyui-button comfyui-menu-mobile-collapse primary",
      }).element,
    );
    group.element.id = "pv-menu-btn-group";
    app.menu.settingsGroup.element.before(group.element);
    return true;
  } catch (_error) {
    return false;
  }
}

function injectLegacyMenuButton(openFn) {
  if (document.getElementById("pv-menu-btn")) return true;
  const menu = document.querySelector(".comfy-menu");
  if (!menu) return false;
  const button = document.createElement("button");
  button.id = "pv-menu-btn";
  button.textContent = "\u63d0\u793a\u8bcd\u5e93";
  button.onclick = openFn;
  menu.appendChild(button);
  return true;
}

function thumbUrl(itemId, updatedAt) {
  const v = updatedAt ? encodeURIComponent(updatedAt) : "0";
  return `/promptvault/entries/${encodeURIComponent(itemId)}/thumbnail?v=${v}`;
}

function openManager() {
  ensureStyle();

  const overlay = create("div", { class: "pv-overlay" });
  const modal = create("div", {
    class: "pv-modal",
    role: "dialog",
    "aria-label": "\u63d0\u793a\u8bcd\u5e93\u7ba1\u7406\u5668",
  });
  const titleLabel = create("span", { text: "\u63d0\u793a\u8bcd\u5e93\u7ba1\u7406\u5668" });

  const inputQuery = create("input", { class: "pv-input", placeholder: "\u5173\u952e\u8bcd\uff08\u6807\u9898/\u5185\u5bb9/\u6807\u7b7e\uff09" });
  const inputTags = create("input", { class: "pv-input", placeholder: "\u6807\u7b7e\uff08\u9017\u53f7\u5206\u9694\uff0c\u53ef\u9009\uff09" });
  const inputModel = create("input", { class: "pv-input", placeholder: "\u6a21\u578b\uff08\u5982 SDXL / Flux\uff0c\u53ef\u9009\uff09" });
  const selectStatus = create(
    "select",
    { class: "pv-input pv-select-status", title: "\u72b6\u6001" },
    [
      create("option", { value: "active", text: "\u6b63\u5e38" }),
      create("option", { value: "deleted", text: "\u56de\u6536\u7ad9" }),
    ],
  );
  const buttonSearch = create("button", { class: "pv-btn pv-primary", text: "\u68c0\u7d22" });
  const buttonPurge = create("button", { class: "pv-btn pv-danger", text: "\u6e05\u7a7a\u56de\u6536\u7ad9" });
  const buttonNew = create("button", { class: "pv-btn", text: "\u65b0\u5efa" });
  const buttonToggleSidebar = create("button", { class: "pv-btn", text: "\u6807\u7b7e\u680f" });
  const buttonClose = create("button", { class: "pv-btn pv-danger", text: "\u5173\u95ed" });
  const title = create("div", { class: "pv-title" }, [titleLabel, buttonClose]);
  const toolbarSpacer = create("div", { class: "pv-toolbar-spacer" });
  const toolbar = create("div", { class: "pv-toolbar" }, [
    inputQuery,
    inputTags,
    inputModel,
    buttonSearch,
    buttonNew,
    toolbarSpacer,
    selectStatus,
    buttonPurge,
    buttonToggleSidebar,
  ]);

  const sidebar = create("div", { class: "pv-sidebar" });
  const list = create("div", { class: "pv-list" });
  let currentPositive = "";
  const buttonCopyPositive = create("button", { class: "pv-btn pv-small", text: "\u590d\u5236\u6b63\u5411\u63d0\u793a\u8bcd" });
  buttonCopyPositive.addEventListener("click", async () => {
    if (!currentPositive.trim()) {
      toast("\u8bf7\u5148\u9009\u62e9\u4e00\u6761\u8bb0\u5f55", "info");
      return;
    }
    try {
      await copyTextToClipboard(currentPositive);
      toast("\u5df2\u590d\u5236\u6b63\u5411\u63d0\u793a\u8bcd", "success");
    } catch (error) {
      toast(`\u590d\u5236\u5931\u8d25: ${error}`, "error");
    }
  });
  const detailBody = create("div", { class: "pv-detail-body" }, [
    create("div", { class: "pv-empty", text: "\u9009\u62e9\u8bb0\u5f55\u67e5\u770b\u9884\u89c8\u3002" }),
  ]);
  const detailHeader = create("div", { class: "pv-detail-header" }, [
    create("div", { class: "pv-detail-title", text: "\u8be6\u60c5 / \u9884\u89c8" }),
    buttonCopyPositive,
  ]);
  const detail = create("div", { class: "pv-detail" }, [detailHeader, detailBody]);
  const body = create("div", { class: "pv-body" }, [sidebar, list, detail]);

  const statusBarLeft = create("span", { class: "pv-statusbar-left", text: "\u5c31\u7eea" });
  const statusBarRight = create("span", { class: "pv-statusbar-right", text: "" });
  const statusBar = create("div", { class: "pv-statusbar" }, [statusBarLeft, statusBarRight]);

  let selectedTag = "";
  let currentStatus = "active";
  let sidebarVisible = false;

  sidebar.style.display = "none";
  body.classList.add("pv-body-no-sidebar");

  function closeManager() {
    if (document.body.contains(overlay)) document.body.removeChild(overlay);
  }

  buttonToggleSidebar.addEventListener("click", () => {
    sidebarVisible = !sidebarVisible;
    if (sidebarVisible) {
      sidebar.style.display = "";
      body.classList.remove("pv-body-no-sidebar");
    } else {
      sidebar.style.display = "none";
      body.classList.add("pv-body-no-sidebar");
    }
  });

  selectStatus.addEventListener("change", () => {
    currentStatus = selectStatus.value === "deleted" ? "deleted" : "active";
    reloadList().catch((e) => toast(String(e), "error"));
  });

  buttonPurge.addEventListener("click", async () => {
    if (currentStatus !== "deleted") {
      toast("\u8bf7\u5148\u5207\u6362\u5230\u201c\u56de\u6536\u7ad9\u201d\u72b6\u6001\u518d\u6267\u884c\u6e05\u7a7a\u3002", "info");
      return;
    }
    if (!confirm("\u786e\u5b9a\u6e05\u7a7a\u56de\u6536\u7ad9\uff1f\u6b64\u64cd\u4f5c\u4e0d\u53ef\u64a4\u56de\u3002")) return;
    try {
      await request("/entries/purge_deleted", { method: "POST", body: JSON.stringify({}) });
      toast("\u56de\u6536\u7ad9\u5df2\u6e05\u7a7a", "success");
      await reloadList();
    } catch (error) {
      toast(`\u6e05\u7a7a\u56de\u6536\u7ad9\u5931\u8d25: ${error}`, "error");
    }
  });

  async function loadTags() {
    sidebar.textContent = "\u52a0\u8f7d\u6807\u7b7e...";
    try {
      const res = await request("/tags?limit=200");
      const items = res.items || [];
      sidebar.textContent = "";
      const headerRow = create("div", { class: "pv-sidebar-header-row" }, [
        create("div", { class: "pv-sidebar-header", text: "\u6807\u7b7e" }),
        create("button", { class: "pv-btn pv-small pv-sidebar-tidy-btn", text: "\u6574\u7406\u6807\u7b7e" }),
      ]);
      const tidyButton = headerRow.querySelector("button");
      tidyButton.addEventListener("click", async () => {
        try {
          if (!confirm("\u5c06\u5220\u9664\u6ca1\u6709\u4efb\u4f55\u8bb0\u5f55\u5f15\u7528\u7684\u6807\u7b7e\uff0c\u5e76\u8865\u5145\u7f3a\u5931\u7684\u6807\u7b7e\u8bb0\u5f55\u3002\u786e\u5b9a\u7ee7\u7eed\uff1f")) return;
          const result = await request("/tags/tidy", { method: "POST", body: JSON.stringify({}) });
          toast(`\u6574\u7406\u5b8c\u6210\uff1a\u5220\u9664 ${result.removed || 0} \u4e2a\u65e0\u7528\u6807\u7b7e\uff0c\u65b0\u589e ${result.added || 0} \u4e2a\u6807\u7b7e\u3002`, "success");
          await loadTags();
        } catch (e) {
          toast(`\u6574\u7406\u6807\u7b7e\u5931\u8d25: ${e}`, "error");
        }
      });
      const allRow = create("div", {
        class: "pv-sidebar-item pv-sidebar-item-active",
        text: "\u5168\u90e8",
      });
      selectedTag = "";
      allRow.addEventListener("click", () => {
        selectedTag = "";
        inputTags.value = "";
        updateSidebarActive(allRow);
        reloadList().catch((e) => toast(String(e), "error"));
      });
      const tagSearchInput = create("input", {
        class: "pv-input pv-sidebar-search",
        placeholder: "\u641c\u7d22\u6807\u7b7e\u2026",
      });

      const tagListContainer = create("div", { class: "pv-sidebar-list" });

      function renderTagItems(filter) {
        tagListContainer.textContent = "";
        tagListContainer.appendChild(allRow);
        const kw = (filter || "").trim().toLowerCase();
        let count = 0;
        items.forEach((t) => {
          const name = t.name || "";
          if (!name) return;
          if (kw && !name.toLowerCase().includes(kw)) return;
          count++;
          const row = create("div", { class: "pv-sidebar-item", text: name });
          if (name === selectedTag) row.classList.add("pv-sidebar-item-active");
          row.addEventListener("click", () => {
            selectedTag = name;
            inputTags.value = name;
            updateSidebarActive(row);
            reloadList().catch((e) => toast(String(e), "error"));
          });
          tagListContainer.appendChild(row);
        });
        if (kw && count === 0) {
          tagListContainer.appendChild(create("div", { class: "pv-empty", text: "\u65e0\u5339\u914d\u6807\u7b7e" }));
        }
      }

      tagSearchInput.addEventListener("input", () => renderTagItems(tagSearchInput.value));

      sidebar.appendChild(headerRow);
      sidebar.appendChild(tagSearchInput);
      sidebar.appendChild(tagListContainer);
      renderTagItems("");
    } catch (e) {
      sidebar.textContent = "";
      sidebar.appendChild(create("div", { class: "pv-empty", text: `\u6807\u7b7e\u52a0\u8f7d\u5931\u8d25: ${e}` }));
    }
  }

  function updateSidebarActive(activeEl) {
    sidebar.querySelectorAll(".pv-sidebar-item").forEach((el) => {
      if (el === activeEl) el.classList.add("pv-sidebar-item-active");
      else el.classList.remove("pv-sidebar-item-active");
    });
  }

  function renderDetail(entry, assembled) {
    currentPositive = assembled.positive || "";
    statusBarRight.textContent = `\u5f53\u524d: ${entry.title || "\u672a\u547d\u540d"} | ID: ${(entry.id || "").slice(0, 8)}\u2026 | v${entry.version || 1}`;
    const params = entry.params || {};
    const tableRows = [
      ["\u6807\u9898", entry.title || ""],
      ["ID", entry.id || ""],
      ["\u6807\u7b7e", (entry.tags || []).join(", ")],
      ["\u6a21\u578b", (entry.model_scope || []).join(", ")],
      ["\u7248\u672c", String(entry.version || 1)],
      { k1: "steps", v1: String(params.steps ?? ""), k2: "cfg", v2: String(params.cfg ?? "") },
      { k1: "sampler", v1: String(params.sampler ?? ""), k2: "scheduler", v2: String(params.scheduler ?? "") },
      ["seed", String(params.seed ?? "")],
    ];

    const table = create("table", { class: "pv-param-table" });
    const colgroup = create("colgroup", {}, [
      create("col", { class: "pv-col-k1" }),
      create("col", { class: "pv-col-v1" }),
      create("col", { class: "pv-col-k2" }),
      create("col", { class: "pv-col-v2" }),
    ]);
    const tbody = create("tbody");
    tableRows.forEach((row) => {
      if (Array.isArray(row)) {
        const [k, v] = row;
        const tr = create("tr", {}, [
          create("th", { text: k }),
          create("td", { text: v, colspan: "3" }),
        ]);
        tbody.appendChild(tr);
        return;
      }
      const tr = create("tr", { class: "pv-param-row-2col" }, [
        create("th", { text: row.k1 }),
        create("td", { text: row.v1 }),
        create("th", { text: row.k2 }),
        create("td", { text: row.v2 }),
      ]);
      tbody.appendChild(tr);
    });
    table.appendChild(colgroup);
    table.appendChild(tbody);

    const thumb = create("img", {
      class: "pv-thumb",
      alt: "thumbnail",
      src: entry.thumbnail_data_url || thumbUrl(entry.id, entry.updated_at),
    });
    thumb.onerror = () => {
      thumb.replaceWith(create("div", { class: "pv-empty", text: "\u6682\u65e0\u7f29\u7565\u56fe" }));
    };

    const btnCopyPos = create("button", { class: "pv-btn pv-small pv-copy-btn", text: "\u590d\u5236" });
    btnCopyPos.addEventListener("click", async () => {
      try {
        await copyTextToClipboard(assembled.positive || "");
        btnCopyPos.textContent = "\u2713";
        toast("\u5df2\u590d\u5236\u6b63\u5411\u63d0\u793a\u8bcd", "success", 1500);
        setTimeout(() => { btnCopyPos.textContent = "\u590d\u5236"; }, 1500);
      } catch (e) { toast(`\u590d\u5236\u5931\u8d25: ${e}`, "error"); }
    });
    const btnCopyNeg = create("button", { class: "pv-btn pv-small pv-copy-btn", text: "\u590d\u5236" });
    btnCopyNeg.addEventListener("click", async () => {
      try {
        await copyTextToClipboard(assembled.negative || "");
        btnCopyNeg.textContent = "\u2713";
        toast("\u5df2\u590d\u5236\u8d1f\u5411\u63d0\u793a\u8bcd", "success", 1500);
        setTimeout(() => { btnCopyNeg.textContent = "\u590d\u5236"; }, 1500);
      } catch (e) { toast(`\u590d\u5236\u5931\u8d25: ${e}`, "error"); }
    });

    const prompts = create("div", { class: "pv-prompt-grid" }, [
      create("div", { class: "pv-prompt-box" }, [
        create("div", { class: "pv-prompt-box-header" }, [
          create("div", { class: "pv-detail-title", text: "\u6b63\u5411\u63d0\u793a\u8bcd" }),
          btnCopyPos,
        ]),
        create("pre", { class: "pv-pre", text: assembled.positive || "" }),
      ]),
      create("div", { class: "pv-prompt-box" }, [
        create("div", { class: "pv-prompt-box-header" }, [
          create("div", { class: "pv-detail-title", text: "\u8d1f\u5411\u63d0\u793a\u8bcd" }),
          btnCopyNeg,
        ]),
        create("pre", { class: "pv-pre", text: assembled.negative || "" }),
      ]),
    ]);

    detailBody.textContent = "";
    detailBody.appendChild(thumb);
    detailBody.appendChild(table);
    detailBody.appendChild(prompts);
  }

  function openEditor(entry) {
    const isNew = !entry;
    const overlayEditor = create("div", { class: "pv-overlay" });
    const editor = create("div", {
      class: "pv-modal pv-editor",
      role: "dialog",
      "aria-label": isNew ? "\u65b0\u5efa\u63d0\u793a\u8bcd" : "\u7f16\u8f91\u63d0\u793a\u8bcd",
    });

    const fieldTitle = create("input", { class: "pv-input", placeholder: "\u6807\u9898", value: entry?.title || "" });
    const fieldTags = create("input", {
      class: "pv-input",
      placeholder: "\u6807\u7b7e\uff08\u9017\u53f7\u5206\u9694\uff09",
      value: (entry?.tags || []).join(","),
    });
    const fieldModel = create("input", {
      class: "pv-input",
      placeholder: "\u6a21\u578b\u8303\u56f4\uff08\u9017\u53f7\u5206\u9694\uff09",
      value: (entry?.model_scope || []).join(","),
    });
    const fieldPos = create("textarea", { class: "pv-textarea", placeholder: "\u6b63\u5411\u63d0\u793a\u8bcd\uff08raw\uff0c\u652f\u6301 {name}\uff09" });
    const fieldNeg = create("textarea", { class: "pv-textarea", placeholder: "\u8d1f\u5411\u63d0\u793a\u8bcd\uff08raw\uff0c\u652f\u6301 {name}\uff09" });
    const fieldVars = create("textarea", {
      class: "pv-textarea",
      placeholder: "\u53d8\u91cf JSON\uff08\u5bf9\u8c61\uff0c\u53ef\u9009\uff09",
    });
    fieldPos.value = entry?.raw?.positive || "";
    fieldNeg.value = entry?.raw?.negative || "";
    fieldVars.value = JSON.stringify(entry?.variables || {}, null, 2);

    /* ── Generation params fields ── */
    const ep = entry?.params || {};
    const fieldSteps = create("input", { class: "pv-input pv-input-short", placeholder: "steps", type: "number", value: String(ep.steps ?? "") });
    const fieldCfg = create("input", { class: "pv-input pv-input-short", placeholder: "cfg", type: "number", step: "0.1", value: String(ep.cfg ?? "") });
    const fieldSampler = create("input", { class: "pv-input pv-input-short", placeholder: "sampler", value: ep.sampler || "" });
    const fieldScheduler = create("input", { class: "pv-input pv-input-short", placeholder: "scheduler", value: ep.scheduler || "" });
    const fieldSeed = create("input", { class: "pv-input pv-input-short", placeholder: "seed", type: "number", value: String(ep.seed ?? "") });

    const paramsGrid = create("div", { class: "pv-editor-params-grid" }, [
      create("label", { class: "pv-editor-param-label", text: "Steps" }), fieldSteps,
      create("label", { class: "pv-editor-param-label", text: "CFG" }), fieldCfg,
      create("label", { class: "pv-editor-param-label", text: "Sampler" }), fieldSampler,
      create("label", { class: "pv-editor-param-label", text: "Scheduler" }), fieldScheduler,
      create("label", { class: "pv-editor-param-label", text: "Seed" }), fieldSeed,
    ]);

    /* ── Thumbnail upload ── */
    const THUMB_MAX_W = 256;
    let pendingThumbB64 = null;
    let pendingThumbW = 0;
    let pendingThumbH = 0;
    let thumbCleared = false;

    const thumbPreview = create("img", { class: "pv-editor-thumb-preview", alt: "thumbnail" });
    const thumbPlaceholder = create("div", { class: "pv-editor-thumb-placeholder", text: "\u70b9\u51fb\u6216\u62d6\u62fd\u4e0a\u4f20\u56fe\u7247\uff08\u652f\u6301\u8bfb\u53d6\u5143\u6570\u636e\uff09" });
    const thumbFileInput = create("input", { type: "file", accept: "image/*" });
    thumbFileInput.style.display = "none";
    const btnClearThumb = create("button", { class: "pv-btn pv-small pv-danger", text: "\u6e05\u9664" });
    btnClearThumb.style.display = "none";

    const thumbDropZone = create("div", { class: "pv-editor-thumb-zone" }, [
      thumbPreview, thumbPlaceholder, thumbFileInput,
    ]);
    const thumbRow = create("div", { class: "pv-editor-thumb-row" }, [
      thumbDropZone, btnClearThumb,
    ]);

    if (entry?.thumbnail_data_url) {
      thumbPreview.src = entry.thumbnail_data_url;
      thumbPreview.style.display = "block";
      thumbPlaceholder.style.display = "none";
      btnClearThumb.style.display = "";
    } else {
      thumbPreview.style.display = "none";
    }

    function applyMetadata(d) {
      if (d.positive) fieldPos.value = d.positive;
      if (d.negative) fieldNeg.value = d.negative;
      if (d.steps) fieldSteps.value = String(d.steps);
      if (d.cfg) fieldCfg.value = String(d.cfg);
      if (d.sampler) fieldSampler.value = d.sampler;
      if (d.scheduler) fieldScheduler.value = d.scheduler;
      if (d.seed) fieldSeed.value = String(d.seed);
      if (d.model_name && !fieldModel.value.trim()) fieldModel.value = d.model_name;
    }

    async function tryExtractMetadata(fullDataUrl) {
      try {
        const res = await request("/extract_image_metadata", {
          method: "POST",
          body: JSON.stringify({ image_b64: fullDataUrl }),
        });
        const d = res.data || {};
        const keys = Object.keys(d).filter((k) => d[k] !== "" && d[k] !== 0 && d[k] != null);
        if (!keys.length) {
          toast("\u56fe\u7247\u4e2d\u672a\u68c0\u6d4b\u5230\u5143\u6570\u636e", "info");
          return;
        }
        const summary = keys.map((k) => {
          const v = String(d[k]);
          return `${k}: ${v.length > 40 ? v.slice(0, 40) + "\u2026" : v}`;
        }).join("\n");
        if (confirm(`\u68c0\u6d4b\u5230\u56fe\u7247\u5143\u6570\u636e\uff0c\u662f\u5426\u8986\u76d6\u5f53\u524d\u5b57\u6bb5\uff1f\n\n${summary}`)) {
          applyMetadata(d);
          toast("\u5df2\u4ece\u56fe\u7247\u5143\u6570\u636e\u586b\u5145\u5b57\u6bb5", "success");
        }
      } catch (e) {
        toast(`\u5143\u6570\u636e\u63d0\u53d6\u5931\u8d25: ${e}`, "error");
      }
    }

    function processImageFile(file) {
      if (!file || !file.type.startsWith("image/")) return;
      const reader = new FileReader();
      reader.onload = () => {
        const fullDataUrl = reader.result;
        const img = new Image();
        img.onload = () => {
          let w = img.width, h = img.height;
          if (w > THUMB_MAX_W) {
            h = Math.max(1, Math.round(h * (THUMB_MAX_W / w)));
            w = THUMB_MAX_W;
          }
          const canvas = document.createElement("canvas");
          canvas.width = w;
          canvas.height = h;
          canvas.getContext("2d").drawImage(img, 0, 0, w, h);
          const dataUrl = canvas.toDataURL("image/png");
          pendingThumbB64 = dataUrl;
          pendingThumbW = w;
          pendingThumbH = h;
          thumbCleared = false;
          thumbPreview.src = dataUrl;
          thumbPreview.style.display = "block";
          thumbPlaceholder.style.display = "none";
          btnClearThumb.style.display = "";
        };
        img.src = fullDataUrl;
        tryExtractMetadata(fullDataUrl);
      };
      reader.readAsDataURL(file);
    }

    thumbDropZone.addEventListener("click", (e) => {
      if (e.target === btnClearThumb) return;
      thumbFileInput.click();
    });
    thumbFileInput.addEventListener("change", () => {
      if (thumbFileInput.files?.[0]) processImageFile(thumbFileInput.files[0]);
    });
    thumbDropZone.addEventListener("dragover", (e) => { e.preventDefault(); thumbDropZone.classList.add("pv-drag-over"); });
    thumbDropZone.addEventListener("dragleave", () => { thumbDropZone.classList.remove("pv-drag-over"); });
    thumbDropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      thumbDropZone.classList.remove("pv-drag-over");
      const file = e.dataTransfer?.files?.[0];
      if (file) processImageFile(file);
    });
    btnClearThumb.addEventListener("click", (e) => {
      e.stopPropagation();
      pendingThumbB64 = null;
      pendingThumbW = 0;
      pendingThumbH = 0;
      thumbCleared = true;
      thumbPreview.style.display = "none";
      thumbPreview.src = "";
      thumbPlaceholder.style.display = "";
      btnClearThumb.style.display = "none";
      thumbFileInput.value = "";
    });

    const buttonSave = create("button", { class: "pv-btn pv-primary", text: "\u4fdd\u5b58" });
    const closeEditor = () => {
      if (document.body.contains(overlayEditor)) document.body.removeChild(overlayEditor);
    };
    const buttonCancel = create("button", {
      class: "pv-btn pv-danger",
      text: "\u53d6\u6d88",
      onclick: closeEditor,
    });

    function collectParams() {
      const p = {};
      const sv = fieldSteps.value.trim();
      if (sv) p.steps = parseInt(sv, 10) || 0;
      const cv = fieldCfg.value.trim();
      if (cv) p.cfg = parseFloat(cv) || 0;
      if (fieldSampler.value.trim()) p.sampler = fieldSampler.value.trim();
      if (fieldScheduler.value.trim()) p.scheduler = fieldScheduler.value.trim();
      const seedv = fieldSeed.value.trim();
      if (seedv) p.seed = parseInt(seedv, 10) || 0;
      return p;
    }

    buttonSave.addEventListener("click", async () => {
      let variables = {};
      try {
        variables = fieldVars.value.trim() ? JSON.parse(fieldVars.value) : {};
        if (!variables || typeof variables !== "object" || Array.isArray(variables)) {
          throw new Error("variables must be object");
        }
      } catch (error) {
        toast(`JSON \u89e3\u6790\u9519\u8bef: ${error}`, "error");
        return;
      }

      const payload = {
        title: fieldTitle.value.trim(),
        tags: parseCommaList(fieldTags.value),
        model_scope: parseCommaList(fieldModel.value),
        raw: { positive: fieldPos.value, negative: fieldNeg.value },
        variables,
        params: collectParams(),
      };

      if (pendingThumbB64) {
        payload.thumbnail_b64 = pendingThumbB64;
        payload.thumbnail_width = pendingThumbW;
        payload.thumbnail_height = pendingThumbH;
      } else if (thumbCleared) {
        payload.thumbnail_b64 = "";
        payload.thumbnail_width = 0;
        payload.thumbnail_height = 0;
      }

      try {
        if (isNew) {
          await request("/entries", { method: "POST", body: JSON.stringify(payload) });
        } else {
          await request(`/entries/${encodeURIComponent(entry.id)}`, { method: "PUT", body: JSON.stringify(payload) });
        }
        closeEditor();
        toast(isNew ? "\u521b\u5efa\u6210\u529f" : "\u4fdd\u5b58\u6210\u529f", "success");
        await reloadList();
      } catch (error) {
        toast(`\u4fdd\u5b58\u5931\u8d25: ${error}`, "error");
      }
    });

    const editorKeyHandler = (event) => {
      if (event.key === "Escape") { closeEditor(); }
    };
    overlayEditor.addEventListener("keydown", editorKeyHandler);

    const content = create("div", { class: "pv-editor-body" }, [
      fieldTitle,
      fieldTags,
      fieldModel,
      create("div", { class: "pv-detail-title", text: "\u7f29\u7565\u56fe\uff08\u4e0a\u4f20\u542b\u5143\u6570\u636e\u7684\u56fe\u7247\u53ef\u81ea\u52a8\u586b\u5145\u53c2\u6570\uff09" }),
      thumbRow,
      create("div", { class: "pv-detail-title", text: "\u751f\u6210\u53c2\u6570" }),
      paramsGrid,
      create("div", { class: "pv-split" }, [fieldPos, fieldNeg]),
      create("div", { class: "pv-detail-title", text: "\u53d8\u91cf\uff08\u53ef\u88ab nodes.variables_json \u8986\u76d6\uff09" }),
      fieldVars,
      create("div", { class: "pv-editor-actions" }, [buttonSave, buttonCancel]),
    ]);
    editor.appendChild(create("div", { class: "pv-title", text: isNew ? "\u65b0\u5efa\u63d0\u793a\u8bcd" : "\u7f16\u8f91\u63d0\u793a\u8bcd" }));
    editor.appendChild(content);
    overlayEditor.appendChild(editor);
    overlayEditor.addEventListener("click", (event) => {
      if (event.target === overlayEditor) closeEditor();
    });
    document.body.appendChild(overlayEditor);
    fieldTitle.focus();
  }

  async function reloadList() {
    list.textContent = "\u52a0\u8f7d\u4e2d...";
    const params = new URLSearchParams();
    if (inputQuery.value.trim()) params.set("q", inputQuery.value.trim());
    if (inputTags.value.trim()) params.set("tags", inputTags.value.trim());
    if (inputModel.value.trim()) params.set("model", inputModel.value.trim());
    params.set("status", currentStatus);
    params.set("limit", "50");

    const result = await request(`/entries?${params.toString()}`);
    list.textContent = "";
    const totalCount = result.items?.length || 0;
    statusBarLeft.textContent = `\u5171 ${totalCount} \u6761\u8bb0\u5f55` + (currentStatus === "deleted" ? "\uff08\u56de\u6536\u7ad9\uff09" : "");
    statusBarRight.textContent = "";
    if (!totalCount) {
      list.appendChild(create("div", { class: "pv-empty", text: "\u6ca1\u6709\u627e\u5230\u8bb0\u5f55\u3002" }));
      return;
    }

    for (const item of result.items) {
      const row = create("div", { class: "pv-row" });
      const thumb = create("img", {
        class: "pv-row-thumb",
        alt: "thumbnail",
        src: thumbUrl(item.id, item.updated_at),
      });
      thumb.onerror = () => { thumb.style.display = "none"; };
      const tagsText = (item.tags || []).join(", ");
      const timeText = formatTimestamp(item.updated_at);
      const subText = tagsText ? `\u6807\u7b7e: ${tagsText}  \u00b7  ${timeText}` : timeText;
      const left = create("div", { class: "pv-row-left" }, [
        thumb,
        create("div", { class: "pv-row-title", text: item.title || "(\u672a\u547d\u540d)" }),
        create("div", { class: "pv-row-sub", text: subText }),
      ]);
      const buttonNode = create("button", { class: "pv-btn pv-small", text: "\u65b0\u5efa\u68c0\u7d22" });
      const buttonEdit = create("button", { class: "pv-btn pv-small", text: "\u7f16\u8f91" });
      const buttonDelete = create("button", {
        class: `pv-btn pv-small ${currentStatus === "deleted" ? "" : "pv-danger"}`,
        text: currentStatus === "deleted" ? "\u8fd8\u539f" : "\u5220\u9664",
      });
      const right = create("div", { class: "pv-row-right" }, [buttonNode, buttonEdit, buttonDelete]);

      buttonNode.addEventListener("click", () => {
        try {
          const graph = app.graph || app.canvas?.graph;
          if (!graph?.add) {
            toast("\u5f53\u524d\u753b\u5e03\u4e0d\u53ef\u7528\uff0c\u8bf7\u5148\u6253\u5f00\u4e00\u4e2a\u5de5\u4f5c\u6d41", "error");
            return;
          }

          const createNode = (type) => {
            try { return globalThis.LiteGraph?.createNode?.(type) || null; }
            catch (_e) { return null; }
          };
          const node = createNode("PromptVaultQuery") || createNode("\u63d0\u793a\u8bcd\u5e93\u68c0\u7d22");
          if (!node) {
            toast("\u672a\u627e\u5230\u8282\u70b9\u7c7b\u578b\uff1aPromptVaultQuery", "error");
            return;
          }

          const canvas = app.canvas;
          const ds = canvas?.ds;
          const scale = ds?.scale || 1;
          const offset = ds?.offset || [0, 0];
          const canvasEl = canvas?.canvas;
          const viewW = canvasEl?.width || 1200;
          const viewH = canvasEl?.height || 800;
          const centerX = viewW * 0.5 / scale - offset[0];
          const centerY = viewH * 0.5 / scale - offset[1];
          node.pos = [Math.round(centerX), Math.round(centerY)];
          node.widgets?.forEach((widget) => {
            if (widget.name === "query") widget.value = "";
            if (widget.name === "title") widget.value = item.title || "";
            if (widget.name === "tags") widget.value = (item.tags || []).join(",");
            if (widget.name === "model") widget.value = (item.model_scope || []).join(",");
            if (widget.name === "top_k") widget.value = 1;
            if (widget.name === "variables_json") widget.value = "{}";
          });
          graph.add(node);
          app.graph?.setDirtyCanvas?.(true, true);
          app.canvas?.setDirty?.(true, true);

          closeManager();
          toast("\u68c0\u7d22\u8282\u70b9\u5df2\u6dfb\u52a0\u5230\u753b\u5e03", "success");
        } catch (error) {
          toast(`\u521b\u5efa\u8282\u70b9\u5931\u8d25: ${error}`, "error");
        }
      });

      buttonEdit.addEventListener("click", async () => {
        try {
          const full = await request(`/entries/${encodeURIComponent(item.id)}`);
          openEditor(full);
        } catch (error) {
          toast(`\u52a0\u8f7d\u7f16\u8f91\u6570\u636e\u5931\u8d25: ${error}`, "error");
        }
      });
      buttonDelete.addEventListener("click", async () => {
        try {
          if (currentStatus === "deleted") {
            if (!confirm("\u786e\u5b9a\u8fd8\u539f\u8bb0\u5f55\uff1f")) return;
            await request(`/entries/${encodeURIComponent(item.id)}`, {
              method: "PUT",
              body: JSON.stringify({ status: "active" }),
            });
            toast("\u8bb0\u5f55\u5df2\u8fd8\u539f", "success");
          } else {
            if (!confirm("\u786e\u5b9a\u5220\u9664\uff1f\u5c06\u79fb\u5165\u56de\u6536\u7ad9\u3002")) return;
            await request(`/entries/${encodeURIComponent(item.id)}`, { method: "DELETE" });
            toast("\u5df2\u79fb\u5165\u56de\u6536\u7ad9", "success");
          }
          await reloadList();
        } catch (error) {
          toast(`\u66f4\u65b0\u72b6\u6001\u5931\u8d25: ${error}`, "error");
        }
      });

      row.addEventListener("click", async (event) => {
        if (event.target === buttonNode || event.target === buttonEdit || event.target === buttonDelete) return;
        try {
          list.querySelectorAll(".pv-row-active").forEach((el) => el.classList.remove("pv-row-active"));
          row.classList.add("pv-row-active");
          const full = await request(`/entries/${encodeURIComponent(item.id)}`);
          const assembled = await request("/assemble", {
            method: "POST",
            body: JSON.stringify({ entry_id: item.id, variables_override: {} }),
          });
          renderDetail(full, assembled);
        } catch (error) {
          toast(`\u52a0\u8f7d\u8be6\u60c5\u5931\u8d25: ${error}`, "error");
        }
      });

      row.appendChild(left);
      row.appendChild(right);
      list.appendChild(row);
    }

    const firstItem = result.items[0];
    if (firstItem?.id) {
      try {
        const full = await request(`/entries/${encodeURIComponent(firstItem.id)}`);
        const assembled = await request("/assemble", {
          method: "POST",
          body: JSON.stringify({ entry_id: firstItem.id, variables_override: {} }),
        });
        renderDetail(full, assembled);
        const firstRow = list.querySelector(".pv-row");
        if (firstRow) firstRow.classList.add("pv-row-active");
      } catch (_e) { /* ignore */ }
    }
  }

  /* ── Keyboard: Enter to search, Escape to close ── */
  const triggerSearch = () => reloadList().catch((e) => toast(String(e), "error"));
  buttonSearch.addEventListener("click", triggerSearch);
  [inputQuery, inputTags, inputModel].forEach((inp) => {
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); triggerSearch(); }
    });
  });

  const managerKeyHandler = (event) => {
    if (event.key === "Escape") closeManager();
  };
  overlay.addEventListener("keydown", managerKeyHandler);

  buttonNew.addEventListener("click", () => openEditor(null));
  buttonClose.addEventListener("click", closeManager);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeManager();
  });

  modal.appendChild(title);
  modal.appendChild(toolbar);
  modal.appendChild(body);
  modal.appendChild(statusBar);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  inputQuery.focus();

  loadTags().catch((e) => {
    sidebar.textContent = "";
    sidebar.appendChild(create("div", { class: "pv-empty", text: `\u6807\u7b7e\u52a0\u8f7d\u5931\u8d25: ${e}` }));
  });
  reloadList().catch((e) => {
    list.textContent = "";
    list.appendChild(create("div", { class: "pv-empty", text: `Error: ${e}` }));
  });
}

let _modelResCache = null;
async function getModelResolutions() {
  if (_modelResCache) return _modelResCache;
  try {
    const resp = await fetch("/promptvault/model_resolutions");
    if (resp.ok) _modelResCache = await resp.json();
  } catch (_e) { /* ignore */ }
  return _modelResCache || {};
}

function setupModelResolutionNode(node) {
  const modelWidget = node.widgets?.find((w) => w.name === "model");
  const sizeWidget = node.widgets?.find((w) => w.name === "size");
  if (!modelWidget || !sizeWidget) return;

  const originalSizes = [...(sizeWidget.options?.values || [])];

  async function updateSizes() {
    const data = await getModelResolutions();
    const modelSizes = data[modelWidget.value];
    if (modelSizes && modelSizes.length) {
      sizeWidget.options.values = modelSizes;
      if (!modelSizes.includes(sizeWidget.value)) {
        sizeWidget.value = modelSizes[0];
      }
    } else {
      sizeWidget.options.values = originalSizes;
    }
    app.graph?.setDirtyCanvas?.(true, false);
  }

  const origCallback = modelWidget.callback;
  modelWidget.callback = function (...args) {
    if (origCallback) origCallback.apply(this, args);
    updateSizes();
  };

  updateSizes();
}

if (!globalThis[GUARD_KEY]) {
  globalThis[GUARD_KEY] = true;
  app.registerExtension({
    name: EXT_ID,
    async setup() {
      console.log("[PromptVault] setup start");
      ensureStyle();

      let tries = 0;
      const timer = setInterval(async () => {
        tries += 1;
        if (await injectTopMenuButton(openManager)) {
          clearInterval(timer);
          return;
        }
        if (injectLegacyMenuButton(openManager)) {
          clearInterval(timer);
          return;
        }
        if (tries >= 20) {
          clearInterval(timer);
          ensureFloatingButton(openManager);
        }
      }, 500);
    },
    nodeCreated(node) {
      if (node.comfyClass === "ModelResolution") {
        setupModelResolutionNode(node);
      }
    },
  });
}
