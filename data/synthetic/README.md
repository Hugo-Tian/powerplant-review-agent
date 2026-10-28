# 模拟工单数据（第 3 步）

本目录全部工单、机组、型号和用户画像均为人工生成的演示数据，不来自真实电厂运行记录。厂家名称仅用于匹配原有 NLP 词典，不表示相关厂商发生过这些事件。设备异常与处理描述是程序场景文案，不是操作规程。

## 文件

- `dataset.json`：320 条工单、3 个虚构岗位画像，以及电厂、机组、设备类型、厂家和型号字典。每条工单字段与原 `EventCreate` 完全一致，模拟标识写入工单号、标题、内容和文件元数据。
- `predict_requests.json`：同一批工单转换成 `/predict` 请求，默认使用虚构汽轮机专工画像。数组中的每个对象均可单独提交；接口不接收整个数组。
- `../../scripts/generate_demo_data.py`：固定种子的生成器与 `to_predict_request` 字段转换函数。

字段包括 event_no、plant_id、unit_id、device_type_id、manufacturer_id、model_id、kks_code、title、content、level、event_type、occurred_at。整数外键只对应 dataset.json 内的 catalogs，不能直接写入已有数据库。发生时间从 2026-08-01 起每 2 小时一条，固定时间用于可复现演示，不适合原旧服务的“近日工单”过滤条件。

## 场景与边界

覆盖汽轮机、发电机、锅炉、变压器、给水泵、循环水泵、励磁系统、DCS，以及一般、重要、紧急、建议四种等级。设备与故障场景成组生成，附带缺厂家、缺机组及待补充工单，展示信息不完整时的结果。

三个画像分别为汽轮机、电气和锅炉专工，兴趣权重是明确设定的演示输入，未从真实行为学习。同一工单切换画像可观察个性化评分差异；紧急工单体现原算法保底规则，待补充工单不应凭空得到高匹配分。这些场景检查不是准确率、召回率或模型泛化能力评估。数据不含预置预测分数、真实标签或伪造评估指标。

## 重新生成与验证

在项目根目录运行，命令只覆盖本目录下两个生成 JSON，不访问数据库：

```powershell
python -m scripts.generate_demo_data --count 320 --seed 20260909
$env:PYTHONPATH = Join-Path (Get-Location) '.local-deps'
python -m unittest discover -s tests -v
```

原始行用 `EventCreate` 校验；转换后的全部 320 条请求通过测试客户端实际执行预测，并检查列表读取、分数范围、紧急保底及岗位差异。测试使用独立临时 SQLite 文件，不会写入你正在运行的服务。

## 导入正在运行的第 2 步 API

先按 `docs/api.md` 启动服务，再在项目目录的 PowerShell 中执行：

```powershell
$demoRequests = Get-Content -Raw -Encoding UTF8 'data/synthetic/predict_requests.json' | ConvertFrom-Json
foreach ($demoRequest in $demoRequests) {
    $demoJson = $demoRequest | ConvertTo-Json -Depth 10 -Compress
    Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/predict' -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($demoJson)) | Out-Null
}
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/orders?limit=5'
```

导入会计算推送结果；重复执行会追加历史。第 4 步已接入 SQLite，重启 API 后数据保留，详见 `docs/sqlite.md`。
