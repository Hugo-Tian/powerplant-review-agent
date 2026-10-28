# 第 2 步：本地演示 API

入口为 `demo_api:app`，不需要 PostgreSQL、定时任务或外部 LLM。旧 `main:app` 仍是原应用入口。第 4 步已接入 SQLite，默认保存至 `data/demo.sqlite3`，重启保留数据，详见 `sqlite.md`。

## 启动

在 `power-plant-final` 项目目录执行（当前已补齐 `.local-deps`）：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) '.local-deps'
python -m uvicorn demo_api:app --host 127.0.0.1 --port 8000
```

其他环境可创建有效虚拟环境后安装 `requirements-demo.txt`，无需设置上述 PYTHONPATH。当前仓库原 `.venv` 已失效。

打开 http://127.0.0.1:8000/docs，在 POST /predict 中点击 Try it out，输入下面的演示请求。OpenAPI JSON 位于 `/openapi.json`。Swagger UI 默认需要联网加载其 JS/CSS。

```json
{
  "order": {
    "event_id": "demo-001",
    "title": "汽轮机振动超标",
    "content": "东方汽轮机轴承振动异常，安排检查",
    "level": "紧急",
    "unit_no": "#1"
  },
  "profile": {
    "user_id": "demo-user",
    "role": "汽轮机专工",
    "responsible_units": ["#1"],
    "device_interests": {"TURBINE": 1.0}
  }
}
```

此请求是人工构造的接口示例，画像权重是输入配置，不是评估数据。模型需要目标用户画像才能计算个性化匹配分。

## 接口行为

- `POST /predict`：接收 `order`、`profile`，可选 `weights`。返回推送分数、四维明细、理由、推送类型、提取标签、预测 ID 和时间。`confidence` 为 null，并说明尚未校准概率。每次成功请求追加一条历史，重复提交同一 event_id 不新增工单。
- `GET /orders`：返回 `items`、`total`、`offset`、`limit` 和 `storage: "sqlite"`。每条包含工单、最新结果、历史快照、人工反馈及当前有效结果。支持 `user_id` 筛选、`offset` 和 `limit` 分页，按预测写入顺序倒序。未调用预测前列表为空。
- 非法等级、空标题、超出 0～1 的兴趣值、不归一的权重及非法分页返回 422；校验失败不会写入历史。

原始数据库编号需由调用方转换为推理用的设备名称、厂家名称和机组号，字段映射见 `inference.md`。同一工单再次预测时可提交修改后的内容，历史保留每次输入。第 4 步已提供 `POST /predictions/{prediction_id}/feedback`，详见 `sqlite.md`。

## 验证

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) '.local-deps'
python -m unittest discover -s tests -v
```

测试覆盖原推理规则、原文预测、重复预测历史、用户筛选、分页、输入校验及 Swagger/OpenAPI 路由。这是功能测试，不是模型效果评估。

## 用户、行为与画像（主线统一后新增）

| 接口 | 说明 |
|---|---|
| `GET /users` / `GET /users/{id}` | 用户列表 / 单个用户 |
| `POST /users` | 登记用户；已存在则原样返回，不覆盖 |
| `PUT /users/{id}` | 创建或更新岗位、负责机组、基础兴趣，画像缓存随之失效 |
| `POST /behaviors` | 上报行为，`action_type` 取 query/detail/export/download/share/print/like；传 `event_id` 不传 `tags` 时自动取该工单标签 |
| `GET /users/{id}/behaviors?days=30&limit=200` | 近 N 天行为 |
| `GET /users/{id}/profile` | 画像（1 小时缓存，返回 `cached`、`behavior_count`） |
| `POST /users/{id}/profile/rebuild` | 立即重算画像 |
| `POST /push/run` | 请求体 `{"user_id": 可选, "threshold": 可选}`；重算画像并对全部已存工单重新评分，结果未变化的不新增历史 |

`POST /predict` 现在接受 `{"order": ..., "profile": ...}`（与原来一致）或 `{"order": ..., "user_id": "..."}`，二者只能选一。

画像公式（`core/profile_builder.py`，移植自旧版 `ProfileBuilder`）：单条行为权重 = 动作权重 ×（1 + ln(停留秒数+1)/10，仅 detail）× e^(-0.05·距今天数)；按标签累加后用饱和函数 1 − e^(−累计权重/8) 换算为兴趣（两次查看详情约 0.39，十次约 0.92，不会到 1.0；旧版按最大值归一化会让一两次点击就把兴趣拉满），再与用户基础兴趣取较大值；岗位职责设备至少 0.3。只统计近 30 天行为。

## 大模型工单理解（第 2 步新增）

`/predict` 与 `/push/run` 的结果新增两个字段：

