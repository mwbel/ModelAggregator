# 模型智能分发设计说明

## 目标

智能分发层用于在调用方不想手动指定模型时，根据任务类型、模型能力档案和调用约束选择一个合适的 provider-qualified model id。

当前 MVP 的目标是：

1. 保持 `/api/aggregate/*` 现有接口兼容。
2. 允许 `POST /api/aggregate/chat` 使用 `model: "auto"`。
3. 新增 `POST /api/aggregate/route`，让调用方可先做 dry-run 选型。
4. 让路由决策可解释，响应中返回 `routerDecision`。
5. 先用保守的静态能力画像启动，再通过 benchmark 和运行反馈修正分数。

它暂时不负责：

1. 自动改写业务侧 prompt。
2. 保存调用方业务数据。
3. 自动训练或微调模型。
4. 取代人工选择模型。
5. 对所有 provider 做复杂并行竞价或动态成本核算。

## 核心链路

```text
client request
→ /api/aggregate/chat or /api/aggregate/route
→ model: "auto" or manual model ref
→ task_router
→ model_registry
→ selected provider-qualified model id
→ existing provider call path (chat only)
→ normalized response + routerDecision
```

手动指定模型时，例如 `gemini:gemini-3.8-flash`，路由层不会重新选择模型，只补充兼容性的 `provider`、`modelRef`、`resolvedModel` 等字段。

## 模型能力档案

模型能力档案由 `model_aggregator/services/model_registry.py` 生成。每个模型会被表示成一个 `ModelProfile`。

关键字段：

| 字段 | 含义 |
| --- | --- |
| `id` | provider-qualified model id，例如 `gemini:gemini-3.8-flash` |
| `provider` | 内部 provider 名，例如 `gemini`、`openai-compatible`、`yunwu-gpt55` |
| `providerPrefix` | 对调用方暴露的模型前缀，例如 `local`、`gemini`、`yunwu` |
| `model` | provider 内部模型名 |
| `available` | 当前 provider 配置是否完整 |
| `chatCapable` | 是否适合普通 chat 调用 |
| `imageCapable` | 是否可能支持图片输入 |
| `supportsJson` | 是否适合结构化 JSON 输出 |
| `contextWindow` | 已知上下文窗口；未知时为 `null` |
| `costTier` | 成本等级：`low`、`low-medium`、`medium`、`high` |
| `speedTier` | 速度等级：`slow`、`medium`、`fast` |
| `qualityTier` | 质量等级：`medium`、`medium-high`、`high` |
| `privacy` | `local` 或 `remote` |
| `strengths` | 主要优势说明 |
| `limits` | 能力边界说明 |
| `taskScores` | 各任务类型的初始能力分数 |
| `profileVersion` | 模型画像结构版本；当前为 `2` |
| `registryRevision` | 模型目录修订日期 |
| `adapterId` | 对应的 AS译林适配器模型 ID；没有映射时为 `null` |
| `legacyAdapterIds` | 仍可调用的旧适配器名称 |
| `translationZhEn` | 中翻英用途、推荐说明和证据边界；非本次七模型时为 `null` |

这些字段通过 `GET /api/aggregate/config` 的 `modelProfiles` 返回，便于调用方展示模型能力，也便于排查路由决策。

### 中翻英模型选择画像

`translation.zh_en` 的默认建议为 `agg-gemini-3.8-flash`。用途建议如下：

