import { app } from "../../scripts/app.js";

const EXT_NAME = "ComfyUI_PromptVault";
const EXT_ID = "ComfyUI_PromptVault.TopMenu";
const BASE_URL = `/extensions/${EXT_NAME}/`;
const GUARD_KEY = "__PROMPTVAULT_REGISTERED__";
const ASSET_VERSION = "20260228-llm-multi-rules";

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

function ensureStylesheet(id, file) {
  let link = document.getElementById(id);
  if (!link) {
    link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  link.href = `${BASE_URL}${file}?v=${ASSET_VERSION}`;
  return link;
}

function ensureStyle() {
  ensureStylesheet("promptvault-style", "promptvault.css");
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`/promptvault${path}`, {
    ...options,
    headers,
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try {
      const parsed = JSON.parse(text);
      message = parsed.error || parsed.message || text;
    } catch (_error) {
      message = text;
    }
    throw new Error(`${response.status}: ${message}`);
  }
  return await response.json();
}

function getNodeWidget(node, name) {
  return node?.widgets?.find((widget) => widget.name === name) || null;
}

function getNodeWidgetValue(node, name, fallback = "") {
  return getNodeWidget(node, name)?.value ?? fallback;
}

function setNodeWidgetValue(node, name, value) {
  const widget = getNodeWidget(node, name);
  if (!widget) return;
  widget.value = value;
  if (typeof widget.callback === "function") {
    try {
      widget.callback(value, app.canvas, node, null, widget);
    } catch (_error) {
      /* ignore widget callback failures */
    }
  }
}

function markNodeDirty() {
  app.graph?.setDirtyCanvas?.(true, true);
  app.canvas?.setDirty?.(true, true);
}

function openImageLightbox(imageUrl, title = "图片预览") {
  if (!imageUrl) return;
  const overlay = create("div", { class: "pv-overlay pv-image-lightbox" });
  const modal = create("div", { class: "pv-image-lightbox-modal" });
  const closeLightbox = () => {
    document.removeEventListener("keydown", onKeyDown);
    if (document.body.contains(overlay)) document.body.removeChild(overlay);
  };
  const onKeyDown = (event) => {
    if (event.key === "Escape") closeLightbox();
  };
  document.addEventListener("keydown", onKeyDown);

  const header = create("div", { class: "pv-title" }, [
    create("span", { text: title }),
    create("div", { class: "pv-title-actions" }, [
      create("button", { class: "pv-btn pv-danger", text: "关闭", onclick: closeLightbox }),
    ]),
  ]);
  const image = create("img", {
    class: "pv-image-lightbox-img",
    alt: title,
    src: imageUrl,
  });
  image.addEventListener("load", () => {
    const vw = Math.max(320, Math.floor(window.innerWidth * 0.9));
    const vh = Math.max(320, Math.floor(window.innerHeight * 0.88));
    const naturalW = image.naturalWidth || 0;
    const naturalH = image.naturalHeight || 0;
    const targetW = Math.min(Math.max(420, naturalW + 48), vw, 900);
    const targetH = Math.min(Math.max(360, naturalH + 88), vh, 820);
    modal.style.width = `${targetW}px`;
    modal.style.height = `${targetH}px`;
  });
  const body = create("div", { class: "pv-image-lightbox-body" }, [image]);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeLightbox();
  });
  modal.appendChild(header);
  modal.appendChild(body);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
}

function buildPreviewSummary(entry, assembled, extra = {}) {
  return {
    id: entry?.id || "",
    title: entry?.title || "未命名",
    tags: entry?.tags || [],
    model_scope: entry?.model_scope || [],
    favorite: !!entry?.favorite,
    score: Number(entry?.score || 0),
    updated_at: entry?.updated_at || "",
    positive: assembled?.positive || entry?.raw?.positive || "",
    negative: assembled?.negative || entry?.raw?.negative || "",
    thumbnail_url: entry?.id ? thumbUrl(entry.id, entry?.updated_at || "") : "",
    match_source: extra.match_source || "matched",
  };
}

async function fetchPreviewEntryById(entryId, extra = {}) {
  const full = await request(`/entries/${encodeURIComponent(entryId)}`);
  const assembled = await request("/assemble", {
    method: "POST",
    body: JSON.stringify({ entry_id: entryId, variables_override: {} }),
  });
  return buildPreviewSummary(full, assembled, extra);
}

async function searchPreviewHits({ q, tags, model, limit = 10 }) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (tags?.length) params.set("tags", tags.join(","));
  if (model) params.set("model", model);
  params.set("status", "active");
  params.set("limit", String(limit));
  params.set("offset", "0");
  params.set("sort", "updated_desc");
  const result = await request(`/entries?${params.toString()}`);
  return result.items || [];
}

async function resolveQueryPreview(node) {
  const mode = String(getNodeWidgetValue(node, "mode", "auto") || "auto").trim();
  const lockedEntryId = String(getNodeWidgetValue(node, "entry_id", "") || "").trim();
  if (mode === "locked" && lockedEntryId) {
    return await fetchPreviewEntryById(lockedEntryId, { match_source: "locked" });
  }
  const lockedWithoutId = mode === "locked" && !lockedEntryId;

  const query = String(getNodeWidgetValue(node, "query", "") || "").trim();
  const title = String(getNodeWidgetValue(node, "title", "") || "").trim();
  const tags = parseCommaList(String(getNodeWidgetValue(node, "tags", "") || ""));
  const model = String(getNodeWidgetValue(node, "model", "") || "").trim();
  const previewLimit = 10;
  const searchQ = title ? `${title} ${query}`.trim() : query;

  const trySearch = async (qv, tagsV, modelV) => {
    const rows = await searchPreviewHits({ q: qv, tags: tagsV, model: modelV, limit: previewLimit });
    return rows || [];
  };

  let hits = await trySearch(searchQ, tags, model);
  let matchSource = lockedWithoutId ? "locked_missing_id" : "matched";
  if (!hits.length && (tags.length || model)) hits = await trySearch(searchQ, tags, "");
  if (!hits.length && tags.length) hits = await trySearch(searchQ, [], model);
  if (!hits.length && (tags.length || model)) hits = await trySearch(searchQ, [], "");
  if (!hits.length && title && query) hits = await trySearch(query, [], "");
  if (!hits.length && title) hits = await trySearch(title, [], "");
  if (!hits.length) {
    hits = await trySearch("", [], "");
    matchSource = lockedWithoutId ? "locked_missing_id_fallback_latest" : "fallback_latest";
  }

  if (title && hits.length) {
    const lowerTitle = title.toLowerCase();
    const titleHits = hits.filter((item) => String(item?.title || "").toLowerCase().includes(lowerTitle));
    if (titleHits.length) hits = titleHits;
  }

  const best = hits[0];
  if (!best?.id) return null;
  return await fetchPreviewEntryById(best.id, { match_source: matchSource });
}

