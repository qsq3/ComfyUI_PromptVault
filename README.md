# ComfyUI_PromptVault（提示词库）

声明：本仓库所有代码均由 Codex 编写，自用。

用于 ComfyUI 的提示词保存、检索、管理与复用插件，包含管理器窗口、检索节点、保存节点，以及基于 LLM 的标题/标签生成功能。

## 功能

- 提示词记录增删改查，支持软删除与回收站
- SQLite + FTS 全文检索
- 标签管理、标签整理、标签侧栏筛选
- 提示词库管理器中文界面
- `提示词库检索` / `提示词库保存` 两个节点
- 自动提取 PNG / workflow / 源图元数据
- LLM 标题生成、标签生成、标题+标签同时生成
- LLM 规则管理器，支持按用途分别配置规则
- 管理器记录列表分页

## 安装

- 放入 `ComfyUI/custom_nodes/ComfyUI_PromptVault`
- 重启 ComfyUI

## 节点

### 提示词库检索（PromptVault Query）

从提示词库中检索记录，输出可直接接入 `CLIPTextEncode` 等节点的正负提示词。

| 输入 | 类型 | 说明 |
|------|------|------|
| `query` | STRING | 关键词，按标题/内容/标签检索 |
| `title` | STRING | 标题过滤，留空忽略 |
| `tags` | STRING | 标签过滤，逗号分隔 |
| `model` | STRING | 模型过滤，如 `SDXL`、`Flux` |
| `top_k` | INT | 候选数量，默认 1 |
| `variables_json` | STRING | 变量覆盖 JSON |

| 输出 | 类型 | 说明 |
|------|------|------|
| `positive_prompt` | STRING | 拼装后的正向提示词 |
| `negative_prompt` | STRING | 拼装后的负向提示词 |

检索策略：

- 先按关键词 + 标签 + 模型严格检索
- 无结果时逐步放宽条件
- 最终可回退到最近更新记录，尽量保证有输出

### 提示词库保存（PromptVault Save）

在工作流执行时自动提取生成参数并保存到提示词库，同时生成缩略图。

| 输入 | 类型 | 说明 |
|------|------|------|
| `image` | IMAGE | 生成图像，必填 |
| `title` | STRING | 记录标题 |
| `tags` | STRING | 标签，逗号分隔 |
| `model` | STRING | 模型名，留空时尝试自动提取 |
| `positive_prompt` | STRING | 可选正向提示词，有输入时优先保存，否则从图片元数据提取 |
| `negative_prompt` | STRING | 可选反向提示词，有输入时优先保存，否则从图片元数据提取 |
| `llm_generate` | BOOLEAN | 是否启用 LLM 自动补全，默认关闭 |
| `llm_generate_mode` | ENUM | `auto` / `title_only` / `tags_only` / `title_and_tags`，默认 `title_and_tags` |

| 输出 | 类型 | 说明 |
|------|------|------|
| `entry_id` | STRING | 保存成功后的记录 ID |
| `status` | STRING | 保存结果 |

自动提取内容：

- 正向提示词（未提供 `positive_prompt` 时）
- 负向提示词（未提供 `negative_prompt` 时）
- `steps`
- `cfg`
- `sampler`
- `scheduler`
- `seed`
- `model_name`
- 缩略图

自动生成说明：

- `llm_generate=false` 时不调用 LLM
- `llm_generate=true` 时按 `llm_generate_mode` 调用已配置规则
- LLM 生成的标签最多保留前 5 个
- 如果 LLM 未启用、配置无效或生成失败，会回退到本地默认逻辑，不阻止保存

## 管理器窗口

在 ComfyUI 主菜单中打开“提示词库”管理器，可进行：

- 关键词 / 标签 / 模型筛选
- 新建、编辑、删除记录
- 回收站查看、恢复、清空
- 左侧标签栏浏览
- 整理标签
- 查看详情与拼装预览
- 复制正向提示词
- 一键创建检索节点

分页：

- 记录列表支持真正分页
- 当前默认每页 10 条，便于测试
- 工具栏中提供页码、上一页、下一页

记录列表：

- 每条记录前带编号
- 编号从 1 开始，跨页连续递增

## LLM 功能

### 编辑提示词窗口

当 AI 生成功能已启用且配置有效时，编辑窗口中的 AI 按钮可用：

- `AI 标题`
- `AI 标签`
- `AI 标题+标签`

如果 AI 未启用或配置无效，按钮会禁用。

### 规则管理器

规则管理器支持 3 类规则：

- 标签生成
- 标题生成
- 标题+标签

每类规则都可以：

- 新增规则
- 编辑规则
- 删除规则
- 单独指定当前启用规则

规则默认保存在数据库 `meta` 表中的 `llm_config` 项内，不是单独表。

### AI 推荐标签弹窗

- 已存在标签会禁用
- 默认只勾选前 5 个未存在标签

## 标签整理

“整理标签”会做两件事：

- 删除没有任何有效记录引用的标签
- 补回当前有效记录中存在、但 `tags` 表缺失的标签

注意：

- 这里的“有效记录”指 `status != deleted`
- 回收站中的记录标签不会参与补回

## 后端 API

- `GET /promptvault/health`
- `GET /promptvault/entries`
- `POST /promptvault/entries`
- `PUT /promptvault/entries/{id}`
- `DELETE /promptvault/entries/{id}`
- `GET /promptvault/entries/{id}/versions`
- `POST /promptvault/assemble`
- `POST /promptvault/entries/purge_deleted`
- `GET /promptvault/tags`
- `POST /promptvault/tags/tidy`
- `GET /promptvault/llm/config`
- `PUT /promptvault/llm/config`
- `POST /promptvault/llm/auto_tag`
- `POST /promptvault/llm/auto_title`
- `POST /promptvault/llm/auto_title_tags`
- `POST /promptvault/llm/test`
- `POST /promptvault/extract_image_metadata`
- `GET /promptvault/model_resolutions`
