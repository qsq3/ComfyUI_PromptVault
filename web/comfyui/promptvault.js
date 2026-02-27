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

function openManager() {
  ensureStyle();

  const overlay = create("div", { class: "pv-overlay" });
  const modal = create("div", {
    class: "pv-modal",
    role: "dialog",
    "aria-label": "\u63d0\u793a\u8bcd\u5e93\u7ba1\u7406\u5668",
  });
  const title = create("div", { class: "pv-title", text: "\u63d0\u793a\u8bcd\u5e93\u7ba1\u7406\u5668" });

  const inputQuery = create("input", { class: "pv-input", placeholder: "\u5173\u952e\u8bcd\uff08\u6807\u9898/\u5185\u5bb9/\u6807\u7b7e\uff09" });
  const inputTags = create("input", { class: "pv-input", placeholder: "\u6807\u7b7e\uff08\u9017\u53f7\u5206\u9694\uff0c\u53ef\u9009\uff09" });
  const inputModel = create("input", { class: "pv-input", placeholder: "\u6a21\u578b\uff08\u5982 SDXL / Flux\uff0c\u53ef\u9009\uff09" });
  const buttonSearch = create("button", { class: "pv-btn pv-primary", text: "\u68c0\u7d22" });
  const buttonNew = create("button", { class: "pv-btn", text: "\u65b0\u5efa" });
  const buttonClose = create("button", { class: "pv-btn pv-danger", text: "\u5173\u95ed" });
  const toolbar = create("div", { class: "pv-toolbar" }, [inputQuery, inputTags, inputModel, buttonSearch, buttonNew, buttonClose]);

  const list = create("div", { class: "pv-list" });
  let currentPositive = "";
  const buttonCopyPositive = create("button", { class: "pv-btn pv-small", text: "\u590d\u5236\u6b63\u5411\u63d0\u793a\u8bcd" });
  buttonCopyPositive.addEventListener("click", async () => {
    if (!currentPositive.trim()) {
      alert("\u8bf7\u5148\u9009\u62e9\u4e00\u6761\u8bb0\u5f55");
      return;
    }
    try {
      await copyTextToClipboard(currentPositive);
      alert("\u5df2\u590d\u5236\u6b63\u5411\u63d0\u793a\u8bcd");
    } catch (error) {
      alert(`\u590d\u5236\u5931\u8d25: ${error}`);
    }
  });
  const pre = create("pre", { class: "pv-pre", text: "\u9009\u62e9\u8bb0\u5f55\u67e5\u770b\u9884\u89c8\u3002" });
  const detailHeader = create("div", { class: "pv-detail-header" }, [
    create("div", { class: "pv-detail-title", text: "\u8be6\u60c5 / \u9884\u89c8" }),
    buttonCopyPositive,
  ]);
  const detail = create("div", { class: "pv-detail" }, [detailHeader, pre]);
  const body = create("div", { class: "pv-body" }, [list, detail]);

  function renderDetail(entry, assembled) {
    currentPositive = assembled.positive || "";
    pre.textContent =
      `\u6807\u9898: ${entry.title || ""}\n` +
      `ID: ${entry.id}\n` +
      `\u6807\u7b7e: ${(entry.tags || []).join(", ")}\n` +
      `\u6a21\u578b: ${(entry.model_scope || []).join(", ")}\n` +
      `\u7248\u672c: ${entry.version || 1}\n\n` +
      `\u6b63\u5411:\n${assembled.positive || ""}\n\n` +
      `\u8d1f\u5411:\n${assembled.negative || ""}\n`;
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

    const buttonSave = create("button", { class: "pv-btn pv-primary", text: "\u4fdd\u5b58" });
    const buttonCancel = create("button", {
      class: "pv-btn pv-danger",
      text: "\u53d6\u6d88",
      onclick: () => document.body.removeChild(overlayEditor),
    });

    buttonSave.addEventListener("click", async () => {
      let variables = {};
      try {
        variables = fieldVars.value.trim() ? JSON.parse(fieldVars.value) : {};
        if (!variables || typeof variables !== "object" || Array.isArray(variables)) {
          throw new Error("variables must be object");
        }
      } catch (error) {
        alert(`JSON parse error: ${error}`);
        return;
      }

      const payload = {
        title: fieldTitle.value.trim(),
        tags: parseCommaList(fieldTags.value),
        model_scope: parseCommaList(fieldModel.value),
        raw: { positive: fieldPos.value, negative: fieldNeg.value },
        variables,
      };

      if (isNew) {
        await request("/entries", { method: "POST", body: JSON.stringify(payload) });
      } else {
        await request(`/entries/${encodeURIComponent(entry.id)}`, { method: "PUT", body: JSON.stringify(payload) });
      }
      document.body.removeChild(overlayEditor);
      await reloadList();
    });

    const content = create("div", { class: "pv-editor-body" }, [
      fieldTitle,
      fieldTags,
      fieldModel,
      create("div", { class: "pv-split" }, [fieldPos, fieldNeg]),
      create("div", { class: "pv-detail-title", text: "\u53d8\u91cf\uff08\u53ef\u88ab nodes.variables_json \u8986\u76d6\uff09" }),
      fieldVars,
      create("div", { class: "pv-editor-actions" }, [buttonSave, buttonCancel]),
    ]);
    editor.appendChild(create("div", { class: "pv-title", text: isNew ? "\u65b0\u5efa\u63d0\u793a\u8bcd" : "\u7f16\u8f91\u63d0\u793a\u8bcd" }));
    editor.appendChild(content);
    overlayEditor.appendChild(editor);
    overlayEditor.addEventListener("click", (event) => {
      if (event.target === overlayEditor) document.body.removeChild(overlayEditor);
    });
    document.body.appendChild(overlayEditor);
  }

  async function reloadList() {
    list.textContent = "\u52a0\u8f7d\u4e2d...";
    const params = new URLSearchParams();
    if (inputQuery.value.trim()) params.set("q", inputQuery.value.trim());
    if (inputTags.value.trim()) params.set("tags", inputTags.value.trim());
    if (inputModel.value.trim()) params.set("model", inputModel.value.trim());
    params.set("status", "active");
    params.set("limit", "50");

    const result = await request(`/entries?${params.toString()}`);
    list.textContent = "";
    if (!result.items?.length) {
      list.appendChild(create("div", { class: "pv-empty", text: "\u6ca1\u6709\u627e\u5230\u8bb0\u5f55\u3002" }));
      return;
    }

    for (const item of result.items) {
      const row = create("div", { class: "pv-row" });
      const left = create("div", { class: "pv-row-left" }, [
        create("div", { class: "pv-row-title", text: item.title || "(untitled)" }),
        create("div", { class: "pv-row-sub", text: `标签: ${(item.tags || []).join(", ")} | ${item.updated_at || ""}` }),
      ]);
      const buttonNode = create("button", { class: "pv-btn pv-small", text: "\u65b0\u5efa\u68c0\u7d22\u8282\u70b9" });
      const buttonEdit = create("button", { class: "pv-btn pv-small", text: "\u7f16\u8f91" });
      const buttonDelete = create("button", { class: "pv-btn pv-small pv-danger", text: "\u5220\u9664" });
      const right = create("div", { class: "pv-row-right" }, [buttonNode, buttonEdit, buttonDelete]);

      buttonNode.addEventListener("click", () => {
        try {
          const graph = app.graph || app.canvas?.graph;
          if (!graph?.add) {
            alert("当前画布不可用，请先打开一个工作流");
            return;
          }

          const create = (type) => {
            try {
              return globalThis.LiteGraph?.createNode?.(type) || null;
            } catch (_e) {
              return null;
            }
          };
          const node = create("PromptVaultQuery") || create("提示词库检索");
          if (!node) {
            alert("未找到节点类型：PromptVaultQuery");
            return;
          }

          node.pos = [240, 120];
          node.widgets?.forEach((widget) => {
            if (widget.name === "query") widget.value = "";
            if (widget.name === "tags") widget.value = (item.tags || []).join(",");
            if (widget.name === "model") widget.value = (item.model_scope || []).join(",");
            if (widget.name === "top_k") widget.value = 1;
            if (widget.name === "variables_json") widget.value = "{}";
          });
          graph.add(node);
          app.graph?.setDirtyCanvas?.(true, true);
          app.canvas?.setDirty?.(true, true);

          // Close manager after creation so users can immediately see the new node on canvas.
          document.body.removeChild(overlay);
        } catch (error) {
          alert(`创建节点失败: ${error}`);
        }
      });

      buttonEdit.addEventListener("click", async () => {
        try {
          const full = await request(`/entries/${encodeURIComponent(item.id)}`);
          openEditor(full);
        } catch (error) {
          alert(`加载编辑数据失败: ${error}`);
        }
      });
      buttonDelete.addEventListener("click", async () => {
        if (!confirm("\u786e\u5b9a\u5220\u9664\uff1f")) return;
        await request(`/entries/${encodeURIComponent(item.id)}`, { method: "DELETE" });
        await reloadList();
      });

      row.addEventListener("click", async (event) => {
        if (event.target === buttonNode || event.target === buttonEdit || event.target === buttonDelete) return;
        const full = await request(`/entries/${encodeURIComponent(item.id)}`);
        const assembled = await request("/assemble", {
          method: "POST",
          body: JSON.stringify({ entry_id: item.id, variables_override: {} }),
        });
        renderDetail(full, assembled);
      });

      row.appendChild(left);
      row.appendChild(right);
      list.appendChild(row);
    }
  }

  buttonSearch.addEventListener("click", () => reloadList().catch((e) => alert(String(e))));
  buttonNew.addEventListener("click", () => openEditor(null));
  buttonClose.addEventListener("click", () => document.body.removeChild(overlay));
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) document.body.removeChild(overlay);
  });

  modal.appendChild(title);
  modal.appendChild(toolbar);
  modal.appendChild(body);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  reloadList().catch((e) => {
    list.textContent = "";
    list.appendChild(create("div", { class: "pv-empty", text: `Error: ${e}` }));
  });
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
  });
}