function openQueryPreviewModal(node, preview) {
  const currentMode = String(getNodeWidgetValue(node, "mode", "auto") || "auto").trim();
  const currentEntryId = String(getNodeWidgetValue(node, "entry_id", "") || "").trim();
  const alreadyLocked = currentMode === "locked" && currentEntryId === preview.id;

  const overlay = create("div", { class: "pv-overlay" });
  const modal = create("div", { class: "pv-modal pv-preview-modal" });
  const closePreview = () => {
    if (document.body.contains(overlay)) document.body.removeChild(overlay);
  };

  const header = create("div", { class: "pv-title" }, [
    create("span", { text: "检索预览" }),
    create("div", { class: "pv-title-actions" }, [
      create("button", { class: "pv-btn pv-danger", text: "关闭", onclick: closePreview }),
    ]),
  ]);

  const metaText = [
    `ID: ${(preview.id || "").slice(0, 8)}…`,
    preview.updated_at ? `更新于 ${formatTimestamp(preview.updated_at)}` : "",
  ].filter(Boolean).join(" · ");

  const heroMeta = create("div", { class: "pv-preview-meta", text: metaText });
  const heroStats = create("div", { class: "pv-preview-stats" }, [
    create("span", {
      class: `pv-preview-pill ${preview.favorite ? "pv-preview-pill-hot" : ""}`,
      text: preview.favorite ? "已收藏" : "未收藏",
    }),
    create("span", { class: "pv-preview-pill", text: `评分 ${Number(preview.score || 0).toFixed(1)}` }),
    create("span", {
      class: "pv-preview-pill",
      text: preview.model_scope?.length ? preview.model_scope.join(" / ") : "不限模型",
    }),
  ]);
  const heroTags = create(
    "div",
    { class: "pv-preview-tags" },
    (preview.tags || []).map((tag) => create("span", { class: "pv-card-tag", text: tag })),
  );
  const thumb = create("img", {
    class: "pv-preview-thumb",
    alt: "thumbnail",
    src: preview.thumbnail_url || "",
  });
  const thumbEmpty = create("div", { class: "pv-preview-thumb pv-preview-thumb-empty", text: "暂无缩略图" });
  thumb.onerror = () => {
    thumb.replaceWith(thumbEmpty);
  };
  if (!preview.thumbnail_url) {
    thumb.replaceWith(thumbEmpty);
  }
  thumb.addEventListener("click", (event) => {
    event.stopPropagation();
    openImageLightbox(preview.thumbnail_url, preview.title || "图片预览");
  });

  const hero = create("div", { class: "pv-preview-hero" }, [
    create("div", { class: "pv-preview-hero-main" }, [
      create("div", { class: "pv-preview-title", text: preview.title || "未命名" }),
      heroMeta,
      heroStats,
      heroTags,
    ]),
    create("div", { class: "pv-preview-hero-side" }, [preview.thumbnail_url ? thumb : thumbEmpty]),
  ]);

  const noticeText =
    preview.match_source === "locked_missing_id_fallback_latest"
      ? "当前为锁定模式，但条目 ID 为空；已按自动检索回退到最近更新记录。"
      : preview.match_source === "locked_missing_id"
        ? "当前为锁定模式，但条目 ID 为空；以下结果按自动检索预览。"
      : preview.match_source === "fallback_latest"
      ? "未命中当前条件，已回退到最近更新记录。"
      : preview.match_source === "locked"
        ? "当前预览来自已锁定条目。"
        : "当前结果按节点条件命中。";
  const noticeClass =
    preview.match_source === "fallback_latest" || preview.match_source === "locked_missing_id_fallback_latest"
      ? "pv-preview-notice pv-preview-notice-warn"
      : "pv-preview-notice";

  const body = create("div", { class: "pv-detail-body pv-preview-body" }, [
    hero,
    create("div", { class: noticeClass, text: noticeText }),
    create("div", { class: "pv-preview-section" }, [
      create("div", { class: "pv-detail-title", text: "正向提示词" }),
      create("pre", { class: "pv-pre pv-preview-code", text: preview.positive || "" }),
    ]),
    create("div", { class: "pv-preview-section" }, [
      create("div", { class: "pv-detail-title", text: "负向提示词" }),
      create("pre", { class: "pv-pre pv-preview-code", text: preview.negative || "" }),
    ]),
  ]);

  const lockButton = create("button", {
    class: "pv-btn pv-primary",
    text: "锁定到当前节点",
  });
  if (alreadyLocked) lockButton.textContent = "已锁定当前条目";
  lockButton.disabled = alreadyLocked;
  lockButton.addEventListener("click", () => {
    setNodeWidgetValue(node, "mode", "locked");
    setNodeWidgetValue(node, "entry_id", preview.id || "");
    if (preview.title) node.title = `检索: ${preview.title}`;
    markNodeDirty();
    toast(`已锁定：${preview.title || "未命名"}`, "success");
    closePreview();
  });

  const footer = create("div", { class: "pv-detail-actions" }, [
    lockButton,
    create("button", { class: "pv-btn", text: "关闭", onclick: closePreview }),
  ]);

  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closePreview();
  });
  modal.appendChild(header);
  modal.appendChild(body);
  modal.appendChild(footer);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
}

function setupPromptVaultQueryNode(node) {
  if (!node || node._pvQueryPreviewBound) return;
  node._pvQueryPreviewBound = true;
  node.addWidget("button", "查询预览", "查询预览", async () => {
    try {
      const preview = await resolveQueryPreview(node);
      if (!preview?.id) {
        toast("未找到匹配记录", "info");
        return;
      }
      openQueryPreviewModal(node, preview);
    } catch (error) {
      toast(`查询预览失败: ${error}`, "error");
    }
  });
}

