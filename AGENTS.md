# AGENTS.md

## 项目目标

本项目是独立的模型聚合服务，为多个本地 AI 项目提供统一 HTTP 接口。

核心链路：

```text
client project
→ ModelAggregatorService HTTP API
→ provider-qualified model routing
→ local / Gemini / Yunwu / Mathpix / future providers
→ normalized response
→ caller-side workflow
```

项目目标不是聊天前端，也不是某一个业务项目的内部模块；目标是成为共享模型基础设施，统一管理模型列表、模型调用、图片转 Markdown、多模型对比、鉴权配置与可观测性。

当前重点调用方包括：

1. `ResearchManjusi/reader-workbench` 的 AI 解释工作台。
2. 后续其它研究、OCR、知识库、实验执行项目。

## 执行前必须先输出 Preflight Plan

Codex 修改代码前必须先输出：

1. 本次任务目标。
2. 准备修改的文件。
3. 明确不会修改的文件。
4. 是否涉及：
   - `model_aggregator/server.py`
   - `model_aggregator/config.py`
   - `model_aggregator/services/model_aggregator.py`
   - `frontend/`
   - `docs/api.md`
   - `README.md`
   - `start.sh`
   - `scripts/launch_aggregator.py`
   - `.env.example`
   - API 路由、响应字段、鉴权、CORS、超时、重试、日志
5. 准备运行的测试或检查命令。
6. 如果涉及接口变更，必须给出至少一个 `curl` 冒烟测试示例。

输出 Preflight Plan 后，除非用户明确说“等我确认”“不要修改”“先分析”“只读”，否则无需等待确认，可以直接执行修改。

## 当前服务边界

本服务只负责模型聚合，不负责业务侧知识库、阅读器、OCR 校对 UI 或长期数据投影。

允许范围：

1. 暴露模型聚合 HTTP API。
2. 统一 provider-qualified model id。
3. 后端读取模型 API Key 和 provider 配置。
4. 归一化不同 provider 的模型列表、chat、图片转 Markdown、对比结果。
5. 为调用方提供稳定错误结构、健康检查与配置摘要。

不负责：

1. 保存业务项目的原始资料。
2. 写入 `ResearchManjusi/LLM Wiki/wiki` 或 `raw`。
3. 写入 OCR 校对 accepted patch。
4. 管理调用方前端页面状态。
5. 在浏览器端暴露第三方模型 API Key。

## 当前 API 规范

接口前缀固定为：

```text
/api/aggregate
```

当前关键接口：

```text
GET  /api/aggregate/health
GET  /api/aggregate/config
POST /api/aggregate/models
POST /api/aggregate/upload
POST /api/aggregate/chat
POST /api/aggregate/image-to-markdown
POST /api/aggregate/compare
```

模型 ID 必须采用 provider-qualified 格式：

```text
local:qwen3.6-27b:latest
gemini:gemini-2.5-flash
yunwu:gpt-5.5
mathpix:mathpix-text
```

响应应尽量保持以下字段可用：

1. `ok`
2. `error`
3. `model` / `resolvedModel`
4. `provider`
5. `content` / `answer` / `markdown`
6. `latencyMs`
7. `rawPreview`，不要默认返回过大的 raw provider 响应

## Reader Workbench 接入约束

`ResearchManjusi/reader-workbench` 的 AI 解释工作台会把本服务作为模型聚合接口。

推荐调用方式：

```text
POST /api/aggregate/chat
```

请求应兼容普通 chat body：

```json
{
  "model": "gemini:gemini-2.5-flash",
  "messages": [
    {"role": "system", "content": "你是研究阅读工作台的 AI 解释助手。"},
    {"role": "user", "content": "文档标题、页码、段落 ID、原文、翻译、用户问题"}
  ],
  "temperature": 0.2,
  "maxTokens": 2048
}
```

为 reader 类任务新增能力时，优先在本服务保持通用接口，不要把 `reader-workbench` 的业务字段硬编码成唯一格式。可以接受 `metadata` 字段，但它应作为透传日志和调用追踪，不应破坏普通 chat 兼容性。

