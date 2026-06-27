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
  "model": "gemini:gemini-2.5-flash",
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
gemini:gemini-2.5-flash
yunwu:gpt-5.5
mathpix:mathpix-text
```

### 图片转 Markdown

```http
POST /api/aggregate/image-to-markdown
Content-Type: application/json

{
  "attachmentIds": ["..."],
  "prompt": "将图片中的内容转为 Markdown，数学公式使用 $...$ 或 $$...$$",
  "models": ["gemini:gemini-2.5-flash", "mathpix:mathpix-text"],
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
    "gemini:gemini-2.5-flash",
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
  "models": ["gemini:gemini-2.5-flash", "mathpix:mathpix-text"],
  "attachmentIds": ["..."],
  "prompt": "将图片转为 Markdown",
  "temperature": 0,
  "maxTokens": 8192
}
```

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
