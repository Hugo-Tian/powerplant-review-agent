# 第 4 步：SQLite 持久化

`demo_api:app` 启动时自动创建项目内 `data/demo.sqlite3`，重启保留数据，不需要数据库服务。设置 `DEMO_DB_PATH` 环境变量可指定其他文件。原 PostgreSQL 数据不受影响。

| 表 | 主要字段 | 用途 |
|---|---|---|
| orders | event_id 主键、title、content、level、order_json、时间 | 最新工单内容 |
| predictions | prediction_id 唯一键、event_id 外键、user_id、score、confidence、push_type、版本、时间、request_json、result_json | 每次推送及完整输入输出快照 |
| feedback | feedback_id 唯一键、prediction_id 外键、action、reviewer、comment、corrected_score、corrected_push_type、时间 | 追加的人工确认/修正记录 |
| users | user_id 主键、name、role、responsible_units、base_profile_json（手工基础兴趣）、时间 | 用户岗位与负责机组；`/predict` 传入显式画像时自动登记 |
| behaviors | behavior_id 唯一键、user_id 外键、action_type、event_id、query_content、stay_sec、tags_json、occurred_at | 行为埋点；未传标签时取关联工单最近一次预测的标签 |
| profiles | user_id 主键、profile_json、behavior_count、computed_at | 画像缓存；1 小时过期，新行为或用户信息修改时立即失效 |

建表 SQL 在 `core/sqlite_store.py`。每条连接开启外键，工单与预测在同一事务保存，失败整体回滚。预测和反馈追加保存，数据库文件已加入 .gitignore。当前保存第 2 步 API 接收的推理字段；原始发生时间、电厂 ID 等额外字段仍保留在模拟 dataset.json 中。

## 启动

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) '.local-deps'
python -m uvicorn demo_api:app --host 127.0.0.1 --port 8000
```

模拟数据导入命令见 `data/synthetic/README.md`。重复导入追加预测历史；以前已退出进程的内存历史无法恢复。

## 反馈接口

Swagger `/docs` 提供 `POST /predictions/{prediction_id}/feedback`，返回 201。prediction_id 取自预测响应或工单列表。

确认：

```json
{"action":"confirm","reviewer":"演示审核人","comment":"已核对"}
```

修正（评分为人工业务判断，不是模型准确率）：

```json
{"action":"correct","reviewer":"演示审核人","comment":"调整本次匹配建议","corrected_score":0.4,"corrected_push_type":"device_group"}
```

修改必须填写理由，并至少提供评分或类型之一。确认不能带修正值。不存在的预测返回 404，非法输入返回 422。

`GET /orders` 新增 `storage: "sqlite"`、每次历史中的 `feedback`、最新预测的 `latest_feedback`，以及展示用 `effective_result`（评分、类型、来源 model/human、状态 pending/confirm/correct）。原 `latest_prediction` 始终是模型结果。

同次预测以最后一条反馈为准，未填写的修正字段沿用原模型值；再次确认表示接受原模型结果。重新预测产生新的待审核结果，旧反馈留在历史。user_id 筛选仅返回对应用户历史，不是身份认证。reviewer 为本地演示手工填写身份。

反馈用于人工调整和追溯，暂不自动训练模型；行为数据会通过画像影响后续评分。Vue 工作台已接入，构建后由后端根路径 `/` 提供页面，使用说明见主 README。

## 验证

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) '.local-deps'
python -m unittest discover -s tests -v
```

测试使用独立临时数据库，验证重建应用后持久读取、确认/修正、原模型输出保留、重新预测待审核、用户历史隔离、非法反馈、事务回滚及全部 320 条模拟工单入库和分页。
