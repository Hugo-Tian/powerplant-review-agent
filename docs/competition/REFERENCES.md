# 参考文档

作品：电厂工单推送审核智能体（智维工作室 · 田贵恒，个人参赛）

## 一、大赛与框架

1. openJiuwen 智能体创新大赛·参赛 FAQ 文档（大赛官方发布）。
2. openJiuwen 官网与文档：https://openjiuwen.com ，https://openjiuwen.com/docs-page
3. openJiuwen agent-core 源码仓库：https://gitcode.com/openJiuwen/agent-core （本作品使用 0.1.19.post3：ReActAgent、LocalFunction、回调、multi_agent HandoffTeam）

## 二、方法

4. Yao S, Zhao J, Yu D, et al. ReAct: Synergizing Reasoning and Acting in Language Models. ICLR 2023. arXiv:2210.03629.（审核智能体的推理—行动循环）
5. Salton G, Buckley C. Term-weighting approaches in automatic text retrieval. Information Processing & Management, 1988, 24(5): 513–523.（TF-IDF 标签提取与相似工单检索）
6. Kraft D. A software package for sequential quadratic programming. DFVLR-FB 88-28, 1988.（SLSQP，按岗位拟合四维权重）
7. Cohen J. A coefficient of agreement for nominal scales. Educational and Psychological Measurement, 1960, 20(1): 37–46.（专工盲评中专工之间一致程度的 kappa 系数）

## 三、行业规定

8. 《电力监控系统安全防护规定》，国家发展和改革委员会令 2014 年第 14 号。（部署位置：管理信息大区，不接入生产控制大区）

## 四、软件与服务

9. Pedregosa F, et al. Scikit-learn: Machine Learning in Python. Journal of Machine Learning Research, 2011, 12: 2825–2830.
10. Virtanen P, et al. SciPy 1.0: Fundamental Algorithms for Scientific Computing in Python. Nature Methods, 2020, 17: 261–272.
11. jieba 中文分词：https://github.com/fxsjy/jieba
12. FastAPI：https://fastapi.tiangolo.com
13. Vue.js：https://vuejs.org
14. SQLite：https://sqlite.org
15. Playwright：https://playwright.dev
16. DeepSeek API 文档：https://api-docs.deepseek.com

第三方软件许可见仓库根目录 `THIRD_PARTY_NOTICES.md`。

## 五、作者既有工作

17. 田贵恒.《电厂工单数据智能推送模型研究与实现》. 本科毕业设计论文, 2026.（标签提取、四维评分 v1、行为画像公式与原系统来源于此，不申报为本次贡献，见《既有基础与新增贡献说明》）

## 六、本作品内的配套文档

| 文档 | 内容 |
|---|---|
| 需求与场景分析 | 用户、痛点、功能与非功能需求、典型场景 |
| 系统架构说明 | 架构图、模块、智能体与护栏、数据流、技术栈 |
| 技术落地可行性方案 | 部署、对接、试点计划、成本、风险 |
| 创意亮点说明 | 八个亮点及其证据 |
| 界面原型与示意 | 实际运行截图与用户路径 |
| 数据来源与合规说明 | 数据来源、评估口径、外部模型调用 |
| 既有基础与新增贡献说明 | 毕设已有内容与大赛期间新增内容的划分 |
| 开发日志 | 按时间记录的改动、问题与修复 |
