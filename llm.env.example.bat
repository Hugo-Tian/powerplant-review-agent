@echo off
rem Copy this file to llm.env.bat, uncomment ONE provider block and fill in the key.
rem start_demo.bat loads llm.env.bat automatically. llm.env.bat is git-ignored - never share it.
rem Without it the app uses rule + TF-IDF only.

rem --- DeepSeek (deepseek-chat was retired 2026-07-24; thinking off = faster and cheaper) ---
rem set LLM_PROVIDER=openai
rem set LLM_BASE_URL=https://api.deepseek.com
rem set LLM_MODEL=deepseek-flash
rem set LLM_THINKING=disabled
rem set LLM_API_KEY=sk-...

rem --- Qwen via Alibaba Cloud DashScope (OpenAI-compatible mode) ---
rem set LLM_PROVIDER=openai
rem set LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
rem set LLM_MODEL=qwen-plus
rem set LLM_API_KEY=sk-...

rem --- Local Ollama (no key, data stays on this computer) ---
rem set LLM_PROVIDER=openai
rem set LLM_BASE_URL=http://localhost:11434/v1
rem set LLM_MODEL=qwen2.5:7b

rem --- Anthropic Claude (only in supported regions) ---
rem set LLM_PROVIDER=anthropic
rem set LLM_MODEL=claude-haiku-5-5
rem set LLM_API_KEY=sk-ant-...

rem Review agent engine: openjiuwen (needs setup_openjiuwen.bat) or builtin. Empty = openjiuwen if installed.
rem set AGENT_ENGINE=openjiuwen

rem Optional: request timeout in seconds
rem set LLM_TIMEOUT=30