- `effective_level`：实际参与评分的等级。大模型复核只会上调（建议 < 一般 < 重要 < 紧急），上调时 `push_reasons` 第一条写明原文依据。
- `analysis`：`status`（ok / disabled / error）、`level_review`、`new_terms`（词表外新词，不参与评分）、`dropped`（被拦截的模型输出及原因）、`model`、`cached`、`duration_ms`、`error`。

`inference_mode` 为 `rule_tfidf_llm` 表示大模型结果已与规则、TF-IDF 融合（权重 0.4 / 0.5 / 0.6，沿用论文融合公式）。

| 接口 | 说明 |
|---|---|
| `GET /llm/status` | 是否启用、服务商、模型、接口地址、提示词版本、缓存条数（不返回密钥） |
| `GET /terms/candidates?status=pending` | 词表外新词，按出现工单数排序 |

## 相似工单、AI 解读、重点审核（第 3、4 步）

预测结果新增 `similar`（最多 3 条相似工单，含 `similarity`、`text_similarity`、`tag_overlap`、`shared_tags`、`human_outcome`）和 `triage`（`needs_review` 与 `reasons`）。标签新增 `llm` 字段表示大模型是否参与识别。

| 接口 | 说明 |
|---|---|
| `GET /orders/{event_id}/similar?k=5` | 实时检索相似工单 |
| `POST /predictions/{prediction_id}/explain` | 大模型推送解读：`explanation`、`key_points`、`cited_similar`；未启用时 `status: disabled` |

## 反馈学习与评估（第 5 步）

| 接口 | 说明 |
|---|---|
| `GET /metrics/feedback` | 已审核数、直接确认率、平均分差（MAE）、推送判断一致率、重点审核召回率、按推理模式的 MAE |
| `GET /learning/weights?role=` | 当前生效权重、来源（role 岗位专属 / learned 全局学习 / default 默认）、修改历史 |
| `POST /learning/weights/suggest` | 用审核结果拟合权重（非负、和为 1、单项不超过 0.7，排除紧急保底工单，至少 10 条） |
| `PUT /learning/weights` | `{"weights": {...}, "reviewer": "...", "note": "...", "role": "可选"}` 批准并生效；带 role 只对该岗位生效 |
| `DELETE /learning/weights?reviewer=...&role=` | 全局恢复默认权重；带 role 则该岗位改回使用全局权重 |
| `POST /learning/profile-suggestions` | 同一用户、同一标签的工单被人工下调或上调至少 2 次时，建议调整该兴趣 0.2；启用大模型时附 `review` 复盘 |
| `POST /learning/profile-suggestions/apply` | 批准选中的调整，写入用户基础兴趣 |
| `PATCH /terms/candidates/{term}` | `{"category", "status": "accepted|rejected|pending", "reviewer", "code"}`；接受后立即加入规则词典 |
| `GET /vocabulary` | 当前词表 |

这些指标以人工审核为参照，只覆盖被审核过的推送，不等同于独立标注测试集上的准确率和召回率。

## 评分公式 v2（模型升级）

- **岗位维度**：工单在负责机组时，只有设备属于本岗位职责（设备兴趣 ≥ 0.3，含岗位兜底设备）或为紧急等级才得 1.0；设备无关时得 0.3。不在负责机组但设备兴趣 > 0.6 时仍为 0.7。`model_version` 为 `weighted-matching-v2`。
- **岗位专属权重**：每个岗位可以单独设置四维权重，优先级为岗位专属 > 全局学习 > 默认。权重建议会用最新一次预测的评分明细重新拟合，人工目标分保持不变。

## 审核助手 Agent

| 接口 | 说明 |
|---|---|
| `POST /predictions/{prediction_id}/agent-review` | 运行一次调查，返回结论与完整过程，并留档 |
| `GET /predictions/{prediction_id}/agent-review` | 读取最近一次调查 |
| `POST /agent/review-focus` | `{"user_id", "limit"}`：依次预审该用户待确认、尚未调查过的重点审核工单 |
| `GET /agent/stats` | 调查次数与建议分布 |

调查结果字段：`status`（ok / incomplete / error / disabled）、`recommendation`（push / no_push / needs_human）、`suggested_score`、`confidence`、`summary`、`evidence`（`tool`、`fact`，以及可选的 `unverified` 数字列表）、`dropped_evidence`、`notes`、`steps`（每步的工具、参数、结果摘要、模型当时的说明）、`tool_calls`、`duration_ms`、`model`。

约束：工具全部只读，`what_if` 只做试算；最多 8 次工具调用；证据必须来自本次调用过的工具，证据中的数字必须出现在该工具的返回结果中；没有有效证据、全部证据未核实、或建议与建议分数矛盾时，降级为 needs_human。`/orders` 的每条记录附带 `agent_review` 摘要。
