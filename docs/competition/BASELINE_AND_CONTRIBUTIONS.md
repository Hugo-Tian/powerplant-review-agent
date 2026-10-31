# 既有基础与本次新增贡献说明

依据大赛 FAQ Q40（三）“既有项目参赛规则”：基于既有项目继续开发，须说明既有基础、本次新增内容与新增贡献范围；评审仅认定新增部分的有效工作量。

作者：田贵恒（个人参赛）

## 一、既有基础（参赛前已完成，不申报为本次贡献）

来源：作者本科毕业设计《电厂工单数据智能推送模型研究与实现》，2025 年 12 月开始，2026 年 5 月提交。**该论文已公开发表**，论文内容对应下表的“既有基础”，不申报为本次贡献。本次新增的审核智能体、大模型工单理解、相似工单、反馈学习、评分 v2 等内容（见第二部分）均在大赛期间完成，未出现在论文中。

| 既有内容 | 位置 |
|---|---|
| 规则词典 + TF-IDF 的工单标签提取 | `core/nlp.py` |
| 四维加权匹配评分 v1（设备 / 行为 / 岗位 / 厂家，紧急保底 0.75，厂家加分） | `core/matching.py` 的原始版本 |
| 行为画像公式（动作权重 × 停留时长 × e^(−λΔt)） | `_legacy/modules/profile/`，移植到 `core/profile_builder.py` |
| React + PostgreSQL + APScheduler 原系统 | `_legacy/`（已归档，仅保留作对照；`EventCreate` 字段定义仍被测试引用） |
| Vue 3 + FastAPI + SQLite 本地演示工作台（工单导入、评分、人工确认/修改、历史留存） | `demo_api.py`、`core/sqlite_store.py`、`frontend-vue/` 的基础部分 |
| 320 条模拟工单与 3 个虚构岗位画像（固定种子生成器） | `data/synthetic/`、`scripts/generate_demo_data.py` |

## 二、本次新增（大赛期间，2026 年 10 月起）

核心是把一个“规则打分 + 人工逐条确认”的推荐系统，升级为“大模型理解工单 + 审核智能体自主调查 + 人机协同反馈学习”的 Agent 应用。

| 新增内容 | 位置 | 说明 |
|---|---|---|
| **审核助手智能体（openJiuwen ReActAgent）** | `core/agent_openjiuwen.py` | 基于 openJiuwen agent-core 的 ReActAgent：模型自主规划调查路线，调用 7 个只读工具 + 提交结论工具；工具以 openJiuwen `LocalFunction` 注册；通过 `AFTER_MODEL_CALL` 回调记录推理过程 |
| 审核工具集与结论护栏 | `core/agent.py` | 7 个只读工具（工单、评分构成、画像、相似工单、同机组工单、本人审核历史、假设试算）；证据必须来自本次调用过的工具，数字必须能在工具返回中找到，矛盾结论自动降级为“需人工判断”；步数预算；完整过程留档 |
| 大模型工单理解 | `core/llm.py` | 标签代码白名单、原文片段引用校验、等级只升不降、新词进入候选不参与评分、失败自动降级、结果缓存；兼容 OpenAI 协议与 Anthropic 协议 |
| 相似历史工单检索 | `core/similar.py` | 字符 n-gram TF-IDF × 0.7 + 标签 Jaccard × 0.3，区分本人与其他岗位的人工结论 |
| 重点审核分流 | `core/inference.py`、`demo_api.py` | 灰区、大模型上调等级、新设备、调用失败、本人对相似工单的修正等触发条件 |
| 反馈学习 | `core/learning.py` | 四维权重拟合（SLSQP，按岗位）、画像调整建议、一致性指标、调整前后对比；所有调整须人工批准 |
| 评分 v2 与岗位专属权重 | `core/matching.py`、`demo_api.py` | 修正“负责机组的无关工单带固定底分”的缺陷；权重按岗位存储 |
| 画像饱和函数 | `core/profile_builder.py` | 1 − e^(−w/8) 代替最大值归一化（原做法两次点击即把兴趣拉满） |
| 模拟审核员 | `scripts/simulate_review.py` | 按岗位职责规则自动审核，用于在没有真实审核数据时检验流程，可撤销 |
| 工作台重设计 | `frontend-vue/` | 控制室风格界面、评分仪表盘、审核助手面板、批量预审、学习与评估页 |
| 测试 | `tests/test_llm.py`、`tests/test_steps345.py`、`tests/test_agent.py`、`tests/test_agent_openjiuwen.py` 等 | 含用本地假模型服务驱动 openJiuwen ReActAgent 的端到端测试 |

代码量参考（2026-10-28，`wc -l`，不含第三方依赖与 `_legacy/`）：全部自有代码约 6,300 行，其中新增的 Agent / 大模型 / 学习相关核心模块约 1,600 行。仓库内没有拷贝任何第三方源码，第三方库仅以依赖方式引入（见 `THIRD_PARTY_NOTICES.md`）。

## 三、开发过程证明

- 开发日志：`docs/competition/DEVLOG.md`（按时间记录每一步的改动、发现的问题和修复）。
- Git 提交历史：仓库于 2026-10-28 初始化。此前的迭代没有版本库记录，首个提交如实标注为“当前快照”，之后每项改动单独提交。**不补造历史提交。**
- 测试用例演化：`tests/` 下各文件对应各阶段新增功能。
