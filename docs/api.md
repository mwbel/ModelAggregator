# 模型聚合独立服务

## 目标

把宇宙模型 MVP 里的模型聚合能力抽成独立 HTTP 服务，供其它项目通过接口访问。当前第一阶段采用“接口层剥离”：

- 保留现有 `backend/services/model_tester.py` 作为模型接入核心。
- 新增 `backend/aggregator_server.py`，只暴露模型聚合相关 API。
- 新增 `start_aggregator.sh`，独立启动聚合服务，不依赖宇宙模型前端、RAG、可视化和 OCR 三栏页面。

这样其它项目只需要访问聚合服务的 HTTP API，不需要引入宇宙模型 MVP 的前端页面。

## 启动

```bash
cd "/Users/Min369/Documents/同步空间/Manju/AIProjects/UnivModel/宇宙模型MVP"
./start_aggregator.sh
```

默认端口：

```text
http://127.0.0.1:8890
```

如果端口被占用，脚本会自动寻找下一个可用端口，并写入：

```text
.run-logs/aggregator.env
```

## 环境变量

聚合服务复用现有 `.env` 中的模型配置：

| 变量 | 用途 |
| --- | --- |
| `MODEL_TESTER_BASE_URL` | 本地/校园网 OpenAI-compatible 服务地址 |
| `MODEL_TESTER_API_KEY` | 本地/校园网服务 API key |
| `MODEL_TESTER_MODELS_PATH` | 模型列表路径 |
| `MODEL_TESTER_CHAT_PATH` | Chat completions 路径 |
| `MODEL_TESTER_MODELS` | 默认本地模型列表 |
| `GEMINI_BASE_URL` | Gemini API 地址 |
| `GEMINI_API_KEYS` | Gemini key 池 |
| `GEMINI_MODELS` | Gemini 默认模型 |
| `YUNWU_API_BASE_URL` | 云雾 GPT-5.5 API 地址 |
| `YUNWU_API_KEY` | 云雾 API key |
| `YUNWU_GPT55_MODEL` | 云雾模型名 |
| `MATHPIX_APP_ID` | Mathpix app id |
| `MATHPIX_APP_KEY` | Mathpix app key |

服务自身变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `AGGREGATOR_HOST` | `127.0.0.1` | 监听地址 |
| `AGGREGATOR_PORT` | `8890` | 起始监听端口 |
| `AGGREGATOR_SERVICE_NAME` | `Model Aggregator Service` | 服务名 |

## API

当前服务版本为 `0.2.0`，健康检查与配置响应会返回 `version`。API 路径仍保持 `/api/aggregate/*`，旧调用方无需迁移到新前缀。

### 健康检查

```http
GET /api/aggregate/health
```

### 获取配置

```http
GET /api/aggregate/config
```

返回 provider、默认模型、统一模型列表和端点信息。

### 列出模型

```http
POST /api/aggregate/models
Content-Type: application/json

{
  "providerPreset": "all"
}
```

`providerPreset` 可选：

- `all`
- `openai-compatible`
- `gemini`
- `yunwu-gpt55`
- `mathpix`

### 上传附件

```http
POST /api/aggregate/upload
Content-Type: application/json

{
  "name": "page.png",
  "kind": "image",
  "mimeType": "image/png",
  "size": 12345,
  "dataUrl": "data:image/png;base64,..."
}
```

返回 `id`，后续图片转 Markdown 使用 `attachmentIds` 引用，不需要重复传图。

### 单模型聊天

```http
POST /api/aggregate/chat
Content-Type: application/json

{
  "model": "gemini:gemini-3.8-flash",
  "messages": [
    {"role": "user", "content": "请总结这段文字"}
  ],
  "temperature": 0.3,
  "maxTokens": 2048
}
```

模型 ID 使用 provider-qualified 格式：

```text
local:qwen3.6-27b:latest
gemini:gemini-3.1-flash-lite
gemini:gemini-3.6-flash
gemini:gemini-3.8-flash
yunwu:gpt-5.5
mathpix:mathpix-text
```

兼容说明：本地 `qwen3.6-27b:latest` 与 `batiai/qwen3.6-27b:q4` 会由聚合器自动通过 Ollama 原生 `/api/chat` 调用，并默认设置 `think=false`。这是为了避免 Ollama 的 OpenAI 兼容接口只返回思考 token、`content` 为空；对调用方的请求路径、模型 ID 和响应字段没有影响。

也可以让服务按任务智能分发：