| AS译林模型 | 画像与建议 |
| --- | --- |
| `agg-gemini-3.8-flash` | 当前目录中的高能力 Flash 型号，可用于正式译文、长文和复杂句；仍建议按实际语料评估。 |
| `agg-gemini-3.6-flash` | 质量型备选，可用于复杂任务和模型对照。 |
| `agg-gemini-3.1-flash-lite` | 速度快、成本低，适合批量初译和短段落；当前环境已有成功中翻英记录，约 1.29 秒。旧名 `agg-gemini-31-flash-lite` 继续兼容。 |
| `agg-local-qwen3.6-27b` | 本地模型首选，适合隐私材料或不希望调用外部 API 的情况。旧名 `agg-local-qwen36` 继续兼容。 |
| `agg-local-qwen3.6-27b-q4` | 更省资源，但量化可能损失措辞准确性，不建议作为终稿首选。旧名 `agg-local-qwen36-q4` 继续兼容。 |
| `agg-local-qwen2.5-14b` | 可用，但整体能力预计弱于 Qwen 3.6 27B。旧名 `agg-local-qwen25` 继续兼容。 |
| `agg-local-gemma2-27b` | 可以作为对照，不是中文理解和中翻英的优先选择。旧名 `agg-local-gemma2` 继续兼容。 |
| `agg-compare-all` | 同时比较各模型结果，不是单一翻译模型；首次处理重要材料时很有价值。 |

推荐结论：

1. 正式中翻英默认建议：`agg-gemini-3.8-flash`。
2. 质量型备选：`agg-gemini-3.6-flash`。
3. 快速批量初译：`agg-gemini-3.1-flash-lite`。
4. 本地隐私翻译：`agg-local-qwen3.6-27b`。
5. 重要文稿首次选型：先用 `agg-compare-all` 比较，再固定模型。

证据边界：目前没有这些模型使用同一组中英语料进行的完整横向评分。上述模型排序是目录使用建议，不是统一 benchmark 的实测冠军；当前已有的链路验证记录仍需分别参考实际运行结果。

上述结构化信息通过 `GET /api/aggregate/config` 的 `taskGuides.translation.zh_en` 返回。

## 当前任务类型

当前支持的 `taskType`：

| taskType | 典型用途 |
| --- | --- |
| `general.chat` | 普通问答、轻量解释 |
| `reader.explain` | 文献段落解释、原文/译文辅助理解 |
| `reader.translate` | 翻译、术语解释、双语辅助 |
| `reader.summarize` | 段落总结、长文摘要 |
| `code.debug` | 代码解释、报错定位、修复建议 |
| `structured.json` | JSON/schema/字段化输出 |
| `ocr.image_to_markdown` | 图片 OCR、公式和表格转 Markdown |
| `compare.reasoning` | 多模型对比、复杂推理、方案评估 |

如果请求没有显式传入 `taskType`，`task_router` 会尝试从 `metadata.taskType` 或消息文本中做轻量推断。推断失败时默认使用 `general.chat`。

## 路由约束

调用方可以通过 `constraints` 控制路由行为。

| 字段 | 示例 | 作用 |
| --- | --- | --- |
| `prefer` | `quality` | 选择偏好，可选 `quality`、`speed`、`cost`、`privacy`、`balanced` |
| `allowProviders` | `["gemini", "yunwu"]` | 只允许指定 provider |
| `denyProviders` | `["local"]` | 排除指定 provider |
| `preferredProvider` | `gemini` | 给某个 provider 加权，但不强制 |
| `requireProvider` | `gemini` | 强制使用某个 provider |
| `requireLocal` | `true` | 只允许本地 OpenAI-compatible 模型 |
| `requireVision` | `true` | 只允许具备图片能力的模型 |
| `maxCostTier` | `medium` | 排除成本等级高于该值的模型 |
| `preferredModels` | `["gemini:gemini-3.8-flash"]` | 给指定模型加权 |
| `denyModels` | `["local:nomic-embed-text:latest"]` | 排除指定模型 |

示例：

```json
{
  "model": "auto",
  "taskType": "reader.explain",
  "messages": [
    {"role": "user", "content": "请解释这段文献内容"}
  ],
  "constraints": {
    "prefer": "privacy",
    "requireLocal": true
  }
}
```

## 当前评分逻辑

路由器位于 `model_aggregator/services/task_router.py`。

当前打分分为两步：

1. 过滤不可用或不符合约束的模型。
2. 对剩余模型按任务分数和偏好加权排序。

过滤条件包括：

1. provider 是否已配置。
2. chat 任务是否误选了非 chat 模型，例如 Mathpix 或 embedding 模型。
3. 是否满足 `requireLocal`、`requireVision`、`requireProvider`。
4. 是否被 `allowProviders`、`denyProviders`、`denyModels`、`maxCostTier` 排除。

