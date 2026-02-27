# ComfyUI_PromptVault（提示词库）

声明：本仓库所有代码均由 Codex 编写。

用于 ComfyUI 的提示词保存、检索与拼装自定义节点。

## 功能（V1）
- 提示词增删改查（含软删除状态）
- SQLite + FTS 全文检索
- `提示词库检索` 节点输出正负提示词
- 变量覆盖与拼装输出

## 安装
- 放置到 `ComfyUI/custom_nodes/ComfyUI_PromptVault`
- 重启 ComfyUI

## 后端 API
- `GET /promptvault/health`
- `GET /promptvault/entries`
- `POST /promptvault/entries`
- `PUT /promptvault/entries/{id}`
- `DELETE /promptvault/entries/{id}`
- `POST /promptvault/assemble`
