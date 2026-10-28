# 第三方依赖声明

本仓库没有拷贝第三方源码；以下组件均通过包管理器（pip / npm）按依赖安装。版本为 2026-10-28 开发环境实际使用的版本。

## Python（后端）

| 组件 | 版本 | 许可证 | 在作品中的作用 |
|---|---|---|---|
| openjiuwen（openJiuwen agent-core） | 0.1.19.post3 | 以 openJiuwen 社区仓库声明为准 | 审核助手智能体的运行框架：ReActAgent 推理-行动循环、工具注册与调度（`core/agent_openjiuwen.py`） |
| FastAPI | 0.162 | MIT | Web API 框架 |
| Uvicorn | 0.54 | BSD-3-Clause | ASGI 服务器 |
| Pydantic | 2.14 | MIT | 请求/响应数据校验 |
| Starlette | 1.10 | BSD-3-Clause | FastAPI 底层 |
| httpx | 0.28 | BSD-3-Clause | 调用大模型 API（内置引擎与工单分析） |
| jieba | 0.42.1 | MIT | 中文分词（标签提取） |
| scikit-learn | 1.6 | BSD-3-Clause | TF-IDF 向量化（标签提取、相似工单） |
| NumPy | 2.1 | BSD-3-Clause | 数值计算 |
| SciPy | 1.18 | BSD-3-Clause | 权重拟合（SLSQP 优化） |

openjiuwen 会连带安装其自身依赖（openai、anthropic、loguru、sqlalchemy 等），由 pip 自动解析，作品代码不直接调用。

## 前端

| 组件 | 版本 | 许可证 | 作用 |
|---|---|---|---|
| Vue | 3.5 | MIT | 前端框架 |
| @fontsource/barlow-semi-condensed | 5.3 | OFL-1.1 | 数字字体（随前端打包，不依赖 Google Fonts） |
| Vite、@vitejs/plugin-vue | 6.4 / 5.2 | MIT | 构建工具（开发依赖） |
| @playwright/test | 1.63 | Apache-2.0 | 浏览器端到端测试（开发依赖） |

## 模型与外部服务

| 名称 | 调用方式 | 作用 |
|---|---|---|
| DeepSeek `deepseek-flash` | HTTPS API（OpenAI 兼容协议），关闭思考模式 | 工单标签提取与等级复核、推送解读、审核助手的推理与工具调用 |

模型权重不包含在仓库中。也可替换为任何 OpenAI 兼容服务（如通义千问、本地 Ollama）或 Anthropic Claude。

## 代码占比

第三方代码在仓库中的占比为 0%（全部为依赖引用）。作品自有代码约 6,300 行（Python / Vue / JS / CSS / 测试），统计方法见 `docs/competition/BASELINE_AND_CONTRIBUTIONS.md`。
