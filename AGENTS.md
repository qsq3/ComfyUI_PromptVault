# AGENTS.md（ComfyUI 提示词库节点设计规范｜中文版）

用apply_patch修改文件

文档版本：v1.0  
更新日期：2026-02-27

## 1. 目标与原则

本规范用于指导「ComfyUI 提示词保存与检索节点」的设计与实现。

核心目标：
- 高复用：提示词可拆分、可组合、可继承。
- 标准化：统一数据结构与序列化协议，避免“纯文本散乱存储”。
- 可扩展：支持版本演进、模型差异、存储扩容、多端接入。
- 检索方便：支持关键词、标签、模型范围、全文检索与排序。

---

## 2. 总体架构

采用 ComfyUI 插件化结构：

1. 前端（Web UI）
- 在主菜单新增 `提示词库`。
- 点击后弹出类似 ComfyUI-Manager 的管理窗口（全中文）。
- 在弹窗中完成增删改查、筛选、预览、导入导出。

2. 后端（API 服务）
- 提供本地 REST API：`新增/查询/修改/删除/版本/拼装`。
- 负责数据校验、标准化、序列化、反序列化、重组输出。

3. 节点（ComfyUI Custom Node）
- 提供 `提示词库检索` 节点（推荐名称：`PromptVault Query`）。
- 节点执行时查询库并输出可直接用于采样链路的正负提示词。

---

## 3. 数据模型（标准化）

避免只存一整段字符串，建议三层模型：

1. 模板（Template）
- 定义结构与变量槽位（slot），如：`{subject}, {style}, {camera}, {lighting}`。

2. 片段（Fragment）
- 可复用词块，支持标签、建议权重、模型适配信息。
- 示例：`cinematic lighting`、`35mm lens`、`masterpiece`。

3. 实例（Entry）
- 一条可执行提示词记录，引用模板 + 片段 + 自由文本。
- 支持版本号与历史快照。

推荐字段：
- 基础：`id`, `title`, `template_id`, `status`, `version`, `created_at`, `updated_at`
- 内容：`variables`, `fragments`, `negative`, `raw_appendix`
- 索引：`tags`, `model_scope`, `lang`, `score`, `favorite`
- 追踪：`hash`, `source`, `editor`, `debug_trace`

---

## 4. 序列化与重组（PromptIR）

定义统一中间表示 `PromptIR`，用于存储与重组，避免 UI 与模型语法耦合。

示例结构：

```json
{
  "ir_version": "1.0",
  "segments": [
    {"type": "literal", "text": "young woman"},
    {"type": "sep", "text": ", "},
    {"type": "ref", "id": "frag_style_cinematic", "weight": 1.1},
    {"type": "slot", "name": "camera"}
  ],
  "negative_segments": [
    {"type": "ref", "id": "frag_neg_bad_hands"},
    {"type": "sep", "text": ", "},
    {"type": "literal", "text": "lowres"}
  ]
}
```

重组流程：
1. 读取 Entry 与 Template。
2. 展开 Fragment 引用。
3. 填充 slot 变量（可被运行时输入覆盖）。
4. 按目标模型规则应用权重格式。
5. 输出 `positive_prompt`、`negative_prompt`、`meta/debug_trace`。

---

## 5. CRUD 设计要求

1. Create（新增）
- 输入：标题、模板、变量、片段、负面词、标签、模型范围。
- 保存前标准化：空白清洗、标签归一、重复片段去重、生成 hash。
- 自动初始化 `version=1`。

2. Read（查询）
- 支持关键词、标签、模型、状态、时间范围。
- 支持全文检索（FTS）与排序（相关度/最近使用/评分）。
- 支持“收藏”“最近使用”“仅可用版本”过滤。

3. Update（修改）
- 使用 `version` 或 `updated_at` 做并发保护（乐观锁）。
- 每次修改写入 `entry_versions` 快照。
- 支持回滚历史版本。

4. Delete（删除）
- 默认软删除：`status=deleted`。
- 提供回收站恢复。
- 真删除需二次确认并受权限控制。

---

