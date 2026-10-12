# ModelAggregatorService

独立模型聚合服务。它从 `Universe Model Agent / 宇宙模型MVP` 中剥离出来，作为多个 AI 项目共享的基础设施。

## 定位

这个项目只负责模型聚合接口：

- 统一列出本地模型、Gemini、云雾 GPT-5.5、Mathpix。
- 通过 provider-qualified model id 调用不同模型。
- 支持单模型聊天。
- 支持多模型对比。
- 支持中译英、中文 OCR、藏文 OCR、藏译中的可复现实测画像。
- 支持图片上传后转 Markdown。
- API key 只保存在本服务后端，不暴露给各应用前端。

## 启动

```bash
cd "/Users/Min369/Documents/同步空间/Manju/AIProjects/ModelAggregatorService"
./start.sh
```

默认地址：

```text
http://127.0.0.1:8890
```

如果端口被占用，启动脚本会自动寻找下一个可用端口，并写入：

```text
.run-logs/aggregator.env
```

## API

当前服务版本为 `0.2.0`。本次只扩展模型目录和画像字段，API 前缀继续使用 `/api/aggregate`。

```text
GET  /api/aggregate/health
GET  /api/aggregate/config
POST /api/aggregate/models
POST /api/aggregate/route
POST /api/aggregate/upload
POST /api/aggregate/chat
POST /api/aggregate/image-to-markdown
POST /api/aggregate/compare
POST /api/aggregate/benchmark
```

## 模型 ID

服务使用 provider-qualified model id：

```text
local:qwen3.6-27b:latest
gemini:gemini-3.1-flash-lite
gemini:gemini-3.6-flash
gemini:gemini-3.8-flash
yunwu:gpt-5.5
mathpix:mathpix-text
```

## 示例：列出所有模型

```bash
curl -s http://127.0.0.1:8890/api/aggregate/models \
  -H 'Content-Type: application/json' \
  -d '{"providerPreset":"all"}'
```

## 示例：单模型聊天

```bash
curl -s http://127.0.0.1:8890/api/aggregate/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "gemini:gemini-3.8-flash",
    "messages": [{"role": "user", "content": "只回复 OK"}],
    "temperature": 0,
    "maxTokens": 16
  }'
```

本地 `qwen3.6-27b:latest` 和 `batiai/qwen3.6-27b:q4` 会自动改走 Ollama 原生 `/api/chat`，并默认关闭思考输出，避免 OpenAI 兼容接口只产生思考 token、最终正文为空。调用方仍使用相同的 `/api/aggregate/chat` 请求格式，无需改接口或模型 ID。

## 示例：智能分发

调用方可以把 `model` 设为 `auto`，并用 `taskType` 描述任务。服务会根据模型能力档案、provider 配置和可选约束选择实际模型，响应里会返回 `resolvedModel` 和 `routerDecision`。

```bash
curl -s -X POST http://127.0.0.1:8890/api/aggregate/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "auto",
    "taskType": "reader.explain",
    "messages": [{"role": "user", "content": "请解释这段文献内容"}],
    "temperature": 0.2,
    "maxTokens": 512,
    "constraints": {"prefer": "quality"}
  }'
```

当前支持的任务类型包括：

```text
general.chat
reader.explain
reader.translate
reader.summarize
code.debug
structured.json
ocr.image_to_markdown
compare.reasoning
translation.zh_en
ocr.zh
ocr.bo
translation.bo_zh
```

其中：

- `translation.zh_en`：中译英。
- `ocr.zh`：中文图片 OCR。
- `ocr.bo`：藏文图片 OCR。
- `translation.bo_zh`：藏译中。

`GET /api/aggregate/config` 会返回 `benchmark.tasks`、模型的 `taskScores` 和 `taskScoreBasis`。`taskScores` 是用于自动路由的保守初始画像；要得到当前环境下的实测画像，请使用 benchmark 接口。

### 中翻英默认选择

`translation.zh_en` 的默认建议模型是 `gemini:gemini-3.8-flash`，对应 AS译林规范 ID `agg-gemini-3.8-flash`；`gemini:gemini-3.6-flash` 可作为质量型备选，快速批量初译仍可使用 `agg-gemini-3.1-flash-lite`。隐私材料优先使用本地 `agg-local-qwen3.6-27b`；重要材料首次选型可先通过 `agg-compare-all` 比较。此建议尚无统一语料横向评分。

