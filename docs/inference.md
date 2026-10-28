# 第 1 步：独立推理接口

当前代码是标签提取与用户画像驱动的加权推荐系统。没有发现监督训练脚本、训练权重文件或可验证的评估结果。TF-IDF 使用内置领域语料拟合，旧数据库服务还会读取近期工单重新拟合；这不是监督学习的效果评估。

## 输入与输出

原始创建字段见 `modules/events/schemas.py`：event_no、plant_id、unit_id、device_type_id、manufacturer_id、model_id、kks_code、title、content、level、event_type、occurred_at。

独立推理的 `WorkOrder` 接收 event_id、title、content、level，以及可选 unit_no、device_type_name、manufacturer_name、model_code、kks_code、event_type。数据库 ID 需要由调用方解析为名称/机组编号；发生时间、电厂编号及工单号不直接参与现有评分。旧调度器另有时间窗口和关闭状态过滤。

个性化推送还需要显式传入 `UserProfile`：用户 ID、岗位、负责机组以及设备、厂家、故障、关键词兴趣权重。不能仅靠工单原文推断真实用户偏好。已有标签可通过 `predict(..., tags=[...])` 传入，每项包含 code、name、category、confidence。

输出包括 event_id、user_id、score、breakdown、push_reasons、push_type、tags、inference_mode、model_version；rank 另加从 1 开始的排名，同分保持输入顺序。默认不做阈值过滤，可显式传 threshold 和 limit。

保留原有四维权重 0.35/0.30/0.20/0.15、同厂家加成及紧急工单 0.75 保底。这些是算法配置，不是评估指标。confidence 返回 null：原实现没有校准后的预测概率，标签 confidence 也只是启发式权重。

## 调用

在项目根目录运行：

```python
from core.inference import PushPredictor, UserProfile, WorkOrder

profile = UserProfile(
    user_id="demo", role="汽轮机专工", responsible_units=["#1"],
    device_interests={"TURBINE": 1.0}, mfr_interests={},
    fault_interests={}, keyword_interests={}, personal_tags=[],
)
predictor = PushPredictor()  # 服务生命周期内复用；初始化一次 TF-IDF
result = predictor.predict(
    WorkOrder("demo-order", "汽轮机振动超标", "安排轴承检查", "紧急", "#1"),
    profile,
)
print(result)
```

文本模式需要 requirements.txt 中的 jieba 和 scikit-learn。已提取标签时可用 `PushPredictor(text_enabled=False)`，评分路径仅使用标准库。

## 拆分边界及兼容性

- `core/inference_types.py`：画像结构。
- `core/matching.py`：原评分实现，公式不变。
- `core/nlp.py`：原标签提取与融合组件。
- `core/inference.py`：独立预测与排序入口，无持久化、定时任务、网络请求或预测时拟合。

旧 profile/push service 及 nlp_extractor 保留导入兼容和数据库功能。独立文本模式仅使用内置语料和规则 + TF-IDF，因此结果不保证与使用数据库扩充语料或 LLM 的历史结果一致。未删除实际参与运行的 TF-IDF 初始化、画像计算或后台任务；没有发现可直接删除的一次性实验脚本。

验证：`python -m unittest discover -s tests -v`。这些是功能验证，不代表模型准确率。

本次在当前 Python 下使用项目内 `.local-deps` 补齐依赖，4 项测试及旧模块导入兼容检查通过。复现时先在 PowerShell 设置 `$env:PYTHONPATH = Join-Path (Get-Location) '.local-deps'`，再执行测试命令。现有 `.venv` 指向不存在的 Python，需要在后续本地启动配置时重建。本步未启动数据库或重建 Docker 容器，未验证完整旧服务运行。
