# 旧版代码归档（不再维护）

这里是统一主线之前的 React + PostgreSQL + APScheduler 版本，仅供对照和论文引用，不再开发。当前主线是项目根目录的 Vue + FastAPI（`demo_api.py`）+ SQLite。

| 文件 | 原用途 | 在新主线中的对应 |
|---|---|---|
| `main.py`、`tasks.py` | PostgreSQL 版 FastAPI 入口，每日 06:30 标签提取、07:00 推送定时任务 | `demo_api.py`；定时推送改为 `POST /push/run` 手动触发 |
| `modules/events/` | 工单录入与标签提取 | `POST /predict`（`core/nlp.py` 提取） |
| `modules/behavior/` | 行为埋点 | `POST /behaviors`、`GET /users/{id}/behaviors` |
| `modules/profile/` | 画像构建 ProfileBuilder | `core/profile_builder.py`、`GET /users/{id}/profile` |
| `modules/push/` | 推送列表、反馈、调度 | `GET /orders`、`POST /predictions/{id}/feedback`、`POST /push/run` |
| `nlp_extractor.py` | 带数据库读写的 NLP 服务 | `core/nlp.py`（无数据库版本） |
| `frontend/` | React + Ant Design 前端 | `frontend-vue/` |
| `schema.sql`、`seed_data.sql`、`demo_data.sql`、`*.bat`、`docker-compose.yml`、`Dockerfile`、`requirements.txt` | PostgreSQL 建表、数据和 Docker 部署 | SQLite 自动建表（`core/sqlite_store.py`），`requirements-demo.txt` |
| `legacy-readme.md` | 旧版使用说明 | — |

旧版依赖根目录的 `core/config.py`、`core/database.py`、`core/matching.py`、`core/inference_types.py`。如需运行，在项目根目录把 `_legacy` 和根目录都加入 `PYTHONPATH`，再按 `legacy-readme.md` 启动 PostgreSQL（Docker 文件中的相对路径可能需要调整）。

`modules/events/schemas.py` 里的 `EventCreate` 仍被 `tests/test_synthetic_data.py` 用来校验模拟工单字段。
