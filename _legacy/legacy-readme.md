# 电厂工单智能推送系统 — 运行指南

## 项目结构

```
power-plant-final/
├── index.html          ← 前端（直接用浏览器打开）
├── main.py             ← FastAPI 主服务
├── nlp_extractor.py    ← NLP 标签提取（已修复 BUG-3、BUG-4）
├── push_engine.py      ← 推送引擎（已修复 BUG-1、BUG-2）
├── schema.sql          ← 数据库建表 SQL
├── requirements.txt    ← 锁定版本的依赖
├── Dockerfile
└── docker-compose.yml
```

---

## Bug 修复说明

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| BUG-1 | push_engine.py | `MatchingEngine.score()` 方法体里用了 `event_id` 变量，但签名里没有这个参数，运行必定 `NameError` | 签名加入 `event_id: str` 参数 |
| BUG-2 | push_engine.py | 调用 `score()` 后又手动 `mr.event_id = ev["id"]` 覆盖，冗余且逻辑混乱 | 直接在 `score()` 调用时传入 `ev["id"]`，删除覆盖 |
| BUG-3 | nlp_extractor.py | `INSERT INTO nlp_extract_jobs` 用了 `ON CONFLICT DO NOTHING`，但该表只有 BIGSERIAL 主键，无 UNIQUE 约束，PostgreSQL 报语法错误 | 改为普通 INSERT |
| BUG-4 | nlp_extractor.py | 调用 Anthropic API 未传 `x-api-key` 和 `anthropic-version` 请求头，每次都 401 | 从环境变量读取 key 并加入请求头 |
| BUG-5 | requirements.txt | 未锁定版本号 | 固定所有版本 |
| 前端 | index.html | 所有数据硬编码，无 API 调用 | 全部改为 `fetch` 对接后端 |

---

## 方式一：Docker 一键启动（推荐）

### 前提条件
- 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)

### 步骤

**1. 进入项目目录**
```bash
cd power-plant-final
```

**2. 设置 Anthropic API Key（用于 LLM 标签提取，可选）**

在 docker-compose.yml 的 `api` 服务 `environment` 下加一行：
```yaml
environment:
  DATABASE_URL: postgresql://ims_user:change_me_local_only@db:5432/power_plant_ims
  ANTHROPIC_API_KEY: sk-ant-xxxxxxxx   # ← 加这行
```
不填写则自动降级为纯规则引擎，系统照常运行。

**3. 启动所有服务**
```bash
docker compose up -d
```
等待约 30 秒（首次需拉取镜像）。

**4. 检查后端是否就绪**
```bash
curl http://localhost:8000/health
# 返回 {"status":"ok",...} 即成功
```

**5. 打开前端**

用浏览器打开 `index.html` 文件（直接双击，或：）
```bash
# macOS
open index.html
# Windows
start index.html
# Linux
xdg-open index.html
```

**6. 初始化测试数据**

数据库刚创建是空的，需要插入种子数据才能看到推送效果：

```bash
# 进入数据库
docker exec -it power-plant-final-db-1 psql -U ims_user -d power_plant_ims

# 查看已有数据
SELECT COUNT(*) FROM events;
SELECT COUNT(*) FROM users;
```

插入测试用户（复制到 psql 执行）：
```sql
-- 插入测试电厂
INSERT INTO plants (code, name, location, capacity_mw)
VALUES ('PLANT_01', '测试电厂一号', '广东省', 1320.00);

-- 插入机组
INSERT INTO units (plant_id, unit_no, capacity_mw)
VALUES (1, '#1', 660.00), (1, '#2', 660.00);

-- 插入测试用户（UUID 需和 index.html 中的 CURRENT_USER_ID 一致）
INSERT INTO users (id, emp_no, name, role, plant_id, responsible_units, push_enabled)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'EMP-0001', '张明', '汽轮机专工', 1,
  '["#1","#2"]', true
);

-- 插入设备类型（已有种子数据，跳过）
-- 插入一条测试事件
INSERT INTO events (event_no, plant_id, unit_id, title, content, level, occurred_at)
VALUES (
  'EVT-' || TO_CHAR(NOW(), 'YYYYMMDD') || '-001',
  1, 1,
  '#1机汽轮机高压缸效率下降报警',
  '高压缸效率从92.1%下降至88.3%，热电偶T-101显示金属温差异常，建议检查轴封系统及隔板汽封。东方汽轮机N660型。',
  '紧急',
  NOW()
);
```

**7. 触发推送计算**

回到浏览器，点击右上角「重新匹配」按钮，或在推送配置页点击「手动触发今日推送计算」。

---

## 方式二：本地直接运行（不用 Docker）

### 前提条件
- Python 3.11+
- PostgreSQL 15+（本地已安装并运行）

### 步骤

**1. 创建数据库**
```bash
psql -U postgres -c "CREATE DATABASE power_plant_ims;"
psql -U postgres -c "CREATE USER ims_user WITH PASSWORD 'change_me_local_only';"
psql -U postgres -c "GRANT ALL ON DATABASE power_plant_ims TO ims_user;"
psql -U ims_user -d power_plant_ims -f schema.sql
```

**2. 安装依赖**
```bash
pip install -r requirements.txt
```

**3. 设置环境变量**

macOS/Linux：
```bash
export DATABASE_URL="postgresql://ims_user:change_me_local_only@localhost:5432/power_plant_ims"
export ANTHROPIC_API_KEY="sk-ant-xxxxxxxx"  # 可选
```

Windows（PowerShell）：
```powershell
$env:DATABASE_URL = "postgresql://ims_user:change_me_local_only@localhost:5432/power_plant_ims"
$env:ANTHROPIC_API_KEY = "sk-ant-xxxxxxxx"  # 可选
```

**4. 启动后端**
```bash
uvicorn main:app --reload --port 8000
```
看到 `Application startup complete` 即成功。

**5. 打开前端**
```bash
open index.html
```

---

## 常用 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/events` | 新建事件（自动触发NLP） |
| GET | `/api/events` | 事件列表（支持筛选） |
| GET | `/api/events/{id}/tags` | 查看事件NLP标签 |
| POST | `/api/events/{id}/extract-tags` | 手动触发NLP提取 |
| POST | `/api/behaviors` | 上报用户行为 |
| GET | `/api/users/{id}/behaviors` | 查询行为记录 |
| GET | `/api/users/{id}/profile` | 获取用户画像 |
| GET | `/api/users/{id}/push` | 今日推送列表 |
| PATCH | `/api/push/{id}/read` | 标记已读 |
| PATCH | `/api/push/{id}/feedback` | 提交反馈 |
| POST | `/api/admin/run-daily-push` | 手动触发推送计算 |

完整 API 文档（Swagger）：http://localhost:8000/docs

---

## 前端 index.html 配置

打开 index.html，找到文件顶部 `<script>` 中：

```js
const API_BASE = 'http://localhost:8000';        // ← 修改为你的后端地址
const CURRENT_USER_ID = '00000000-0000-0000-0000-000000000001'; // ← 修改为真实用户 UUID
```

---

## 停止服务

```bash
docker compose down        # 停止并保留数据
docker compose down -v     # 停止并清空数据库
```
