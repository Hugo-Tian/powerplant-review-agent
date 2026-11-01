# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project Overview

电厂运维工单数据智能推送系统 — extracts NLP tags from work orders, builds user interest profiles from behavior data, and scores each order per user with a 4-dimension weighted engine. A human reviewer confirms or corrects each push.

**The only maintained stack is Vue 3 + FastAPI (`demo_api.py`) + SQLite.** The old React + PostgreSQL + APScheduler app lives in `_legacy/` for reference only — do not add features there.

## Running

```powershell
# backend (Windows, using bundled deps)
$env:PYTHONPATH = Join-Path (Get-Location) '.local-deps'
python -m uvicorn demo_api:app --host 127.0.0.1 --port 8000
# or: pip install -r requirements-demo.txt in a fresh venv
```

- App: http://127.0.0.1:8000 (serves `frontend-vue/dist`), Swagger: `/docs`
- DB: `data/demo.sqlite3` (override with `DEMO_DB_PATH`), created automatically
- Frontend dev: `cd frontend-vue && npm run dev` (proxies `/api` to :8000). Rebuild (`npm run build`) after Vue changes.

## Tests

```powershell
python -m unittest discover -s tests -v          # backend (openJiuwen tests skip without openjiuwen)
cd frontend-vue; npm run build; npm run test:e2e  # Playwright, port 8766, temp DB
```

## Architecture

```
demo_api.py              FastAPI app factory create_app(db_path); all routes, pydantic I/O models
core/
  inference.py           PushPredictor: WorkOrder + UserProfile -> scored result (no DB; network only via optional analyzer)
  matching.py            MatchingEngine: 4-dim weighted score, emergency floor 0.75, mfr bonus
  nlp.py                 RuleExtractor + TFIDFExtractor + TagFusionEngine (+ legacy async LLMExtractor, unused)
  llm.py                 OrderAnalyzer: LLM tags + level review, whitelist/span validation, cache, fallback
  profile_builder.py     build_profile(user, behaviors): behavior log -> UserProfile (pure)
  similar.py             SimilarityIndex: char 2-3gram TF-IDF (0.7) + tag Jaccard (0.3), rebuilt when orders change
  learning.py            fit_weights (SLSQP, sum=1), profile_suggestions, feedback_metrics — suggestions only
  inference_types.py     UserProfile dataclass
  sqlite_store.py        SQLiteOrderStore: schema + all SQL
  config.py, database.py legacy-only (asyncpg); not imported by demo_api
frontend-vue/src/        App.vue (workbench), components/LearningView.vue, components/ScoreGauge.vue, api.js, style.css (design tokens on :root)
data/synthetic/          320 synthetic orders + 3 fictional role profiles (seeded generator in scripts/)
_legacy/                 archived PostgreSQL/React app
```

### Key rules

