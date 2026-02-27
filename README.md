# ComfyUI_PromptVault（提示词库）

声明：本仓库所有代码均由 Codex 编写。

用于 ComfyUI 的提示词保存、检索与拼装自定义节点。

## 功能（V1）
- 提示词增删改查（含软删除 / 回收站）
- 收藏与评分
- SQLite + FTS 全文检索
- 标签管理（左侧栏筛选、整理标签）
- `提示词库检索` / `提示词库保存` 两个节点
- 变量覆盖与拼装输出
- 中文管理器弹窗（主菜单 → 提示词库）

## 安装
- 放置到 `ComfyUI/custom_nodes/ComfyUI_PromptVault`
- 重启 ComfyUI

## 节点用法

### 提示词库检索（PromptVault Query）

从提示词库中检索记录，输出可直接接入 CLIPTextEncode 等下游节点的正负提示词。

| 输入 | 类型 | 说明 |
|------|------|------|
| `query` | STRING | 关键词（按标题/内容/标签全文检索） |
| `title` | STRING | 按标题精确匹配（可选，留空则忽略） |
| `tags` | STRING | 标签过滤，逗号分隔（如 `风景,SDXL`） |
| `model` | STRING | 模型范围过滤（如 `SDXL`、`Flux`） |
| `top_k` | INT | 返回候选数量，默认 1 |
| `variables_json` | STRING | JSON 对象，运行时变量覆盖模板槽位（如 `{"subject": "cat"}`） |

| 输出 | 类型 | 说明 |
|------|------|------|
| `positive_prompt` | STRING | 拼装后的正向提示词 |
| `negative_prompt` | STRING | 拼装后的负向提示词 |

**检索策略**：节点会渐进放宽条件——先严格匹配（关键词 + 标签 + 模型），若无结果则依次去掉模型、标签、仅用关键词，最终回退到最近更新的记录，保证总有输出。

**典型接法**：

```
[PromptVault Query] → positive_prompt → [CLIPTextEncode] → conditioning → [KSampler]
                    → negative_prompt → [CLIPTextEncode] → negative
```

### 提示词库保存（PromptVault Save）

在工作流执行时自动提取生成参数并保存到提示词库，同时生成缩略图。

| 输入 | 类型 | 说明 |
|------|------|------|
| `image` | IMAGE | 生成的图片（必填，用于生成缩略图） |
| `title` | STRING | 记录标题（留空则自动取正向提示词前5字） |
| `tags` | STRING | 标签，逗号分隔（可选） |
| `model` | STRING | 模型名称（可选，留空则自动从工作流提取） |

| 输出 | 类型 | 说明 |
|------|------|------|
| `entry_id` | STRING | 保存成功后的记录 ID |
| `status` | STRING | 操作结果（`保存成功` 或错误信息） |

**自动提取**：节点会从当前工作流的 `prompt`、`extra_pnginfo`（含 workflow / parameters）、以及 LoadImage 源图片的 PNG 元数据中，自动提取正负提示词、steps、cfg、sampler、scheduler、seed、模型名等参数。

**典型接法**：

```
[KSampler] → image → [PromptVault Save]
                      title: "我的风景图"
                      tags: "风景,高清"
```

## 管理器弹窗

在 ComfyUI 主菜单点击「提示词库」打开管理器，可进行：
- 搜索、筛选（关键词 / 标签 / 模型）
- 新建、编辑、删除记录
- 回收站查看与还原、清空回收站
- 标签栏按标签分类浏览
- 整理标签（删除无引用标签、补充缺失标签）
- 查看详情与拼装预览、复制正向提示词
- 一键创建检索节点到画布

## 后端 API
- `GET /promptvault/health`
- `GET /promptvault/entries`
- `POST /promptvault/entries`
- `PUT /promptvault/entries/{id}`
- `DELETE /promptvault/entries/{id}`
- `POST /promptvault/assemble`
- `POST /promptvault/entries/purge_deleted`
- `POST /promptvault/tags/tidy`