## 6. 存储方式与体量策略

默认推荐：SQLite + FTS（单机高性价比）。

建议表：
- `templates`
- `fragments`
- `entries`
- `entry_fragments`
- `tags`
- `entry_tags`
- `entry_versions`
- `entries_fts`（全文检索虚表）

规模策略：
- < 5 万条：SQLite + FTS 足够。
- 5 万 ~ 100 万条：优先 PostgreSQL。
- 语义召回需求：增加向量检索（如 pgvector），与关键词检索并行召回。

---

## 7. UI 规范（全中文）

1. 主菜单
- 新增菜单项：`提示词库`。
- 点击弹出：`提示词库管理器`（风格接近 ComfyUI-Manager）。

2. 窗口布局
- 顶部：搜索框、筛选器（标签/模型/状态）、新建按钮。
- 左侧：标签树、常用过滤。
- 中间：列表区（标题、标签、更新时间、命中高亮）。
- 右侧：详情区（结构化内容 + 最终拼装预览）。
- 底部：`新建` `编辑` `复制` `删除` `导入` `导出`。

3. 弹出子窗口
- 新建提示词：模板选择 + 变量编辑 + 片段选择。
- 编辑提示词：显示版本差异。
- 检索测试：实时查看命中与拼装结果。

---

## 8. 节点规范（查询节点）

节点名：`提示词库检索`（内部可为 `PromptVault Query`）

输入：
- `query`：关键词
- `tags`：标签（逗号分隔）
- `model`：模型范围（SDXL / Flux 等）
- `top_k`：返回数量
- `variables_json`：运行时变量覆盖

输出：
- `positive_prompt`
- `negative_prompt`
- `entry_id`
- `meta_json`（标题、标签、版本、trace）

执行逻辑：
1. 节点调用后端检索 API。
2. 根据评分策略选择最佳条目。
3. 应用 `variables_json` 覆盖后重组。
4. 输出拼装结果并可直接接入下游节点。

---

## 9. 可扩展性预留

- 多语言字段：如 `title_zh`, `title_en`。
- 模型语法策略：不同模型采用不同权重格式化规则。
- 权限与协作：从本地单用户扩展到团队共享库。
- 导入导出：JSONL/CSV/文本互转。
- 插件扩展点：自动打标签、质量评分、推荐器。

---

## 10. 实施优先级

1. V1（最小可用）
- SQLite + FTS
- 模板/片段/实例三层模型
- 中文管理器弹窗
- 查询节点可输出正负提示词

2. V2（增强）
- 版本管理、回收站、收藏与评分
- 导入导出

3. V3（进阶）
- 语义检索
- 远程库/多用户协作

---

## 11. 质量要求

- 接口与字段命名保持一致，禁止同义多命名。
- 所有写接口必须记录 `updated_at` 与版本快照。
- 所有查询接口必须支持分页与稳定排序。
- 节点输出必须可复现（同输入同结果）。
- UI 文案与错误提示全中文。

以上规范作为本项目后续开发的统一基线。

## 12. 大模型辅助功能（PromptAI Assist）

为提升提示词创建效率，系统支持接入大语言模型自动生成「标题」与「标签」，辅助用户快速命名与分类。

### 1. 大模型接入设置

支持多种大模型服务来源：

- **OpenAI**：通过官方 API 接口调用 GPT-4/3.5。
- **Azure OpenAI**：配置自定义端点与 API Key。
- **LM Studio 本地部署**（推荐）：
  - 通过本地 HTTP 服务调用，如 `http://localhost:1234/v1/chat/completions`。
  - 支持 GGUF 格式模型（如 Mistral, LLaMA, Zephyr 等）。
  - 无需联网、响应快、隐私安全。
  - 建议使用 Chat 模式模型，保持 API 接口兼容 OpenAI 格式。

#### 配置示例（llm_config.json）：

```json
{
  "provider": "lmstudio",
  "endpoint": "http://localhost:1234/v1/chat/completions",
  "model": "mistral-7b-instruct",
  "temperature": 0.7,
  "max_tokens": 512,
  "timeout": 10
}