let _llmModuleReady = null;
async function ensureLLMModule() {
  ensureStylesheet("promptvault-llm-style", "promptvault-llm.css");
  if (window.PromptVaultLLM) {
    if (!window.PromptVaultLLM._inited) {
      window.PromptVaultLLM.init({ create, request, toast });
      window.PromptVaultLLM._inited = true;
    }
    return Promise.resolve();
  }
  if (_llmModuleReady) return _llmModuleReady;
  _llmModuleReady = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `${BASE_URL}promptvault-llm.js?v=${ASSET_VERSION}`;
    script.onload = () => {
      window.PromptVaultLLM.init({ create, request, toast });
      window.PromptVaultLLM._inited = true;
      resolve();
    };
    script.onerror = () => reject(new Error("Failed to load promptvault-llm.js"));
    document.head.appendChild(script);
  });
  return _llmModuleReady;
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
  const buttonExportCsv = create("button", { class: "pv-btn", text: "\u5bfc\u51fa CSV" });
  const buttonImport = create("button", { class: "pv-btn", text: "\u5bfc\u5165" });
  const importInput = create("input", { type: "file", accept: ".json,.csv,application/json,text/csv" });
  importInput.style.display = "none";
  const buttonLLMSettings = create("button", { class: "pv-btn", text: "LLM \u8bbe\u7f6e" });
  const buttonToggleSidebar = create("button", { class: "pv-btn", text: "\u6807\u7b7e\u680f" });
  const paginationInfo = create("span", { class: "pv-toolbar-page-info", text: "1 / 1 \u9875" });
  const buttonPrevPage = create("button", { class: "pv-btn pv-small", text: "\u4e0a\u4e00\u9875" });
  const buttonNextPage = create("button", { class: "pv-btn pv-small", text: "\u4e0b\u4e00\u9875" });
  const buttonClose = create("button", { class: "pv-btn pv-danger", text: "\u5173\u95ed" });
  const titleActions = create("div", { class: "pv-title-actions" }, [
    buttonNew,
    buttonImport,
    buttonExportCsv,
    buttonLLMSettings,
    buttonToggleSidebar,
    selectStatus,
    buttonPurge,
    buttonClose,
  ]);
  const title = create("div", { class: "pv-title" }, [
    titleLabel,
    titleActions,
  ]);
  const searchSpacer = create("div", { class: "pv-toolbar-spacer" });
  const toolbar = create("div", { class: "pv-toolbar pv-toolbar-search" }, [
    inputQuery,
    inputTags,
    inputModel,
    buttonSearch,
    searchSpacer,
    paginationInfo,
    buttonPrevPage,
    buttonNextPage,
  ]);

  const sidebar = create("div", { class: "pv-sidebar" });
  const resultControls = create("div", { class: "pv-results-toolbar" });
  const list = create("div", { class: "pv-list pv-card-grid" });
  const resultsPane = create("div", { class: "pv-results-pane" }, [resultControls, list]);
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
  const body = create("div", { class: "pv-body" }, [sidebar, resultsPane, detail]);

  const statusBarLeft = create("span", { class: "pv-statusbar-left", text: "\u5c31\u7eea" });
  const statusBarRight = create("span", { class: "pv-statusbar-right", text: "" });
  const statusBar = create("div", { class: "pv-statusbar" }, [statusBarLeft, statusBarRight]);

  let selectedTag = "";
  let currentStatus = "active";
  let sidebarVisible = false;
  let currentOffset = 0;
  let currentTotal = 0;
  let selectedCardId = "";
  const pageLimit = 12;
  const quickFilters = {
    favorite_only: false,
    has_thumbnail: false,
  };
  let currentSort = "updated_desc";
  let currentViewMode = "card_compact";

  sidebar.style.display = "none";
  body.classList.add("pv-body-no-sidebar");

  function closeManager() {
    if (document.body.contains(overlay)) document.body.removeChild(overlay);
  }

  function setStatus(leftText, rightText = "") {
    statusBarLeft.textContent = leftText;
    statusBarRight.textContent = rightText;
  }

  async function downloadExport(format) {
    const upper = format.toUpperCase();
    setStatus(`正在导出 ${upper}...`);
    try {
      const response = await fetch(`/promptvault/export?format=${encodeURIComponent(format)}`);
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      const dispo = response.headers.get("Content-Disposition") || "";
      const match = dispo.match(/filename="?([^"]+)"?/i);
      anchor.href = url;
      anchor.download = match?.[1] || `promptvault-export.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      toast(`${upper} 导出完成`, "success");
      setStatus(`${upper} 导出完成`);
    } catch (error) {
      toast(`导出失败: ${error}`, "error");
      setStatus(`导出失败: ${error}`);
    }
  }

  async function uploadImport(file) {
    const name = file?.name || "";
    if (!file) return;
    const format = name.toLowerCase().endsWith(".csv") ? "csv" : "json";
    const formData = new FormData();
    formData.append("file", file);
    formData.append("format", format);
    formData.append("conflict_strategy", "merge");
    setStatus(`正在导入 ${name}...`, "merge");
    try {
      const result = await request("/import", { method: "POST", body: formData });
      const summary = `创建 ${result.created || 0}，更新 ${result.updated || 0}，跳过 ${result.skipped || 0}，错误 ${(result.errors || []).length}`;
      toast(`导入完成: ${summary}`, (result.errors || []).length ? "info" : "success", 5000);
      setStatus(`导入完成: ${summary}`);
      if ((result.errors || []).length) {
        const brief = result.errors.slice(0, 5).map((item) => `${item.record_type}/${item.id}: ${item.error}`).join("\n");
        alert(`导入结果\n\n${summary}\n\n错误明细:\n${brief}`);
      } else {
        alert(`导入结果\n\n${summary}`);
      }
      await loadTags();
      await reloadList();
    } catch (error) {
      toast(`导入失败: ${error}`, "error", 5000);
      setStatus(`导入失败: ${error}`);
    } finally {
      importInput.value = "";
    }
  }

  function resetPagination() {
    currentOffset = 0;
  }

  function activeFilterSummary() {
    const labels = [];
    if (quickFilters.favorite_only) labels.push("仅收藏");
    if (quickFilters.has_thumbnail) labels.push("有缩略图");
    return labels.join(" · ");
  }

  const quickFilterFavorite = create("button", { class: "pv-filter-chip", text: "仅收藏" });
  const quickFilterThumb = create("button", { class: "pv-filter-chip", text: "有缩略图" });
  const buttonClearFilters = create("button", { class: "pv-btn pv-small", text: "清空筛选" });
  const sortSelect = create(
    "select",
    { class: "pv-input pv-results-sort", title: "排序方式" },
    [
      create("option", { value: "updated_desc", text: "最近更新" }),
      create("option", { value: "score_desc", text: "评分优先" }),
      create("option", { value: "favorite_desc", text: "收藏优先" }),
    ],
  );
  const filterHint = create("span", { class: "pv-results-hint", text: "缩略图优先浏览" });
  resultControls.appendChild(create("div", { class: "pv-filter-chip-row" }, [
    quickFilterFavorite,
    quickFilterThumb,
    buttonClearFilters,
    filterHint,
  ]));
  resultControls.appendChild(sortSelect);

  function refreshQuickFilterUI() {
    quickFilterFavorite.classList.toggle("pv-filter-chip-active", !!quickFilters.favorite_only);
    quickFilterThumb.classList.toggle("pv-filter-chip-active", !!quickFilters.has_thumbnail);
    sortSelect.value = currentSort;
  }

  function updatePaginationUI(itemsCount = 0) {
    const total = Math.max(0, currentTotal);
    const page = total ? Math.floor(currentOffset / pageLimit) + 1 : 1;
    const totalPages = Math.max(1, Math.ceil(total / pageLimit));
    const start = total ? currentOffset + 1 : 0;
    const end = total ? Math.min(currentOffset + itemsCount, total) : 0;
    paginationInfo.textContent = `${page} / ${totalPages} 页`;
    buttonPrevPage.disabled = currentOffset <= 0;
    buttonNextPage.disabled = currentOffset + itemsCount >= total;
    statusBarLeft.textContent = `共 ${total} 条记录` + (total ? ` · 显示 ${start}-${end}` : "") + (currentStatus === "deleted" ? "（回收站）" : "");
  }

  function updatePaginationUI(itemsCount = 0) {
    const total = Math.max(0, currentTotal);
    const page = total ? Math.floor(currentOffset / pageLimit) + 1 : 1;
    const totalPages = Math.max(1, Math.ceil(total / pageLimit));
    const start = total ? currentOffset + 1 : 0;
    const end = total ? Math.min(currentOffset + itemsCount, total) : 0;
    paginationInfo.textContent = `${page} / ${totalPages} 页`;
    buttonPrevPage.disabled = currentOffset <= 0;
    buttonNextPage.disabled = currentOffset + itemsCount >= total;
    const filterSummary = activeFilterSummary();
    const sortSummary =
      currentSort === "score_desc" ? "评分优先" :
      currentSort === "favorite_desc" ? "收藏优先" :
      "最近更新";
    statusBarLeft.textContent = `共 ${total} 条记录`
      + (total ? ` · 显示 ${start}-${end}` : "")
      + (currentStatus === "deleted" ? "（回收站）" : "")
      + (filterSummary ? ` · 筛选: ${filterSummary}` : "")
      + ` · 排序: ${sortSummary}`;
  }

  const viewList = create("button", { class: "pv-filter-chip", text: "列表" });
  const viewCardCompact = create("button", { class: "pv-filter-chip", text: "卡片" });
  const viewModeGroup = create("div", { class: "pv-filter-chip-row" }, [viewList, viewCardCompact]);
  resultControls.appendChild(viewModeGroup);

  quickFilterFavorite.textContent = "仅收藏";
  quickFilterThumb.textContent = "有缩略图";
  buttonClearFilters.textContent = "清空筛选";
  filterHint.textContent = "可切换列表与卡片视图";
  sortSelect.title = "排序方式";
  if (sortSelect.options[0]) sortSelect.options[0].textContent = "最近更新";
  if (sortSelect.options[1]) sortSelect.options[1].textContent = "评分优先";
  if (sortSelect.options[2]) sortSelect.options[2].textContent = "收藏优先";

  refreshQuickFilterUI = function () {
    quickFilterFavorite.classList.toggle("pv-filter-chip-active", !!quickFilters.favorite_only);
    quickFilterThumb.classList.toggle("pv-filter-chip-active", !!quickFilters.has_thumbnail);
    viewList.classList.toggle("pv-filter-chip-active", currentViewMode === "list");
    viewCardCompact.classList.toggle("pv-filter-chip-active", currentViewMode === "card_compact");
    sortSelect.value = currentSort;
  };

  updatePaginationUI = function (itemsCount = 0) {
    const total = Math.max(0, currentTotal);
    const page = total ? Math.floor(currentOffset / pageLimit) + 1 : 1;
    const totalPages = Math.max(1, Math.ceil(total / pageLimit));
    const start = total ? currentOffset + 1 : 0;
    const end = total ? Math.min(currentOffset + itemsCount, total) : 0;
    paginationInfo.textContent = `${page} / ${totalPages} 页`;
    buttonPrevPage.disabled = currentOffset <= 0;
    buttonNextPage.disabled = currentOffset + itemsCount >= total;
    const activeFilters = [];
    if (quickFilters.favorite_only) activeFilters.push("仅收藏");
    if (quickFilters.has_thumbnail) activeFilters.push("有缩略图");
    const viewLabel = currentViewMode === "list" ? "列表" : "卡片";
    const sortLabel =
      currentSort === "score_desc" ? "评分优先" :
      currentSort === "favorite_desc" ? "收藏优先" :
      "最近更新";
    statusBarLeft.textContent = `共 ${total} 条记录`
      + (total ? ` · 显示 ${start}-${end}` : "")
      + (currentStatus === "deleted" ? "（回收站）" : "")
      + (activeFilters.length ? ` · 筛选: ${activeFilters.join(" / ")}` : "")
      + ` · 视图: ${viewLabel}`
      + ` · 排序: ${sortLabel}`;
  };

  function applyResultViewMode() {
    list.classList.remove("pv-card-grid", "pv-card-grid-compact", "pv-list-mode");
    if (currentViewMode === "list") {
      list.classList.add("pv-list-mode");
      detail.style.display = "";
      body.style.gridTemplateColumns = sidebarVisible ? "" : "";
      return;
    }
    list.classList.add("pv-card-grid");
    list.classList.add("pv-card-grid-compact");
    detail.style.display = "none";
    body.style.gridTemplateColumns = sidebarVisible ? "180px 1fr" : "1fr";
  }

  buttonLLMSettings.addEventListener("click", async () => {
    await ensureLLMModule();
    window.PromptVaultLLM.openLLMSettings();
  });

  buttonToggleSidebar.addEventListener("click", () => {
    sidebarVisible = !sidebarVisible;
    if (sidebarVisible) {
      sidebar.style.display = "";
      body.classList.remove("pv-body-no-sidebar");
    } else {
      sidebar.style.display = "none";
      body.classList.add("pv-body-no-sidebar");
    }
    applyResultViewMode();
  });

  selectStatus.addEventListener("change", () => {
    currentStatus = selectStatus.value === "deleted" ? "deleted" : "active";
    resetPagination();
    reloadList().catch((e) => toast(String(e), "error"));
  });

  buttonPrevPage.addEventListener("click", () => {
    if (currentOffset <= 0) return;
    currentOffset = Math.max(0, currentOffset - pageLimit);
    reloadList().catch((e) => toast(String(e), "error"));
  });

  buttonNextPage.addEventListener("click", () => {
    if (currentOffset + pageLimit >= currentTotal) return;
    currentOffset += pageLimit;
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
  buttonExportCsv.addEventListener("click", () => {
    downloadExport("csv").catch((e) => toast(String(e), "error"));
  });
  buttonImport.addEventListener("click", () => importInput.click());
  importInput.addEventListener("change", async () => {
    if (importInput.files?.[0]) {
      await uploadImport(importInput.files[0]);
    }
  });
  quickFilterFavorite.addEventListener("click", () => {
    quickFilters.favorite_only = !quickFilters.favorite_only;
    refreshQuickFilterUI();
    resetPagination();
    reloadList().catch((e) => toast(String(e), "error"));
  });
  quickFilterThumb.addEventListener("click", () => {
    quickFilters.has_thumbnail = !quickFilters.has_thumbnail;
    refreshQuickFilterUI();
    resetPagination();
    reloadList().catch((e) => toast(String(e), "error"));
  });
  buttonClearFilters.addEventListener("click", () => {
    quickFilters.favorite_only = false;
    quickFilters.has_thumbnail = false;
    refreshQuickFilterUI();
    resetPagination();
    reloadList().catch((e) => toast(String(e), "error"));
  });
  sortSelect.addEventListener("change", () => {
    currentSort = sortSelect.value || "updated_desc";
    refreshQuickFilterUI();
    resetPagination();
    reloadList().catch((e) => toast(String(e), "error"));
  });
  viewList.addEventListener("click", () => {
    currentViewMode = "list";
    refreshQuickFilterUI();
    reloadList().catch((e) => toast(String(e), "error"));
  });
  viewCardCompact.addEventListener("click", () => {
    currentViewMode = "card_compact";
    refreshQuickFilterUI();
    reloadList().catch((e) => toast(String(e), "error"));
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
        resetPagination();
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
            resetPagination();
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

  function renderDetailContent(targetBody, entry, assembled, updateStatus = true) {
    currentPositive = assembled.positive || "";
    if (updateStatus) {
      statusBarRight.textContent = `\u5f53\u524d: ${entry.title || "\u672a\u547d\u540d"} | ID: ${(entry.id || "").slice(0, 8)}\u2026 | v${entry.version || 1}`;
    }
    const params = entry.params || {};
    const matchReasons = entry.match_reasons || assembled.match_reasons || [];
    const tableRows = [
      ["\u6807\u9898", entry.title || ""],
      ["ID", entry.id || ""],
      ["\u6807\u7b7e", (entry.tags || []).join(", ")],
      ["\u6a21\u578b", (entry.model_scope || []).join(", ")],
      ["\u7248\u672c", String(entry.version || 1)],
      ["命中原因", matchReasons.length ? matchReasons.join(" / ") : "无"],
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

    const favoriteButton = create("button", {
      class: `pv-btn pv-small ${entry.favorite ? "pv-primary" : ""}`,
      text: entry.favorite ? "★ 已收藏" : "☆ 收藏",
      title: "切换收藏状态",
    });
    const scoreOptions = [0, 1, 2, 3, 4, 5];
    const scoreSelect = create(
      "select",
      { class: "pv-input pv-detail-score", title: "评分" },
      scoreOptions.map((value) => create("option", { value: String(value), text: `评分 ${value}` })),
    );
    scoreSelect.value = String(Math.max(0, Math.min(5, Math.round(Number(entry.score || 0)))));
    scoreSelect.style.display = "none";
    const currentScore = Math.max(0, Math.min(5, Math.round(Number(entry.score || 0))));
    const scoreStars = create("div", { class: "pv-detail-stars", title: "评分" });
    const detailActions = create("div", { class: "pv-detail-actions" }, [
      favoriteButton,
      scoreStars,
      scoreSelect,
    ]);

    const refreshDetailMeta = async (patch) => {
      try {
        await request(`/entries/${encodeURIComponent(entry.id)}`, {
          method: "PUT",
          body: JSON.stringify({
            ...patch,
            version: entry.version,
            updated_at: entry.updated_at,
          }),
        });
        const full = await request(`/entries/${encodeURIComponent(entry.id)}`);
        full.match_reasons = entry.match_reasons || [];
        const freshAssembled = await request("/assemble", {
          method: "POST",
          body: JSON.stringify({ entry_id: entry.id, variables_override: {} }),
        });
        freshAssembled.match_reasons = entry.match_reasons || [];
        renderDetailContent(targetBody, full, freshAssembled, updateStatus);
        await reloadList();
      } catch (error) {
        toast(`更新失败: ${error}`, "error");
      }
    };

    favoriteButton.addEventListener("click", async () => {
      await refreshDetailMeta({ favorite: entry.favorite ? 0 : 1 });
    });
    for (let value = 1; value <= 5; value += 1) {
      const starButton = create("button", {
        class: `pv-star-btn ${value <= currentScore ? "pv-star-btn-on" : ""}`,
        text: "★",
        title: `评分 ${value}`,
      });
      starButton.addEventListener("click", async () => {
        const nextScore = value === currentScore ? 0 : value;
        await refreshDetailMeta({ score: nextScore });
      });
      scoreStars.appendChild(starButton);
    }
    scoreSelect.addEventListener("change", async () => {
      await refreshDetailMeta({ score: Number(scoreSelect.value || 0) });
    });

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

    targetBody.textContent = "";
    targetBody.appendChild(thumb);
    targetBody.appendChild(detailActions);
    targetBody.appendChild(table);
    targetBody.appendChild(prompts);
  }

  function renderDetail(entry, assembled) {
    renderDetailContent(detailBody, entry, assembled, true);
  }

  function openDetailModal(entry, assembled) {
    const overlayDetail = create("div", { class: "pv-overlay" });
    const modalDetail = create("div", {
      class: "pv-modal pv-editor",
      role: "dialog",
      "aria-label": "提示词详情",
    });
    const bodyDetail = create("div", { class: "pv-detail-body" });
    const closeDetail = () => {
      if (document.body.contains(overlayDetail)) document.body.removeChild(overlayDetail);
    };
    const titleBar = create("div", { class: "pv-title" }, [
      create("span", { text: entry.title || "提示词详情" }),
      create("button", { class: "pv-btn pv-danger", text: "关闭", onclick: closeDetail }),
    ]);
    const shell = create("div", { class: "pv-detail" }, [bodyDetail]);
    renderDetailContent(bodyDetail, entry, assembled, false);
    modalDetail.appendChild(titleBar);
    modalDetail.appendChild(shell);
    overlayDetail.appendChild(modalDetail);
    overlayDetail.addEventListener("click", (event) => {
      if (event.target === overlayDetail) closeDetail();
    });
    document.body.appendChild(overlayDetail);
  }

  function openEditor(entry) {
    const isNew = !entry;
    const overlayEditor = create("div", { class: "pv-overlay" });
    const editor = create("div", {
      class: "pv-modal pv-editor",
      role: "dialog",
      "aria-label": isNew ? "\u65b0\u5efa\u63d0\u793a\u8bcd" : "\u7f16\u8f91\u63d0\u793a\u8bcd",
    });

    const fieldTitle = create("input", { class: "pv-input pv-input-flex", placeholder: "\u6807\u9898", value: entry?.title || "" });
    const fieldTags = create("input", {
      class: "pv-input pv-input-flex",
      placeholder: "\u6807\u7b7e\uff08\u9017\u53f7\u5206\u9694\uff09",
      value: (entry?.tags || []).join(","),
    });
    const btnAiTitle = create("button", { class: "pv-btn pv-ai-tag-btn", text: "AI \u6807\u9898" });
    const btnAiTag = create("button", { class: "pv-btn pv-ai-tag-btn", text: "AI \u6807\u7b7e" });
    const btnAiTitleTags = create("button", { class: "pv-btn pv-ai-tag-btn", text: "AI \u6807\u9898+\u6807\u7b7e" });
    const titleRow = create("div", { class: "pv-tags-row" }, [fieldTitle, btnAiTitle, btnAiTitleTags]);
    const tagsRow = create("div", { class: "pv-tags-row" }, [fieldTags, btnAiTag]);
    const aiButtons = [btnAiTitle, btnAiTag, btnAiTitleTags];
    let aiButtonsAvailable = false;

    function setAiButtonsState(enabled, reason = "") {
      aiButtonsAvailable = !!enabled;
      aiButtons.forEach((button) => {
        button.disabled = !enabled;
        if (reason) button.title = reason;
        else button.removeAttribute("title");
      });
    }

    async function refreshAiButtonsState() {
      setAiButtonsState(false, "正在检查 AI 配置");
      try {
        const config = await request("/llm/config");
        const hasBaseUrl = !!String(config.base_url || "").trim();
        const hasRules = Array.isArray(config.custom_system_prompts) && config.custom_system_prompts.length > 0;
        const isEnabled = !!config.enabled && hasBaseUrl && hasRules;
        if (isEnabled) {
          setAiButtonsState(true, "");
          return true;
        }
        let reason = "AI 生成功能未启用";
        if (!config.enabled) reason = "请先在规则管理器中启用 AI 生成功能";
        else if (!hasBaseUrl) reason = "请先配置有效的 LLM 地址";
        else if (!hasRules) reason = "请先配置可用的生成规则";
        setAiButtonsState(false, reason);
        return false;
      } catch (_error) {
        setAiButtonsState(false, "AI 配置检查失败");
        return false;
      }
    }

    async function ensurePromptForAI() {
      if (!aiButtonsAvailable) {
        toast("AI 生成功能未启用或配置无效", "info");
        return null;
      }
      const pos = fieldPos.value.trim();
      const neg = fieldNeg.value.trim();
      if (!pos && !neg) {
        toast("\u8bf7\u5148\u586b\u5199\u6b63\u5411\u6216\u8d1f\u5411\u63d0\u793a\u8bcd", "info");
        return null;
      }
      return { pos, neg };
    }

    async function withAiButton(button, idleText, task) {
      button.disabled = true;
      button.textContent = "\u751f\u6210\u4e2d\u2026";
      try {
        return await task();
      } catch (e) {
        toast(`${idleText} \u5931\u8d25: ${e}`, "error");
        return null;
      } finally {
        button.disabled = !aiButtonsAvailable;
        button.textContent = idleText;
      }
    }

    refreshAiButtonsState();

    btnAiTitle.addEventListener("click", async () => {
      const promptData = await ensurePromptForAI();
      if (!promptData) return;
      await withAiButton(btnAiTitle, "AI \u6807\u9898", async () => {
        const res = await request("/llm/auto_title", {
          method: "POST",
          body: JSON.stringify({
            positive: promptData.pos,
            negative: promptData.neg,
            existing_title: fieldTitle.value.trim(),
            existing_tags: parseCommaList(fieldTags.value),
          }),
        });
        if (res.error) {
          toast(res.error, "error");
          return;
        }
        if (!res.title) {
          toast("LLM \u672a\u8fd4\u56de\u6807\u9898", "info");
          return;
        }
        fieldTitle.value = res.title;
        toast("\u5df2\u751f\u6210\u6807\u9898", "success");
      });
    });

    btnAiTag.addEventListener("click", async () => {
      const promptData = await ensurePromptForAI();
      if (!promptData) return;
      await withAiButton(btnAiTag, "AI \u6807\u7b7e", async () => {
        const existing = parseCommaList(fieldTags.value);
        const res = await request("/llm/auto_tag", {
          method: "POST",
          body: JSON.stringify({ positive: promptData.pos, negative: promptData.neg, existing_tags: existing }),
        });
        if (res.error) {
          toast(res.error, "error");
          return;
        }
        const suggested = res.tags || [];
        if (!suggested.length) {
          toast("LLM \u672a\u8fd4\u56de\u6807\u7b7e", "info");
          return;
        }
        await ensureLLMModule();
        window.PromptVaultLLM.openTagPicker(suggested, existing, (selected) => {
          const merged = [...new Set([...existing, ...selected])];
          fieldTags.value = merged.join(",");
          toast(`\u5df2\u6dfb\u52a0 ${selected.length} \u4e2a\u6807\u7b7e`, "success");
        });
      });
    });

    btnAiTitleTags.addEventListener("click", async () => {
      const promptData = await ensurePromptForAI();
      if (!promptData) return;
      await withAiButton(btnAiTitleTags, "AI \u6807\u9898+\u6807\u7b7e", async () => {
        const existing = parseCommaList(fieldTags.value);
        const res = await request("/llm/auto_title_tags", {
          method: "POST",
          body: JSON.stringify({
            positive: promptData.pos,
            negative: promptData.neg,
            existing_title: fieldTitle.value.trim(),
            existing_tags: existing,
          }),
        });
        if (res.error) {
          toast(res.error, "error");
          return;
        }
        if (res.title) fieldTitle.value = res.title;
        const suggested = res.tags || [];
        if (!suggested.length) {
          toast(res.title ? "\u5df2\u751f\u6210\u6807\u9898" : "LLM \u672a\u8fd4\u56de\u6807\u7b7e", res.title ? "success" : "info");
          return;
        }
        await ensureLLMModule();
        window.PromptVaultLLM.openTagPicker(suggested, existing, (selected) => {
          const merged = [...new Set([...existing, ...selected])];
          fieldTags.value = merged.join(",");
          if (res.title) {
            toast(`\u5df2\u751f\u6210\u6807\u9898\u5e76\u6dfb\u52a0 ${selected.length} \u4e2a\u6807\u7b7e`, "success");
          } else {
            toast(`\u5df2\u6dfb\u52a0 ${selected.length} \u4e2a\u6807\u7b7e`, "success");
          }
        });
      });
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
          payload.version = entry.version;
          payload.updated_at = entry.updated_at;
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
      titleRow,
      tagsRow,
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
    applyResultViewMode();
    list.textContent = "加载中...";
    const params = new URLSearchParams();
    if (inputQuery.value.trim()) params.set("q", inputQuery.value.trim());
    if (inputTags.value.trim()) params.set("tags", inputTags.value.trim());
    if (inputModel.value.trim()) params.set("model", inputModel.value.trim());
    params.set("status", currentStatus);
    params.set("limit", String(pageLimit));
    params.set("offset", String(currentOffset));
    params.set("sort", currentSort);
    if (quickFilters.favorite_only) params.set("favorite_only", "true");
    if (quickFilters.has_thumbnail) params.set("has_thumbnail", "true");

    const result = await request(`/entries?${params.toString()}`);
    currentTotal = Math.max(0, Number(result.total || 0));
    if (currentTotal > 0 && currentOffset >= currentTotal) {
      currentOffset = Math.max(0, Math.floor((currentTotal - 1) / pageLimit) * pageLimit);
      return await reloadList();
    }

    list.textContent = "";
    const totalCount = result.items?.length || 0;
    updatePaginationUI(totalCount);
    if (!totalCount) {
      list.appendChild(create("div", { class: "pv-empty", text: "没有找到记录。" }));
      refreshQuickFilterUI();
      return;
    }

    const openQueryNode = (item) => {
      try {
        const graph = app.graph || app.canvas?.graph;
        if (!graph?.add) {
          toast("当前画布不可用，请先打开一个工作流", "error");
          return;
        }
        const createNode = (type) => {
          try { return globalThis.LiteGraph?.createNode?.(type) || null; }
          catch (_e) { return null; }
        };
        const node = createNode("PromptVaultQuery") || createNode("提示词库检索");
        if (!node) {
          toast("未找到节点类型：PromptVaultQuery", "error");
          return;
        }
        const canvas = app.canvas;
        const ds = canvas?.ds;
        const scale = ds?.scale || 1;
        const offset = ds?.offset || [0, 0];
        const canvasEl = canvas?.canvas;
        const viewW = canvasEl?.width || 1200;
        const viewH = canvasEl?.height || 800;
        node.pos = [Math.round(viewW * 0.5 / scale - offset[0]), Math.round(viewH * 0.5 / scale - offset[1])];
        node.widgets?.forEach((widget) => {
          if (widget.name === "query") widget.value = "";
          if (widget.name === "title") widget.value = "";
          if (widget.name === "tags") widget.value = "";
          if (widget.name === "model") widget.value = "";
          if (widget.name === "mode") widget.value = "locked";
          if (widget.name === "entry_id") widget.value = item.id || "";
        });
        if (item.title) node.title = `检索: ${item.title}`;
        graph.add(node);
        app.graph?.setDirtyCanvas?.(true, true);
        app.canvas?.setDirty?.(true, true);
        closeManager();
        toast("检索节点已添加到画布", "success");
      } catch (error) {
        toast(`创建节点失败: ${error}`, "error");
      }
    };

    const openEditorForItem = async (item) => {
      try {
        const full = await request(`/entries/${encodeURIComponent(item.id)}`);
        openEditor(full);
      } catch (error) {
        toast(`加载编辑数据失败: ${error}`, "error");
      }
    };

    const updateItemStatus = async (item) => {
      try {
        if (currentStatus === "deleted") {
          if (!confirm("确定还原记录？")) return;
          await request(`/entries/${encodeURIComponent(item.id)}`, {
            method: "PUT",
            body: JSON.stringify({ status: "active", updated_at: item.updated_at }),
          });
          toast("记录已还原", "success");
        } else {
          if (!confirm("确定删除？将移入回收站。")) return;
          await request(`/entries/${encodeURIComponent(item.id)}`, { method: "DELETE" });
          toast("已移入回收站", "success");
        }
        await reloadList();
      } catch (error) {
        toast(`更新状态失败: ${error}`, "error");
      }
    };

    const selectSummaryItem = async (item, element, activeClass) => {
      try {
        const full = await request(`/entries/${encodeURIComponent(item.id)}`);
        full.match_reasons = item.match_reasons || [];
        const assembled = await request("/assemble", {
          method: "POST",
          body: JSON.stringify({ entry_id: item.id, variables_override: {} }),
        });
        assembled.match_reasons = item.match_reasons || [];
        if (currentViewMode === "list") {
          selectedCardId = item.id;
          list.querySelectorAll(".pv-card-active, .pv-row-active").forEach((el) => el.classList.remove("pv-card-active", "pv-row-active"));
          element.classList.add(activeClass);
          renderDetail(full, assembled);
        } else {
          openDetailModal(full, assembled);
        }
      } catch (error) {
        toast(`加载详情失败: ${error}`, "error");
      }
    };

    for (const item of result.items) {
      const rowIndex = currentOffset + list.childElementCount + 1;
      const buttonCopy = create("button", { class: "pv-btn pv-small pv-icon-btn", text: "⧉", title: "复制正向提示词" });
      const buttonNode = create("button", { class: "pv-btn pv-small", text: "新建检索" });
      const buttonEdit = create("button", { class: "pv-btn pv-small", text: "编辑" });
      const buttonDelete = create("button", {
        class: `pv-btn pv-small ${currentStatus === "deleted" ? "" : "pv-danger"}`,
        text: currentStatus === "deleted" ? "还原" : "删除",
      });
      buttonCopy.addEventListener("click", async () => {
        try {
          const full = await request(`/entries/${encodeURIComponent(item.id)}`);
          await copyTextToClipboard(full?.raw?.positive || "");
          toast("已复制正向提示词", "success", 1500);
        } catch (error) {
          toast(`复制失败: ${error}`, "error");
        }
      });
      buttonNode.addEventListener("click", () => openQueryNode(item));
      buttonEdit.addEventListener("click", () => openEditorForItem(item));
      buttonDelete.addEventListener("click", () => updateItemStatus(item));

      if (currentViewMode === "list") {
        const row = create("div", { class: "pv-row", "data-entry-id": item.id });
      if (currentViewMode === "list" && item.id === selectedCardId) row.classList.add("pv-row-active");
        const thumb = create("img", {
          class: "pv-row-thumb",
          alt: "thumbnail",
          src: thumbUrl(item.id, item.updated_at),
        });
        thumb.onerror = () => { thumb.style.display = "none"; };
        const subText = [
          (item.tags || []).join(", "),
          (item.match_reasons || []).join(" / "),
          formatTimestamp(item.updated_at),
          `评分 ${Number(item.score || 0).toFixed(1)}`,
        ].filter(Boolean).join(" · ");
        const left = create("div", { class: "pv-row-left" }, [
          create("div", { class: "pv-row-index", text: String(rowIndex) }),
          thumb,
          create("div", { class: "pv-row-title", text: item.title || "(未命名)" }),
          create("div", { class: "pv-row-sub", text: subText }),
        ]);
        const right = create("div", { class: "pv-row-right" }, [buttonCopy, buttonNode, buttonEdit, buttonDelete]);
        row.appendChild(left);
        row.appendChild(right);
        row.addEventListener("click", async (event) => {
          if (event.target === buttonCopy || event.target === buttonNode || event.target === buttonEdit || event.target === buttonDelete) return;
          await selectSummaryItem(item, row, "pv-row-active");
        });
        list.appendChild(row);
        continue;
      }

      const card = create("div", { class: "pv-card", "data-entry-id": item.id });
      const thumb = create("img", {
        class: "pv-card-thumb",
        alt: "thumbnail",
        src: thumbUrl(item.id, item.updated_at),
      });
      thumb.onerror = () => {
        thumb.replaceWith(create("div", { class: "pv-card-thumb pv-card-thumb-empty", text: "暂无缩略图" }));
      };
      const tags = item.tags || [];
      const tagWrap = create("div", { class: "pv-card-tags" }, tags.map((tag) => create("span", { class: "pv-card-tag", text: tag })));
      const modelText = (item.model_scope || []).join(" / ") || "不限模型";
      const metaLine = create("div", { class: "pv-card-meta" }, [
        create("span", { class: "pv-card-index", text: `#${rowIndex}` }),
        create("span", { class: "pv-card-model", text: modelText.length > 15 ? `${modelText.slice(0, 15)}…` : modelText }),
      ]);
      const reasonLine = create("div", {
        class: "pv-card-reasons",
        text: "提示词",
      });
      const summaryLine = create("div", { class: "pv-card-summary", text: item.positive_preview || "暂无正向提示词摘要" });
      const bottomLine = create("div", { class: "pv-card-bottom" }, [
        create("span", { class: "pv-card-updated", text: formatTimestamp(item.updated_at) }),
        create("span", {
          class: `pv-card-score ${item.favorite ? "pv-card-favorite-on" : ""}`,
          text: `${item.favorite ? "★ " : ""}评分 ${Number(item.score || 0).toFixed(1)}`,
        }),
      ]);
      const titleRow = create("div", { class: "pv-card-title-row" }, [
        create("div", { class: "pv-card-title", text: item.title || "(未命名)" }),
        buttonCopy,
      ]);
      const cardActions = create("div", { class: "pv-card-actions" }, [buttonNode, buttonEdit, buttonDelete]);
      const cardBody = create("div", { class: "pv-card-body" }, [
        metaLine,
        titleRow,
        tagWrap,
        reasonLine,
        summaryLine,
        bottomLine,
      ]);
      card.appendChild(thumb);
      card.appendChild(cardBody);
      card.appendChild(cardActions);
      card.addEventListener("click", async (event) => {
        if (event.target === buttonCopy || event.target === buttonNode || event.target === buttonEdit || event.target === buttonDelete) return;
        await selectSummaryItem(item, card, "pv-card-active");
      });
      list.appendChild(card);
    }

    const preferredItem = currentViewMode === "list"
      ? (result.items.find((item) => item.id === selectedCardId) || result.items[0])
      : null;
    if (preferredItem?.id) {
      try {
        selectedCardId = preferredItem.id;
        const full = await request(`/entries/${encodeURIComponent(preferredItem.id)}`);
        full.match_reasons = preferredItem.match_reasons || [];
        const assembled = await request("/assemble", {
          method: "POST",
          body: JSON.stringify({ entry_id: preferredItem.id, variables_override: {} }),
        });
        assembled.match_reasons = preferredItem.match_reasons || [];
        renderDetail(full, assembled);
        const activeItem = list.querySelector(`[data-entry-id="${CSS.escape(preferredItem.id)}"]`);
        if (activeItem) activeItem.classList.add("pv-row-active");
      } catch (_e) {
        /* ignore */
      }
    } else if (currentViewMode !== "list") {
      statusBarRight.textContent = "";
    }
    refreshQuickFilterUI();
  }

  /* ── Keyboard: Enter to search, Escape to close ── */
  const triggerSearch = () => {
    resetPagination();
    reloadList().catch((e) => toast(String(e), "error"));
  };
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
  modal.appendChild(importInput);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  inputQuery.focus();
  refreshQuickFilterUI();

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
      if (node.comfyClass === "PromptVaultQuery") {
        setupPromptVaultQueryNode(node);
      }
      if (node.comfyClass === "ModelResolution") {
        setupModelResolutionNode(node);
      }
    },
  });
}