```http
POST /api/aggregate/chat
Content-Type: application/json

{
  "model": "auto",
  "taskType": "reader.explain",
  "messages": [
    {"role": "user", "content": "请解释这段文献内容"}
  ],
  "temperature": 0.2,
  "maxTokens": 512,
  "constraints": {
    "prefer": "quality"
  }
}
```

`taskType` 当前支持：

| taskType | 用途 |
| --- | --- |
| `general.chat` | 普通问答 |
| `reader.explain` | 文献、段落、原文/译文解释 |
| `reader.translate` | 翻译辅助 |
| `reader.summarize` | 长文或段落总结 |
| `code.debug` | 代码解释、报错定位、修复建议 |
| `structured.json` | 结构化 JSON / schema 输出 |
| `ocr.image_to_markdown` | 图片 OCR 到 Markdown 的模型选择 |
| `compare.reasoning` | 多模型对比、复杂推理、方案评估 |
| `translation.zh_en` | 中译英 benchmark 与自动路由 |
| `ocr.zh` | 中文图片 OCR benchmark 与自动路由 |
| `ocr.bo` | 藏文图片 OCR benchmark 与自动路由 |
| `translation.bo_zh` | 藏译中 benchmark 与自动路由 |

`constraints` 是可选对象，MVP 支持以下键：

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| `prefer` | `quality` / `speed` / `cost` / `privacy` / `balanced` | 路由偏好 |
| `allowProviders` | `["gemini", "yunwu"]` | 只允许这些 provider |
| `denyProviders` | `["local"]` | 排除这些 provider |
| `preferredProvider` | `gemini` | 给某个 provider 加权，但不强制 |
| `requireProvider` | `gemini` | 强制使用某个 provider |
| `requireLocal` | `true` | 只允许本地 OpenAI-compatible 模型 |
| `requireVision` | `true` | 只允许具备图片能力的模型 |
| `maxCostTier` | `medium` | 排除更高成本等级模型 |
| `preferredModels` | `["gemini:gemini-3.8-flash"]` | 给指定模型加权 |
| `denyModels` | `["local:nomic-embed-text:latest"]` | 排除指定模型 |

智能分发响应会保留普通 chat 字段，并额外返回：

```json
{
  "ok": true,
  "answer": "...",
  "model": "gemini-3.8-flash",
  "modelRef": "gemini:gemini-3.8-flash",
  "resolvedModel": "gemini:gemini-3.8-flash",
  "provider": "gemini",
  "requestedModel": "auto",
  "fallbackUsed": false,
  "routerDecision": {
    "ok": true,
    "taskType": "reader.explain",
    "selectedModel": "gemini:gemini-3.8-flash",
    "reason": "..."
  }
}
```

`GET /api/aggregate/config` 会返回 `router`、`modelProfiles`、`taskGuides` 和 `benchmark`，调用方可以据此展示可用任务类型、模型能力、成本/速度/质量等级。`modelProfiles[*].taskScores` 是用于路由的保守初始值，`taskScoreBasis` 会标记其为 `capability-heuristic`；实测结果不会自动覆盖静态值。

`taskGuides.translation.zh_en` 记录中翻英默认建议、质量型备选、快速批量初译、本地隐私翻译和首次多模型比较建议。当前默认建议映射为 `agg-gemini-3.8-flash` / `gemini:gemini-3.8-flash`，质量型备选为 `gemini:gemini-3.6-flash`。画像响应包含 `profileVersion: 2` 和 `registryRevision`；这些建议不替代统一语料 benchmark。

### 路由预览（dry-run）

```http
POST /api/aggregate/route
Content-Type: application/json

{
  "model": "auto",
  "taskType": "reader.explain",
  "messages": [
    {"role": "user", "content": "请解释这段文献内容"}
  ],
  "constraints": {
    "prefer": "quality"
  }
}
```

这个接口只返回选型结果，不实际调用下游 provider。适合：

1. 前端实验台先展示命中模型和原因。
2. benchmark 工具只评估路由策略，不触发真实模型调用。
3. 调用方在执行昂贵任务前，先检查当前约束是否能命中可用模型。

典型响应：

```json
{
  "ok": true,
  "purpose": "chat",
  "taskType": "reader.explain",
  "requestedModel": "auto",
  "selectedModel": "gemini:gemini-3.8-flash",
  "resolvedModel": "gemini:gemini-3.8-flash",
  "provider": "gemini",
  "model": "gemini-3.8-flash",
  "fallbacks": [
    "yunwu:gpt-5.5",
    "local:qwen3.6-27b:latest"
  ],
  "reason": "reader.explain 默认优先质量更高且已配置的视觉/通用模型。",
  "routerDecision": {
    "ok": true,
    "taskType": "reader.explain",
    "selectedModel": "gemini:gemini-3.8-flash",
    "fallbacks": [
      "yunwu:gpt-5.5",
      "local:qwen3.6-27b:latest"
    ]
  }
}
```

