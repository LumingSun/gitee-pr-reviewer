# Gitee PR 自动评审服务 — 项目说明

## 1. 项目定位

当开发者在 Gitee（码云）上提交 Pull Request 时，本服务自动对代码变更进行 AI 审查，并将评审报告以评论形式回贴到 PR 中。

**解决什么问题**：

- 人工 Code Review 是团队瓶颈——评审者需要逐行阅读代码变更，耗时且容易遗漏
- 本服务作为**第一道自动化防线**，在 PR 打开的瞬间即刻启动审查，帮团队先过一遍，让人工评审聚焦于 AI 发现的问题和架构层面的决策
- 评审标准统一（每次使用相同的检查清单），不会因为不同评审者的偏好产生差异

## 2. 工作原理（一分钟版）

```
开发者提交 PR
      │
      ▼
Gitee 发送 Webhook ──────→ Flask 服务验证身份
      (HTTP POST)                │
                                 ▼
                          后台线程异步处理
                                 │
                     ┌───────────┼───────────┐
                     ▼           ▼           ▼
              Gitee MCP    DeepSeek    Code Review
              Server        LLM        Expert Skill
              (本地部署)    (AI 模型)    (评审规则)
                     │           │           │
                     └───────────┼───────────┘
                                 ▼
                         生成评审报告(P0~P4)
                                 │
                                 ▼
                         回贴评论到 PR
```

核心流程只有四步：

1. **接收** — Gitee 发来 Webhook 通知（"有人开了一个 PR"）
2. **取数** — 通过本地 MCP Server 拉取 PR 中代码的具体变更（diff）
3. **分析** — 将 diff 提交给 AI（DeepSeek），按预设的评审规范逐条检查
4. **回贴** — 将评审报告格式化为 Markdown 评论，通过 MCP Server 写回 PR 评论区

## 3. 架构分层

### 3.1 Flask Webhook Server（入口层）

- 一个轻量 HTTP 服务，暴露 `/webhook` 端点
- 职责：**验证身份 → 解析事件 → 触发后台任务 → 立即返回 200**
- 为什么立刻返回？Gitee Webhook 有超时限制（约 10 秒），而 AI 审查可能需要数十秒，因此采用异步模式——Webhook 返回后，审查在后台线程中运行

### 3.2 PR Review Agent（智能体层）

- 基于 LangChain 的 AI Agent
- 集成了三个关键能力：
  - **MCP 工具**：连接本地 Gitee MCP Server，调用获取 PR 详情、获取代码 diff、创建评论等接口
  - **大语言模型**：使用 DeepSeek 模型理解代码变更、分析潜在问题
  - **评审技能**：载入预设的代码审查检查清单（涵盖安全、性能、可维护性等维度）

### 3.3 Gitee MCP Server（数据通道层）

- **前置依赖**，需在本地环境中独立启动
- 通过 MCP (Model Context Protocol) 标准化协议暴露 Gitee API 能力
- Agent 不直接调用 Gitee API，而是通过 MCP Server 中转——这样做的好处是将 API 调用逻辑与业务逻辑解耦

### 3.4 DeepSeek LLM（AI 模型层）

- 负责理解代码语义、发现逻辑缺陷、评估代码质量
- 评审使用的温度参数为 0（不随机），确保每次对同一段代码的评审结果稳定可复现

## 4. 评审报告等级体系

评审报告使用 P0 ~ P4 五级严重度分类，跟业界标准对齐：

| 等级 | 含义 | 典型场景 |
|------|------|----------|
| **P0** | 严重/阻塞 | 安全漏洞、数据丢失风险、生产事故隐患，必须立即修复 |
| **P1** | 高优先级 | 功能缺陷、逻辑错误、性能严重退化，应在合并前修复 |
| **P2** | 中优先级 | 代码异味、可维护性问题、不符合团队规范，建议修复 |
| **P3** | 低优先级 | 命名建议、代码风格、小优化，不妨碍功能但值得改进 |
| **P4** | 建议/可选 | 长期重构建议、架构演进方向，可在未来迭代中考虑 |

每个问题都会附带：所在文件与行号、问题描述、建议修复方案。

## 5. 安全机制

| 安全措施 | 说明 |
|----------|------|
| **Webhook 签名校验** | Gitee 在发送 Webhook 时携带 `X-Gitee-Token` 头，服务端通过对比 `GITEE_WEBHOOK_SECRET` 验证请求来源，防止伪造 Webhook |
| **Token 认证链** | 每个外部通信链路都有独立认证：Webhook 用 Webhook 密钥、MCP Server 用 Gitee 个人令牌、LLM 用 API Key |
| **最小权限** | MCP Server 仅启用必要的 6 个工具（如：获取文件内容、获取 diff、创建评论等），不会暴露仓库删除等危险 API |
| **本地部署** | Gitee MCP Server 和本服务均部署在本地或内网环境 |
| **异步隔离** | 后台审查任务以独立线程运行，即使审查失败也不会影响 Webhook 的正常响应 |


## 6. 依赖关系

```
Gitee PR Reviewer 服务
├── Gitee MCP Server（前置，需本地启动）
│   └── 依赖：Gitee Personal Access Token
├── DeepSeek API（云服务）
│   └── 依赖：DeepSeek API Key
└── Code Review Skill（评审规则文件）
    └── 来源：GitHub 远程加载
```

**Gitee MCP Server 启动方式**：

```bash
./bin/mcp-gitee --token <gitee-token> --transport http \
  --enabled-toolsets="get_file_content,compare_branches_tags,list_repo_pulls,get_pull_detail,get_diff_files,create_comment"
```

启动后监听 `http://localhost:8000/mcp`，本服务通过该地址连接。

## 7. 部署方式

支持两种部署方式：

- **直接运行**：`pip install -r requirements.txt && python -m src.app`，适合本地开发与调试
- **Docker 部署**：`docker-compose up --build`，适合生产或标准化环境

两种方式均需确保 Gitee MCP Server 已在同一网络内启动且网络可通。

## 8. 扩展性

- **评审规则可定制**：修改 `resources/review_prompt.md` 即可调整评审重点、增减检查项
- **支持 SSL/HTTPS**：通过配置证书路径启用，适合需要加密传输的生产环境
- **非 Gitee 平台适配**：核心 Agent 层与平台解耦，理论上可替换 MCP Server 适配其他 Git 平台（如 GitLab、GitHub）