偏好加权规则：

| prefer | 影响 |
| --- | --- |
| `quality` | 给 `qualityTier` 更高的模型加权 |
| `speed` | 给 `speedTier` 更高的模型加权 |
| `cost` | 给 `costTier` 更低的模型加权 |
| `privacy` | 给本地模型加权 |
| `balanced` | 同时考虑质量、速度和成本 |

路由响应中的 `routerDecision` 会返回：

| 字段 | 含义 |
| --- | --- |
| `ok` | 是否成功选出模型 |
| `taskType` | 归一化后的任务类型 |
| `selectedModel` | 最终模型 id |
| `provider` | 最终 provider |
| `model` | provider 内部模型名 |
| `reason` | 可读解释 |
| `constraints` | 实际生效约束 |
| `fallbacks` | 后续候选模型 |
| `candidates` | 排名前几的候选模型 |
| `rejected` | 失败时返回部分被排除模型及原因 |

## Dry-run 接口与前端实验台

除了 `POST /api/aggregate/chat` 的自动选型，这一版还提供两个可直接观察路由行为的入口：

1. `POST /api/aggregate/route`
2. `GET /model-tester.html`

`/api/aggregate/route` 只做选型，不实际调用模型，适合：

1. 调用方在真正发送前先看命中模型。
2. benchmark 程序只验证路由策略本身。
3. 调试约束是否过严，例如 `requireLocal + requireVision + maxCostTier=low` 是否导致无可用模型。

`/model-tester.html` 则把这些能力可视化，允许直接切换：

1. `manual` / `auto` 调用模式。
2. `taskType`、`prefer`、`preferredProvider`、`maxCostTier`。
3. `requireLocal`、`requireVision`。
4. 真实执行与 dry-run 预览两条路径。

## 当前默认能力判断

当前能力画像是保守初始值，不是最终 benchmark 结论。

大致策略：

1. Gemini 3.8 Flash 是中翻英默认建议；Gemini 3.6 Flash 可作为质量型备选，Gemini 3.1 Flash-Lite 适合快速、低成本的批量初译和短段落。
2. 云雾 GPT-5.5 优先用于复杂推理、代码调试和多模型对比基准。
3. 本地 Qwen 类模型优先用于隐私、低成本、可离线的 reader 类任务。
4. Mathpix 只用于图片 OCR / 公式识别，不作为普通 chat 模型。
5. embedding 模型不参与 chat 路由。

后续如果实测结果和这些初始假设冲突，应以本项目 benchmark 和真实调用反馈为准。

## 能力边界

当前 MVP 有几个明确边界：

1. `taskScores` 是人工设定的初始值，尚未由 benchmark 自动生成。
2. `imageCapable` 对本地模型存在启发式判断，必须通过实际图片请求验证。
3. `contextWindow` 只有部分模型有明确值，未知模型暂时为 `null`。
4. `costTier` 是粗粒度等级，不代表真实 token 成本。
5. 路由器目前只做单模型选择，不自动执行多模型并行和结果整合。
6. `fallbacks` 目前主要用于解释候选顺序，尚未实现调用失败后的自动重试切换。

## 后续计划

建议按以下顺序继续推进：

1. 建立小型 benchmark 集，覆盖 reader、翻译、总结、代码、JSON、OCR。
2. 为每个任务记录模型输出质量、延迟、失败率和人工评分。
3. 将 benchmark 结果回写为能力档案或单独的评分数据文件。
4. 增加运行时调用追踪，统计 `taskType`、`resolvedModel`、`latencyMs`、错误类型。
5. 实现失败 fallback：首选模型失败时，按 `routerDecision.fallbacks` 尝试下一个候选。
6. 为调用方暴露更清晰的模型选择说明，例如“为什么选这个模型”和“如果失败会换哪个模型”。

## 与 API 文档的关系

`docs/api.md` 面向调用方，说明如何调用接口。

本文档面向维护者，说明智能分发为什么这样设计、当前能力画像如何解释，以及后续如何校准。
