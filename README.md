# ComfyUI_PromptVault（提示词库）

一个用于保存、检索、拼装 ComfyUI 提示词的自定义节点与中文管理器 UI。

## 功能（V1）

- 主菜单新增 `提示词库`，弹出中文 `提示词库管理器`
- 提示词增删改查（软删除进入回收站逻辑暂未做 UI，但后端已标记 `status=deleted`）
- SQLite + FTS 全文检索（标题/内容/标签）
- `提示词库检索` 节点：按关键词/标签/模型检索并输出正/负提示词
- 拼装逻辑：支持 raw 提示词中的 `{变量}` 替换，节点 `variables_json` 可覆盖

## 安装

将本目录放到 ComfyUI 的 `custom_nodes/` 下：

- `custom_nodes/ComfyUI_PromptVault`

重启 ComfyUI 后生效。

## 使用

1. 打开 ComfyUI 页面后，在顶部找到 `提示词库` 按钮。
- 如果没看到，先 `Ctrl+F5` 强制刷新浏览器缓存，再重启一次 ComfyUI。
- 打开浏览器控制台，确认有日志 `[PromptVault] extension loaded ...`。
- 若顶部菜单不存在，会自动在右上角显示悬浮按钮 `提示词库`。
 - 本插件兼容两种加载方式：`web/promptvault.js` 与 `web/js/promptvault.js`，若目录里有历史旧文件请清理后再重启。
2. 在弹窗中点 `新建`，输入：
   - 标题、标签、模型范围
   - 正向/负向提示词（raw）
   - 变量 JSON（可选，例如 `{\"subject\":\"young woman\"}`）
3. 点击列表项可在右侧预览拼装结果。
4. 点击 `新建查询节点`，会在画布中创建 `提示词库检索` 节点。

节点输入说明：
- `query`：关键词（可空）
- `tags`：标签（逗号分隔）
- `model`：模型范围过滤（可空）
- `top_k`：返回条数（当前节点选择第一条）
- `variables_json`：运行时变量覆盖（对象 JSON）

## 后端 API（本地）

- `GET /promptvault/health`
- `GET /promptvault/entries?q=&tags=&model=&status=&limit=&offset=`
- `POST /promptvault/entries`
- `GET /promptvault/entries/{id}`
- `PUT /promptvault/entries/{id}`
- `DELETE /promptvault/entries/{id}`
- `GET /promptvault/entries/{id}/versions`
- `POST /promptvault/assemble`
- `POST /promptvault/fragments` / `GET /promptvault/fragments/{id}`
- `POST /promptvault/templates` / `GET /promptvault/templates/{id}`
- `GET /promptvault/tags`

数据文件：
- 默认存放在 ComfyUI 的 `user/promptvault/promptvault.db`（优先使用 ComfyUI user 目录）