如果传入显式模型，例如 `gemini:gemini-3.8-flash`，接口会返回 `manual: true` 的 `routerDecision`，表示本次未执行自动路由，只做兼容性归一化。

### 图片转 Markdown

```http
POST /api/aggregate/image-to-markdown
Content-Type: application/json

{
  "attachmentIds": ["..."],
  "prompt": "将图片中的内容转为 Markdown，数学公式使用 $...$ 或 $$...$$",
  "models": ["gemini:gemini-3.8-flash", "mathpix:mathpix-text"],
  "temperature": 0,
  "maxTokens": 8192
}
```

### 多模型对比

```http
POST /api/aggregate/compare
Content-Type: application/json

{
  "taskType": "chat",
  "models": [
    "local:qwen3.6-27b:latest",
    "gemini:gemini-3.8-flash",
    "yunwu:gpt-5.5"
  ],
  "messages": [
    {"role": "user", "content": "给出这个需求的实现计划"}
  ],
  "temperature": 0.3,
  "maxTokens": 2048
}
```

图片转 Markdown 对比：

```http
POST /api/aggregate/compare
Content-Type: application/json

{
  "taskType": "image-to-markdown",
  "models": ["gemini:gemini-3.8-flash", "mathpix:mathpix-text"],
  "attachmentIds": ["..."],
  "prompt": "将图片转为 Markdown",
  "temperature": 0,
  "maxTokens": 8192
}
```

### 四类任务性能 benchmark

```http
POST /api/aggregate/benchmark
Content-Type: application/json

{
  "tasks": ["translation.zh_en", "ocr.zh", "ocr.bo", "translation.bo_zh"],
  "providers": ["local", "gemini", "yunwu"],
  "cases": [
    {
      "id": "zh-en-1",
      "taskType": "translation.zh_en",
      "sourceText": "模型聚合服务只在后端读取第三方 API key。",
      "reference": "The model aggregation service reads third-party API keys only on the backend."
    },
    {
      "id": "zh-ocr-1",
      "taskType": "ocr.zh",
      "attachmentIds": ["upload 返回的图片附件 id"],
      "reference": "图片中的人工校对中文原文"
    }
  ],
  "runs": 1,
  "includeAnswers": true
}
```

每个 case 必须带 `taskType`。文本任务使用 `sourceText`（也兼容 `input`/`text`）和人工确认的 `reference`；OCR 任务使用 `attachmentIds` 和人工校对的 `reference`。图片先通过 `/api/aggregate/upload` 上传，再把返回的附件 id 放进 case。

`providers` 未传时默认覆盖 `local`、`gemini`、`yunwu`；也可以直接传 `models` 指定 provider-qualified model id。benchmark 会记录每个模型/任务的成功率、错误率、参考文本分数、平均/P50/P95 延迟、平均输出 token 和 token 吞吐，并返回逐案例结果。

评分方法是 `character_f1_sequence`：对归一化后的字符序列计算字符 F1 与序列相似度的加权值。它适合做固定语料回归和模型排序，不代表完整的人工语义评价；尤其是翻译任务应结合人工抽样复核。

## 当前边界

第一阶段只做接口层剥离，核心 provider 调用仍复用 `ModelTesterService`。后续如果要彻底独立成可发布包，建议再拆：

1. `model_registry`：统一模型注册和能力画像。
2. `provider_clients`：OpenAI-compatible、Gemini、Mathpix、Yunwu 等 provider client。
3. `task_router`：根据任务类型、难度、成本和模态选择模型。
4. `execution_engine`：多模型并行、重试、fallback、日志。
5. `result_integrator`：多模型结果整合和冲突裁决。

## 其它项目接入建议

其它应用不要直接读取本项目 `.env`，只访问聚合服务接口：

```text
http://127.0.0.1:8890/api/aggregate/*
```

这样 API key 保留在聚合服务后端，业务应用只拿模型列表、提交任务、获取结果。

## 前端实验台

服务还会提供一个内置前端页面：

```text
http://127.0.0.1:8890/model-tester.html
```

它主要用于：

1. 查看统一模型列表与 provider 预设。
2. 选择 `manual` / `auto` 模式做真实 chat 调用。
3. 单独调用 `POST /api/aggregate/route` 预览路由决策。
4. 带图片附件测试 `ocr.image_to_markdown` 的路由与实际执行。
