# ModelAggregatorService

独立模型聚合服务。它从 `Universe Model Agent / 宇宙模型MVP` 中剥离出来，作为多个 AI 项目共享的基础设施。

## 定位

这个项目只负责模型聚合接口：

- 统一列出本地模型、Gemini、云雾 GPT-5.5、Mathpix。
- 通过 provider-qualified model id 调用不同模型。
- 支持单模型聊天。
- 支持多模型对比。
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

```text
GET  /api/aggregate/health
GET  /api/aggregate/config
POST /api/aggregate/models
POST /api/aggregate/upload
POST /api/aggregate/chat
POST /api/aggregate/image-to-markdown
POST /api/aggregate/compare
```

## 模型 ID

服务使用 provider-qualified model id：

```text
local:qwen3.6-27b:latest
gemini:gemini-2.5-flash
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
    "model": "gemini:gemini-2.5-flash",
    "messages": [{"role": "user", "content": "只回复 OK"}],
    "temperature": 0,
    "maxTokens": 16
  }'
```

## 示例：多模型对比

```bash
curl -s http://127.0.0.1:8890/api/aggregate/compare \
  -H 'Content-Type: application/json' \
  -d '{
    "taskType": "chat",
    "models": ["gemini:gemini-2.5-flash", "yunwu:gpt-5.5"],
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

## 后续拆分方向

当前版本是最小可运行迁移，核心逻辑仍集中在：

```text
model_aggregator/services/model_aggregator.py
```

下一阶段建议拆成：

- `providers/openai_compatible.py`
- `providers/gemini.py`
- `providers/yunwu.py`
- `providers/mathpix.py`
- `services/model_registry.py`
- `services/model_scheduler.py`
- `services/execution_engine.py`
- `services/result_integrator.py`