- Routes are registered both at `/` and `/api` (the latter hidden from schema).
- `POST /predict` takes either an explicit `profile` (user auto-registered, interests become the base floor) or `user_id` (uses stored behavior profile) — exactly one.
- Each prediction is appended (history kept); a new prediction resets review status to pending. Feedback never overwrites model output.
- Profiles: cached in `profiles`, TTL 1 h, invalidated on new behavior or user update. Formula: action weight × dwell factor × e^(-0.05·days), last 30 days, summed per tag and mapped with 1 − e^(−w/8) (NOT max-normalised: that made two clicks = 1.0), merged with base via max, role-device fallback 0.3.
- `POST /push/run` replaces the old daily cron: rebuild profile(s) and rescore all stored orders; unchanged results are not re-saved.
- Scores are match scores, not probabilities; `confidence` stays null.
- Matching v2 (`core/matching.py`): role dimension = 1.0 for own unit only if a device tag has interest ≥ 0.3 or level 紧急; own unit but unrelated device = 0.3; other unit + strong device interest = 0.7.
- Weights: per-role setting `weights:role:<role>` > global `weights` > default. `/learning/weights*` take `role`; `suggest` re-bases reviewed samples onto the latest prediction breakdown (`learning.rebase`) while keeping the human target.
- LLM step (`core/llm.py`): codes must exist in the rule dictionaries, every tag/term/upgrade must quote a span present in the text, level review can only raise severity. Out-of-vocabulary terms go to `term_candidates` and never affect scoring. Disabled/failed -> rule + TF-IDF. Results cached in `llm_cache` keyed by prompt version + model + text + level; bump `PROMPT_VERSION` when changing the prompt.
- Every prediction result carries `triage` {needs_review, reasons} (gray zone 0.4–0.6, LLM upgrade/new device/new terms/error, similar order corrected) and `similar` (top 3 with human outcome). Tags carry `llm: bool`.
- Learning endpoints never change the system on their own: `/learning/weights` PUT, `/learning/profile-suggestions/apply`, `PATCH /terms/candidates/{term}` are the explicit approval steps. Approved weights live in `settings` and are the default for `/predict` and `/push/run` when the request has no `weights`.
- Frontend design: control-room palette (cabinet grey, ink, safety amber/red/green), Barlow Semi Condensed for numbers (bundled via @fontsource, no Google Fonts — blocked in mainland China). The score gauge with the hatched 0.4–0.6 gray zone is the signature element; keep other UI quiet.
- Review agent team (`core/agent_team.py`, `AGENT_ENGINE=openjiuwen_team` or `team`): openJiuwen `HandoffTeam` of three ReActAgents — 理解 (devices from the whitelist with a quoted span, actual level, who should receive the order via `list_recipients`) → 调查 (the 7 tools + `get_understanding`, `submit_conclusion`) → 复核 (`get_investigation` + read-only tools, `submit_review` agree/challenge; one send-back). Agents hand off with the injected `transfer_to_<id>` tools; agent ids carry a per-run suffix because openJiuwen registers tools globally by agent id. The final result is synthesized in code (`synthesize`): `validate_conclusion` on the latest investigation, downgraded to needs_human if the last review still challenges; plus `understanding` and `dispatch` {missed, extra} (possible missed / extra pushes vs current scores).
- Push policy (`core/policy.py`): role → core/related devices and qualitative push rules; `simulate_review.judge_devices` uses it for target scores, agents read the text version via the `get_push_policy` tool (no target scores in it).
- Component knowledge base (`data/knowledge/components.json`, `core/knowledge.py`): plant components/aliases → system, device code, responsible roles. `rule_safe` names are loaded into the device dictionary at app start via `add_term` (author-approved synonyms); ambiguous names are only for the agents' `lookup_component` tool and for triage hints. Hard-case sets: `hard_cases.json` (main, prompts were tuned on it), `hard_cases_holdout.json` (written before v2), `hard_cases_holdout2.json` (written after the knowledge base, before wiring it in; `kb_covered` per case). Report the sets separately.
- Triage text checks (`core/inference.py: text_doubts`, only when the order text is available): no device recognised, structured device field not mentioned in title/content, device word only used as a place (汽机房, 主变区域).
- Hard-case evaluation: `data/synthetic/hard_cases.json` (23 deliberately difficult synthetic orders with true devices/level) and `scripts/eval_hard_cases.py` (temp DB copy; reference = `simulate_review.judge_devices` on the true devices; `--agent openjiuwen|openjiuwen_team|builtin`, `--env-file llm.env.bat`). Results under `data/eval/`.
- Expert blind review: `scripts/make_blind_review.py` builds `data/blind_review/专工盲评表.xlsx` (47 shuffled hard cases, BR-xx ids, order text only — no scores, tags, agent output or labels) + `key.json` (answer key, never sent to experts: label/rule/agent/team decisions snapshotted from the v3 eval files). `scripts/score_blind_review.py forms...` scores methods against the expert majority, reports inter-expert kappa and label disputes, and exports 专工出题 rows as cases with `expert_push` (used as the reference by `eval_hard_cases.py`). Both need openpyxl (`.jiuwen-venv`).
- Review agent engines: `core/agent_openjiuwen.py` (default when `openjiuwen` is importable; openJiuwen `ReActAgent`, our tools registered as `LocalFunction` via `ability_manager.add_ability`, thought captured with an `AFTER_MODEL_CALL` callback, openJiuwen logging forced to console WARNING) and the built-in loop in `core/agent.py`. Select with `AGENT_ENGINE=openjiuwen|builtin` or `create_app(agent_engine=...)`; when tests inject `llm_client`, auto mode picks builtin. openjiuwen needs Python 3.11–3.13 (`.jiuwen-venv`, `setup_openjiuwen.bat`, `requirements-openjiuwen.txt` — unpinned because openjiuwen needs newer pydantic/starlette/httpx than requirements-demo.txt). Both engines return the same run dict (+ `engine`).
- Review agent (`core/agent.py`): LLM tool-calling loop over read-only `ReviewToolbox` tools (get_order, get_prediction, get_user_profile, search_similar, recent_unit_orders, user_review_history, what_if) + `submit_conclusion`; max 8 tool calls. `validate_conclusion` drops evidence from tools not actually called, flags numbers absent from that tool's output (`unverified`), downgrades to needs_human when no valid evidence / contradiction. Runs stored in `agent_runs`; never mutates scores or feedback. `LLMClient.chat_with_tools` handles OpenAI-compatible and Anthropic formats via a neutral transcript.
- Tag categories: `device_type`, `manufacturer`, `fault_type`, `keyword`; codes like `TURBINE`, `MFR_DFST`, `FAULT_VIBRATION`, `KW_BEARING`.

## Environment Variables

| Variable | Purpose |
|---|---|
| `DEMO_DB_PATH` | SQLite file path (default `data/demo.sqlite3`) |
| `DEMO_API_TARGET` | Vite dev proxy target |
| `LLM_PROVIDER` | `openai` (any OpenAI-compatible API) or `anthropic`; empty = LLM disabled |
| `LLM_API_KEY` | API key (falls back to `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`); not needed for localhost Ollama |
| `LLM_MODEL`, `LLM_BASE_URL`, `LLM_TIMEOUT` | model name, API base URL, timeout seconds |
| `LLM_THINKING` | `disabled` sends DeepSeek `{"thinking": {"type": "disabled"}}` |
| `AGENT_ENGINE` | `openjiuwen_team` (alias `team`) / `openjiuwen` / `builtin`; empty = openjiuwen if installed |
| `OPENJIUWEN_LOG_LEVEL` | openJiuwen console log level (default WARNING) |

On Windows these are set in `llm.env.bat` (git-ignored, template `llm.env.example.bat`), loaded by `start_demo.bat`. Tests inject a fake client via `create_app(..., llm_config=..., llm_client=LLMClient(cfg, httpx.MockTransport(...)))`.

## Competition (openJiuwen 智能体创新大赛)

Apache-2.0 (`LICENSE`, `NOTICE`), `THIRD_PARTY_NOTICES.md`, `docs/competition/` (baseline vs new work, data statement, devlog). All metrics are against `scripts/simulate_review.py` rules on synthetic data — always say so. Never commit `llm.env.bat`, the thesis `.docx`, or virtualenvs. Don't rewrite or backfill git history.