这项默认推荐基于模型定位，不等同于七个模型在同一组中英语料上的完整横向评分。当前已实际验证的是 `agg-gemini-3.1-flash-lite` 中翻英链路，单次记录约 `1.29s`。完整用途、旧名称兼容列表和证据边界由 `GET /api/aggregate/config` 的 `taskGuides.translation.zh_en` 返回；当前画像版本为 `profileVersion: 2`。

## 示例：四类任务性能画像

benchmark 不内置未经确认的 OCR/藏文参考答案。调用方应提供自己的图片附件和人工确认的 `reference`，这样分数才对应自己的字体、语料和任务要求。

```bash
curl -s -X POST http://127.0.0.1:8890/api/aggregate/benchmark \
  -H 'Content-Type: application/json' \
  -d '{
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
        "id": "bo-zh-1",
        "taskType": "translation.bo_zh",
        "sourceText": "在这里填入人工确认的藏文测试句。",
        "reference": "在这里填入人工确认的中文参考译文。"
      },
      {
        "id": "zh-ocr-1",
        "taskType": "ocr.zh",
        "attachmentIds": ["上传接口返回的图片附件 id"],
        "reference": "图片中的人工校对中文原文"
      },
      {
        "id": "bo-ocr-1",
        "taskType": "ocr.bo",
        "attachmentIds": ["上传接口返回的图片附件 id"],
        "reference": "图片中的人工校对藏文原文"
      }
    ],
    "runs": 1,
    "includeAnswers": true
  }'
```

响应中的每个模型 profile 都包含四类任务的 `successRate`、`avgScore`、`avgLatencyMs`、`p50LatencyMs`、`p95LatencyMs`、`tokensPerSecond` 和逐案例结果。`avgScore` 使用 reference 的字符 F1 与序列相似度计算，只作为筛选和回归指标，不替代人工质量评审。

## 示例：只预览路由，不实际调用模型

`POST /api/aggregate/route` 只做 dry-run 选型，适合前端实验台、benchmark 面板或调用方在发起真实请求前先看命中模型和 fallback 候选。

```bash
curl -s -X POST http://127.0.0.1:8890/api/aggregate/route \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "auto",
    "taskType": "reader.explain",
    "messages": [{"role": "user", "content": "请解释这段文献内容"}],
    "constraints": {"prefer": "quality"}
  }'
```

## 示例：多模型对比

```bash
curl -s http://127.0.0.1:8890/api/aggregate/compare \
  -H 'Content-Type: application/json' \
  -d '{
    "taskType": "chat",
    "models": ["gemini:gemini-3.8-flash", "yunwu:gpt-5.5"],
    "messages": [{"role": "user", "content": "给出这个任务的实现计划"}],
    "temperature": 0.3,
    "maxTokens": 2048
  }'
```

## 其它项目接入

其它项目只需要配置：

```env
MODEL_AGGREGATOR_BASE_URL="http://127.0.0.1:8890"
```

然后通过 HTTP 调用本服务，不需要直接保存 Gemini、云雾、Mathpix 或本地服务 API key。

## 前端实验台

服务内置了一个模型测试与路由实验台：

```text
http://127.0.0.1:8890/model-tester.html
```

它可以：

- 手动选择模型做单轮/多轮测试。
- 切换 `manual` / `auto` 调用模式。
- 预览 `/api/aggregate/route` 的命中模型、fallbacks 和原因。
- 带附件测试 `ocr.image_to_markdown` 路由。

## 后续拆分方向

当前版本已经拆出第一版能力档案与任务路由，但 provider 调用和执行链路仍主要集中在：

```text
model_aggregator/services/model_aggregator.py
```

下一阶段建议拆成：

- `services/model_registry.py`
- `services/task_router.py`
- `providers/openai_compatible.py`
- `providers/gemini.py`
- `providers/yunwu.py`
- `providers/mathpix.py`
- `services/execution_engine.py`
- `services/result_integrator.py`