## MVP 当前优先级

优先顺序：

1. 保持 `/api/aggregate/*` 现有接口兼容。
2. 保证 API Key 只在后端 `.env` 或运行环境中读取，不暴露给调用方前端。
3. 优先稳定 `health`、`config`、`models`、`chat` 四个基础接口。
4. 保持 `image-to-markdown` 和 `compare` 的现有行为。
5. 增强错误信息、日志、耗时统计和调用可追踪性。
6. 后续再拆 provider clients、model registry、task router、execution engine。

## 禁止越界修改

除非任务明确要求，否则禁止修改：

1. `.env`
2. `.run-logs/`
3. `.git/`
4. 本地密钥、token、API key、运行 pid 或日志文件
5. 现有 API 路径前缀 `/api/aggregate`
6. 现有路由响应字段的兼容行为
7. 与当前任务无关的 `frontend/` 大面积样式重写
8. package 或 Python 依赖声明
9. 非本项目目录内的调用方代码

不要恢复、删除或覆盖用户已有未提交改动，除非用户明确要求。

对于较重要的代码更新，在完成必要的测试和检查后，应自动执行 Git 提交并推送到远程 GitHub 仓库。推送前必须确认真实仓库根目录、当前分支、远程地址和待提交文件，避免推送无关改动或敏感信息；如果发现远程状态、分支归属或提交范围不明确，应先暂停并说明情况。

## 配置与安全规则

1. 所有敏感信息只允许通过环境变量或 `.env` 读取。
2. 不得把真实 API Key 写入代码、文档、测试样例或提交记录。
3. 新增环境变量时必须同步更新 `.env.example`，并说明默认值和用途。
4. 前端页面不得直接持有 Gemini、Yunwu、Mathpix 或 OpenAI-compatible 服务密钥。
5. 若修改 CORS、鉴权、token 校验、速率限制，必须说明对现有调用方的影响和迁移方式。

## 变更规则

1. 若修改接口路径或请求/响应格式，必须同步更新 `README.md` 和 `docs/api.md`。
2. 若修改 `model_aggregator/config.py`，必须确认 `.env.example` 是否需要同步。
3. 若修改 `start.sh` 或 `scripts/launch_aggregator.py`，必须说明端口选择、日志路径和后台进程行为。
4. 若修改 provider 调用逻辑，必须保留 provider-qualified model id 兼容。
5. 若新增 provider，必须至少补充模型列表、单模型 chat、错误归一化和文档示例。
6. 若新增对比或多模型调度能力，必须保持单模型 chat 不受影响。

## 常用启动与检查

启动服务：

```bash
cd "/Users/Min369/Documents/同步空间/Manju/AIProjects/ModelAggregatorService"
./start.sh
```

默认地址：

```text
http://127.0.0.1:8890
```

常用检查：

```bash
python -m compileall model_aggregator scripts
curl -s http://127.0.0.1:8890/api/aggregate/health
curl -s http://127.0.0.1:8890/api/aggregate/config
```

单模型 chat 冒烟：

```bash
curl -s -X POST http://127.0.0.1:8890/api/aggregate/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemini:gemini-2.5-flash","messages":[{"role":"user","content":"只回复 OK"}],"temperature":0,"maxTokens":16}'
```

模型列表冒烟：

```bash
curl -s -X POST http://127.0.0.1:8890/api/aggregate/models \
  -H 'Content-Type: application/json' \
  -d '{"providerPreset":"all"}'
```

如果服务正在运行且修改了后端代码，修改后需要重启 `./start.sh` 对应的进程。

## 回答风格

默认用中文回答。

完成修改后说明：

1. 改了什么。
2. 影响哪个接口或调用方。
3. 运行了哪些检查。
4. 是否需要重启服务。
5. 是否需要调用方同步调整配置。

不要把 `.env`、token、完整日志或大段命令输出贴给用户。
