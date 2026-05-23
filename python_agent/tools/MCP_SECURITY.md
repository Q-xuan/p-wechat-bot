# MCP 安全设计（方案 B）

## 设计原则

Python Agent 工具注册表保持最小化，只能执行明确授权的"只读查询"类工具。MCP 接入需白名单审查。

## 工具分类

### 已授权工具（白名单内）
- `queryWechat` — HTTP 调用 Node.js 读取聊天 JSON 文件（只读）
- `searchWeb` — 调用外部搜索 API（无本地 I/O）

### 禁止的工具类型
- shell / exec / subprocess
- file/read / file/write
- 网络爬虫（定向抓取网页内容）
- 任何未经明确授权的 MCP 工具

## MCP 接入规则

1. **白名单审查**：新 MCP 工具必须手动添加到 `ALLOWED_MCP_TOOLS` 列表
2. **工具描述审查**：工具描述不得暗示本地文件/命令操作能力
3. **禁止 MCP 服务器带危险工具**：若 MCP 服务器自身注册了 shell/file/subprocess 类工具，禁止接入

## MCP 工具注册流程

```
1. 确认 MCP 服务器名称和版本
2. 检查该 MCP 服务器的工具列表
3. 对每个计划使用的工具：
   - 确认是"只读查询"类（搜索/获取信息/计算）
   - 不涉及本地文件创建/删除/修改
   - 不涉及系统命令执行
   - 不涉及网络爬取（非授权网页抓取）
4. 将允许的工具添加到 ALLOWED_MCP_TOOLS
5. 在 registry.py 中配置并测试
```

## 工具执行验证（execute_tool 函数内）

每次执行工具前，验证：
1. 工具在 `ALLOWED_MCP_TOOLS` 白名单中
2. 参数不包含可疑的路径穿越（如 `../` 路径）
3. 参数长度合理（防止注入）