(function () {
  "use strict";

  var create, request, toast;

  var TASK_OPTIONS = [
    { value: "tags", label: "标签生成" },
    { value: "title", label: "标题生成" },
    { value: "title_tags", label: "标题+标签" },
  ];

  var TASK_LABELS = TASK_OPTIONS.reduce(function (acc, item) {
    acc[item.value] = item.label;
    return acc;
  }, {});

  function init(deps) {
    create = deps.create;
    request = deps.request;
    toast = deps.toast;
  }

  function openTagPicker(suggested, existing, onConfirm) {
    const overlayPicker = create("div", { class: "pv-overlay" });
    const panel = create("div", { class: "pv-modal pv-tag-picker" });
    panel.appendChild(create("div", { class: "pv-title", text: "AI 推荐标签" }));

    const body = create("div", { class: "pv-tag-picker-body" });
    const checkboxes = [];
    const existingSet = new Set(existing.map(function (tag) { return tag.toLowerCase(); }));
    let defaultCheckedCount = 0;

    suggested.forEach(function (tag) {
      const already = existingSet.has(tag.toLowerCase());
      const id = "pv-tag-" + Math.random().toString(36).slice(2, 8);
      const cb = create("input", { type: "checkbox", id: id });
      if (!already && defaultCheckedCount < 5) {
        cb.checked = true;
        defaultCheckedCount += 1;
      }
      if (already) cb.disabled = true;
      const label = create("label", { for: id, text: already ? tag + " (已存在)" : tag });
      if (already) label.classList.add("pv-tag-existing");
      body.appendChild(create("div", { class: "pv-tag-picker-item" }, [cb, label]));
      checkboxes.push({ cb: cb, tag: tag, already: already });
    });

    const btnSelectAll = create("button", { class: "pv-btn pv-small", text: "全选" });
    const btnDeselectAll = create("button", { class: "pv-btn pv-small", text: "取消全选" });
    const btnConfirm = create("button", { class: "pv-btn pv-primary", text: "确认添加" });
    const btnCancel = create("button", { class: "pv-btn", text: "取消" });

    btnSelectAll.addEventListener("click", function () {
      checkboxes.forEach(function (item) { if (!item.already) item.cb.checked = true; });
    });
    btnDeselectAll.addEventListener("click", function () {
      checkboxes.forEach(function (item) { if (!item.already) item.cb.checked = false; });
    });

    function close() {
      if (document.body.contains(overlayPicker)) document.body.removeChild(overlayPicker);
    }

    btnCancel.addEventListener("click", close);
    btnConfirm.addEventListener("click", function () {
      const selected = checkboxes
        .filter(function (item) { return item.cb.checked && !item.already; })
        .map(function (item) { return item.tag; });
      onConfirm(selected);
      close();
    });

    panel.appendChild(body);
    panel.appendChild(create("div", { class: "pv-editor-actions" }, [btnSelectAll, btnDeselectAll, btnConfirm, btnCancel]));
    overlayPicker.appendChild(panel);
    overlayPicker.addEventListener("click", function (e) { if (e.target === overlayPicker) close(); });
    overlayPicker.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
    document.body.appendChild(overlayPicker);
  }

  function normalizeRules(config) {
    var rules = Array.isArray(config.custom_system_prompts) ? config.custom_system_prompts.slice() : [];
    return rules.map(function (rule, index) {
      return {
        id: rule.id || ("rule_" + index),
        task: rule.task || "tags",
        name: rule.name || "未命名规则",
        prompt: rule.prompt || "",
      };
    });
  }

  function openLLMSettings() {
    const overlaySettings = create("div", { class: "pv-overlay" });
    const panel = create("div", { class: "pv-modal pv-llm-settings" });
    const btnClose = create("button", {
      class: "pv-btn pv-small pv-llm-title-close",
      type: "button",
      "aria-label": "关闭",
    });
    btnClose.textContent = "×";
    panel.appendChild(create("div", { class: "pv-title" }, [
      create("span", { text: "规则管理器" }),
      btnClose,
    ]));

    const body = create("div", { class: "pv-editor-body" });
    body.textContent = "加载中…";

    function close() {
      if (document.body.contains(overlaySettings)) document.body.removeChild(overlaySettings);
    }

    btnClose.addEventListener("click", close);

    function loadAndRender() {
      request("/llm/config").then(function (config) {
        body.textContent = "";

        const fieldEnabled = create("input", { type: "checkbox" });
        fieldEnabled.checked = !!config.enabled;
        const enableRow = create("label", { class: "pv-llm-switch" }, [
          fieldEnabled,
          create("span", { text: " 启用 AI 生成功能" }),
        ]);

        const fieldBaseUrl = create("input", {
          class: "pv-input",
          placeholder: "LM Studio 地址，如 http://localhost:1234",
          value: config.base_url || "http://localhost:1234",
        });
        const fieldModel = create("input", {
          class: "pv-input",
          placeholder: "模型名称（可留空，使用默认）",
          value: config.model || "",
        });
        const fieldApiKey = create("input", {
          class: "pv-input",
          placeholder: "API Key（可选）",
          type: "password",
          value: "",
        });
        if (config.api_key) {
          fieldApiKey.setAttribute("placeholder", "API Key（已配置）");
        }
        const fieldTimeout = create("input", {
          class: "pv-input pv-input-short",
          placeholder: "超时（秒）",
          type: "number",
          value: String(config.timeout || 30),
        });

        var rules = normalizeRules(config);
        var activePromptIds = Object.assign({}, config.active_prompt_ids || {});
        var currentRuleId = rules[0] ? rules[0].id : "";

        const sectionTitle = create("h3", { class: "pv-llm-rules-section-title", text: "生成规则" });
        const btnAddRule = create("button", { class: "pv-btn pv-primary pv-llm-add-rule" }, [
          create("span", { class: "pv-llm-add-icon", text: "+" }),
          create("span", { text: " 添加规则" }),
        ]);
        const rulesHeadRow = create("div", { class: "pv-llm-rules-head-row" }, [sectionTitle, btnAddRule]);

        const tableWrap = create("div", { class: "pv-llm-rules-table-wrap" });
        const table = create("table", { class: "pv-llm-rules-table" });
        const thead = create("thead", {}, [
          create("tr", {}, [
            create("th", { class: "pv-llm-th-status", text: "启用" }),
            create("th", { class: "pv-llm-th-type", text: "类型" }),
            create("th", { class: "pv-llm-th-name", text: "规则名称" }),
            create("th", { class: "pv-llm-th-content", text: "规则内容" }),
            create("th", { class: "pv-llm-th-actions", text: "操作" }),
          ]),
        ]);
        const tbody = create("tbody");
        table.appendChild(thead);
        table.appendChild(tbody);
        tableWrap.appendChild(table);

        const editorTitle = create("div", { class: "pv-detail-title", text: "编辑选中规则" });
        const fieldRuleTask = create("select", { class: "pv-input pv-llm-task-select" }, TASK_OPTIONS.map(function (item) {
          return create("option", { value: item.value, text: item.label });
        }));
        const fieldPromptName = create("input", { class: "pv-input", placeholder: "规则名称" });
        const fieldSystemPrompt = create("textarea", {
          class: "pv-textarea pv-llm-prompt-textarea",
          placeholder: "规则内容（System Prompt）",
        });
        fieldSystemPrompt.style.height = "120px";
        const btnSaveRule = create("button", { class: "pv-btn pv-primary", text: "保存当前规则" });

        function truncate(str, maxLen) {
          if (!str || typeof str !== "string") return "";
          return str.length <= maxLen ? str : str.slice(0, maxLen) + "…";
        }

        function getRule(ruleId) {
          return rules.find(function (rule) { return rule.id === ruleId; });
        }

        function fillEditor(rule) {
          if (!rule) {
            fieldRuleTask.value = "tags";
            fieldPromptName.value = "";
            fieldSystemPrompt.value = "";
            return;
          }
          currentRuleId = rule.id;
          fieldRuleTask.value = rule.task || "tags";
          fieldPromptName.value = rule.name || "";
          fieldSystemPrompt.value = rule.prompt || "";
        }

        function renderTableRows() {
          tbody.textContent = "";
          rules.forEach(function (rule) {
            const task = rule.task || "tags";
            const isActive = activePromptIds[task] === rule.id;
            const tr = create("tr", { class: "pv-llm-rule-row" });

            const radio = create("input", {
              type: "radio",
              name: "pv_llm_rule_radio_" + task,
              value: rule.id,
              class: "pv-llm-radio-input",
            });
            radio.checked = isActive;
            const radioVisual = create("span", { class: "pv-llm-radio-visual" });
            if (isActive) radioVisual.classList.add("pv-llm-radio-checked");
            const statusLabel = create("label", { class: "pv-llm-status-label" }, [radio, radioVisual]);
            radio.addEventListener("change", function () {
              activePromptIds[task] = rule.id;
              renderTableRows();
            });

            const btnEdit = create("button", { class: "pv-llm-icon-btn", type: "button", "aria-label": "编辑" });
            btnEdit.innerHTML = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7\"/><path d=\"M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z\"/></svg>";
            btnEdit.addEventListener("click", function () {
              fillEditor(rule);
              renderTableRows();
            });

            const btnDel = create("button", { class: "pv-llm-icon-btn", type: "button", "aria-label": "删除" });
            btnDel.innerHTML = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><polyline points=\"3 6 5 6 21 6\"/><path d=\"M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2\"/><line x1=\"10\" y1=\"11\" x2=\"10\" y2=\"17\"/><line x1=\"14\" y1=\"11\" x2=\"14\" y2=\"17\"/></svg>";
            btnDel.addEventListener("click", function () {
              const sameTaskRules = rules.filter(function (item) { return item.task === task; });
              if (sameTaskRules.length <= 1) {
                toast("每种类型至少保留一条规则", "info");
                return;
              }
              if (!confirm("确定删除此规则？")) return;
              rules = rules.filter(function (item) { return item.id !== rule.id; });
              if (activePromptIds[task] === rule.id) {
                const nextRule = rules.find(function (item) { return item.task === task; });
                activePromptIds[task] = nextRule ? nextRule.id : "";
              }
              const current = getRule(currentRuleId) || rules[0] || null;
              fillEditor(current);
              renderTableRows();
              toast("规则已删除", "success");
            });

            if (rule.id === currentRuleId) tr.classList.add("pv-llm-rule-row-active");
            tr.appendChild(create("td", { class: "pv-llm-td-status" }, [statusLabel]));
            tr.appendChild(create("td", { class: "pv-llm-td-type" }, [
              create("span", { class: "pv-llm-type-badge", text: TASK_LABELS[task] || task }),
            ]));
            tr.appendChild(create("td", { class: "pv-llm-td-name", text: rule.name || "未命名" }));
            tr.appendChild(create("td", {
              class: "pv-llm-td-content",
              title: rule.prompt || "",
              text: truncate(rule.prompt || "", 64),
            }));
            tr.appendChild(create("td", { class: "pv-llm-td-actions" }, [btnEdit, btnDel]));
            tr.addEventListener("click", function (event) {
              if (event.target.closest("button") || event.target.closest("label")) return;
              fillEditor(rule);
              renderTableRows();
            });
            tbody.appendChild(tr);
          });
        }

        btnAddRule.addEventListener("click", function () {
          const task = fieldRuleTask.value || "tags";
          const newRule = {
            id: "custom_" + Date.now(),
            task: task,
            name: "新规则",
            prompt: "",
          };
          rules.push(newRule);
          if (!activePromptIds[task]) activePromptIds[task] = newRule.id;
          fillEditor(newRule);
          renderTableRows();
          toast("已添加新规则", "success");
        });

        btnSaveRule.addEventListener("click", function () {
          var rule = getRule(currentRuleId);
          if (!rule) {
            toast("请先选择或添加一条规则", "info");
            return;
          }
          const prevTask = rule.task || "tags";
          const nextTask = fieldRuleTask.value || "tags";
          rule.task = nextTask;
          rule.name = fieldPromptName.value.trim() || rule.name;
          rule.prompt = fieldSystemPrompt.value.trim();
          if (activePromptIds[prevTask] === rule.id && prevTask !== nextTask) {
            const prevFallback = rules.find(function (item) { return item.task === prevTask && item.id !== rule.id; });
            activePromptIds[prevTask] = prevFallback ? prevFallback.id : "";
          }
          if (!activePromptIds[nextTask]) activePromptIds[nextTask] = rule.id;
          renderTableRows();
          toast("当前规则已保存", "success");
        });

        fillEditor(getRule(currentRuleId) || rules[0] || null);
        renderTableRows();

        const btnTest = create("button", { class: "pv-btn", text: "测试连接" });
        const btnSave = create("button", { class: "pv-btn pv-primary pv-llm-footer-save" }, [
          document.createTextNode("✓ "),
          document.createTextNode("保存"),
        ]);
        const btnCancel = create("button", { class: "pv-btn pv-llm-footer-cancel" }, [
          document.createTextNode("× "),
          document.createTextNode("取消"),
        ]);
        const testResult = create("span", { class: "pv-llm-test-result", text: "" });

        btnTest.addEventListener("click", function () {
          btnTest.disabled = true;
          btnTest.textContent = "测试中…";
          testResult.textContent = "";
          const testConfig = {
            base_url: fieldBaseUrl.value.trim() || "http://localhost:1234",
            model: fieldModel.value.trim(),
            timeout: parseInt(fieldTimeout.value, 10) || 30,
          };
          const newKey = fieldApiKey.value.trim();
          if (newKey) testConfig.api_key = newKey;

          request("/llm/test", { method: "POST", body: JSON.stringify(testConfig) })
            .then(function (res) {
              if (res.ok) {
                fieldEnabled.checked = true;
                testResult.textContent = "✓ 连接成功，模型: " + (res.model || "unknown");
                testResult.style.color = "#2ecc71";
              } else {
                testResult.textContent = "✗ " + (res.error || "连接失败");
                testResult.style.color = "#e74c3c";
              }
            })
            .catch(function (e) {
              testResult.textContent = "✗ " + e;
              testResult.style.color = "#e74c3c";
            })
            .finally(function () {
              btnTest.disabled = false;
              btnTest.textContent = "测试连接";
            });
        });

        btnSave.addEventListener("click", function () {
          const update = {
            enabled: fieldEnabled.checked,
            base_url: fieldBaseUrl.value.trim() || "http://localhost:1234",
            model: fieldModel.value.trim(),
            timeout: parseInt(fieldTimeout.value, 10) || 30,
            custom_system_prompts: rules,
            active_prompt_ids: activePromptIds,
          };
          const newKey = fieldApiKey.value.trim();
          if (newKey) update.api_key = newKey;

          request("/llm/config", { method: "PUT", body: JSON.stringify(update) })
            .then(function () {
              toast("LLM 设置已保存", "success");
              close();
            })
            .catch(function (e) {
              toast("保存失败: " + e, "error");
            });
        });

        btnCancel.addEventListener("click", close);

        body.appendChild(enableRow);
        body.appendChild(create("div", { class: "pv-detail-title", text: "LM Studio 地址" }));
        body.appendChild(fieldBaseUrl);
        body.appendChild(create("div", { class: "pv-detail-title", text: "模型名称" }));
        body.appendChild(fieldModel);
        body.appendChild(create("div", { class: "pv-detail-title", text: "API Key" }));
        body.appendChild(fieldApiKey);
        body.appendChild(create("div", { class: "pv-detail-title", text: "超时时间（秒）" }));
        body.appendChild(fieldTimeout);

        var rulesSection = create("div", { class: "pv-llm-rules-section" });
        rulesSection.appendChild(rulesHeadRow);
        rulesSection.appendChild(tableWrap);
        var editorCard = create("div", { class: "pv-llm-editor-card" });
        editorCard.appendChild(editorTitle);
        editorCard.appendChild(create("div", { class: "pv-detail-title", text: "规则类型" }));
        editorCard.appendChild(fieldRuleTask);
        editorCard.appendChild(create("div", { class: "pv-detail-title", text: "规则名称" }));
        editorCard.appendChild(fieldPromptName);
        editorCard.appendChild(create("div", { class: "pv-detail-title", text: "规则内容" }));
        editorCard.appendChild(fieldSystemPrompt);
        editorCard.appendChild(create("div", { class: "pv-editor-actions" }, [btnSaveRule]));
        rulesSection.appendChild(editorCard);
        body.appendChild(rulesSection);

        body.appendChild(create("div", { class: "pv-llm-test-row" }, [btnTest, testResult]));
        body.appendChild(create("div", { class: "pv-editor-actions pv-llm-footer-actions" }, [btnSave, btnCancel]));
      }).catch(function (e) {
        body.textContent = "加载失败: " + e;
      });
    }

    panel.appendChild(body);
    overlaySettings.appendChild(panel);
    overlaySettings.addEventListener("click", function (e) { if (e.target === overlaySettings) close(); });
    overlaySettings.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
    document.body.appendChild(overlaySettings);
    loadAndRender();
  }

  window.PromptVaultLLM = {
    init: init,
    openTagPicker: openTagPicker,
    openLLMSettings: openLLMSettings,
  };
})();
