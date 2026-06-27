# 从宇宙模型 MVP 迁移说明

## 当前状态

模型聚合服务已经迁移为与 `UnivModel`、`AlVisualization` 平级的独立项目：

```text
/Users/Min369/Documents/同步空间/Manju/AIProjects/ModelAggregatorService
```

当前独立服务已验证启动：

```text
http://127.0.0.1:8890
```

旧的宇宙模型 MVP 内部测试服务已经停用，独立项目现在占用默认端口 `8890`。

## 推荐接入方式

其它项目只配置聚合服务地址：

```env
MODEL_AGGREGATOR_BASE_URL="http://127.0.0.1:8890"
```

然后调用：

```text
GET  /api/aggregate/config
POST /api/aggregate/models
POST /api/aggregate/chat
POST /api/aggregate/compare
POST /api/aggregate/upload
POST /api/aggregate/image-to-markdown
```

## 已迁移内容

从宇宙模型 MVP 迁移出的核心能力：

- OpenAI-compatible 本地/校园网模型服务
- Gemini key 池轮值
- 云雾 GPT-5.5
- Mathpix OCR
- 图片附件上传
- 图片转 Markdown
- 多模型 compare 接口

## 已从宇宙模型移除的旧副本

宇宙模型 MVP 中的临时聚合服务副本已经删除：

```text
backend/aggregator_server.py
start_aggregator.sh
scripts/launch_aggregator.py
docs/model-aggregator-service.md
```

当前依赖搜索只剩 `PRD_智能聚合系统.md` 中的未来产品接口草案引用，不再依赖旧副本文件。

## 验证命令

```bash
cd "/Users/Min369/Documents/同步空间/Manju/AIProjects/ModelAggregatorService"

python3 -m py_compile \
  model_aggregator/server.py \
  model_aggregator/config.py \
  model_aggregator/services/model_aggregator.py \
  scripts/launch_aggregator.py

curl -s http://127.0.0.1:8890/api/aggregate/health

curl -s http://127.0.0.1:8890/api/aggregate/models \
  -H 'Content-Type: application/json' \
  -d '{"providerPreset":"all"}'
```

## 后续清理建议

1. 修改 `宇宙模型MVP`、`AlVisualization`、其它项目，统一读取 `MODEL_AGGREGATOR_BASE_URL`。
2. 确认所有项目都能调用独立服务后，再逐步把项目内重复的模型调用 UI/逻辑改成调用聚合服务。
