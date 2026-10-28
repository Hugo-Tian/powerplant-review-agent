"""
nlp_extractor.py
电厂事件信息 NLP 标签提取服务

Bug 修复记录：
  [BUG-3] record_job() 中使用了 ON CONFLICT DO NOTHING，
           但 nlp_extract_jobs 表只有 BIGSERIAL 主键，没有任何 UNIQUE 约束，
           PostgreSQL 会报错：
           "ON CONFLICT DO NOTHING requires inference specification or constraint name"
           修复：改为普通 INSERT，不加 ON CONFLICT。

  [BUG-4] LLMExtractor.extract() 调用 Anthropic API 时未传 x-api-key header，
           会返回 401 Unauthorized。
           修复：从环境变量 ANTHROPIC_API_KEY 读取并加入请求头。
"""

from __future__ import annotations

import json
import os
import re
import time
import asyncio
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)

# 预加载 jieba 自定义词典（抑制首次分词的 stderr 输出）
from core.nlp import (ExtractedTag, ExtractionResult, RuleExtractor, TFIDFExtractor,
                      LLMExtractor, TagFusionEngine)


class TagPersister:
    def __init__(self, db_pool: asyncpg.Pool):
        self.pool = db_pool

    async def ensure_tags_exist(self, tags: list[ExtractedTag]) -> dict[str, int]:
        code_to_id: dict[str, int] = {}
        async with self.pool.acquire() as conn:
            for tag in tags:
                row = await conn.fetchrow(
                    """
                    INSERT INTO tags (code, name, category)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                    """,
                    tag.code, tag.name, tag.category,
                )
                code_to_id[tag.code] = row["id"]
        return code_to_id

    async def save_event_tags(self, event_id: str, tags: list[ExtractedTag], code_to_id: dict[str, int]) -> int:
        if not tags:
            return 0
        records = [
            (event_id, code_to_id[t.code], t.confidence, t.source)
            for t in tags if t.code in code_to_id
        ]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO event_tags (event_id, tag_id, confidence, extract_method)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (event_id, tag_id) DO UPDATE
                  SET confidence = EXCLUDED.confidence,
                      extract_method = EXCLUDED.extract_method,
                      extracted_at = NOW()
                """,
                records,
            )
        return len(records)

    async def record_job(self, event_id: str, result: ExtractionResult) -> None:
        async with self.pool.acquire() as conn:
            # [BUG-3 修复] 去掉 ON CONFLICT DO NOTHING（nlp_extract_jobs 无 UNIQUE 约束）
            await conn.execute(
                """
                INSERT INTO nlp_extract_jobs
                  (event_id, model_ver, status, raw_result, token_count, duration_ms, error_msg, finished_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                """,
                event_id,
                result.model_version,
                "failed" if result.error else "done",
                json.dumps(result.raw_llm_output) if result.raw_llm_output else None,
                result.token_count,
                result.duration_ms,
                result.error,
            )


# ============================================================
# 6. 主流程（规则 → TF-IDF → LLM → 融合）
# ============================================================

class NLPExtractService:
    def __init__(self, db_pool: asyncpg.Pool, use_llm: bool = True):
        self.db_pool = db_pool
        self.rule_extractor = RuleExtractor()
        self.tfidf_extractor = TFIDFExtractor()
        self.fusion = TagFusionEngine()
        self.persister = TagPersister(db_pool)
        self._corpus_loaded = False
        self._corpus_lock = asyncio.Lock()

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if use_llm and api_key:
            self.llm_extractor: Optional[LLMExtractor] = LLMExtractor()
        else:
            self.llm_extractor = None
            if use_llm and not api_key:
                logger.warning("ANTHROPIC_API_KEY 未设置，LLM 提取已禁用，将使用规则+TF-IDF提取")

    async def _load_corpus_from_db(self) -> None:
        """首次调用时从 DB 加载近期事件文本，重新拟合 TF-IDF 向量器以扩充 IDF 基准。"""
        async with self._corpus_lock:
            if self._corpus_loaded:
                return
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT title || ' ' || COALESCE(content, '') AS text
                        FROM events
                        ORDER BY occurred_at DESC
                        LIMIT 500
                        """
                    )
                if rows:
                    corpus = [r["text"] for r in rows]
                    self.tfidf_extractor.refit(corpus)
            except Exception as exc:
                logger.warning(f"从 DB 加载 TF-IDF 语料失败: {exc}")
            finally:
                self._corpus_loaded = True   # 无论成败，避免反复重试

    async def process_event(
        self,
        event_id: str,
        title: str,
        content: str,
        force_reprocess: bool = False,
    ) -> ExtractionResult:
        t0 = time.monotonic()
        result = ExtractionResult(event_id=event_id)

        # 懒加载：首次调用时用 DB 语料重新拟合 TF-IDF（后续调用直接跳过）
        await self._load_corpus_from_db()

        # 从 DB 获取结构化字段扩充文本（设备类型名、厂家名、型号编码、KKS编码、事件类型）
        extra_parts: list[str] = []
        try:
            async with self.db_pool.acquire() as conn:
                meta = await conn.fetchrow(
                    """
                    SELECT e.kks_code, e.event_type,
                           dt.name  AS device_type_name,
                           m.name   AS manufacturer_name,
                           dm.model_code
                    FROM events e
                    LEFT JOIN device_types  dt ON dt.id = e.device_type_id
                    LEFT JOIN manufacturers m  ON m.id  = e.manufacturer_id
                    LEFT JOIN device_models dm ON dm.id = e.model_id
                    WHERE e.id = $1::uuid
                    """,
                    event_id,
                )
            if meta:
                for val in [
                    meta["device_type_name"], meta["manufacturer_name"],
                    meta["model_code"], meta["kks_code"], meta["event_type"],
                ]:
                    if val:
                        extra_parts.append(str(val))
        except Exception as exc:
            logger.warning(f"[{event_id}] 获取结构化字段失败: {exc}")

        full_text = title
        if extra_parts:
            full_text += "\n" + " ".join(extra_parts)
        full_text += "\n" + content

        rule_tags = self.rule_extractor.extract(full_text, event_id)
        logger.info(f"[{event_id}] 规则提取 {len(rule_tags)} 个标签")

        tfidf_tags = self.tfidf_extractor.extract(full_text, event_id)
        logger.info(f"[{event_id}] TF-IDF 提取 {len(tfidf_tags)} 个标签")

        llm_tags: list[ExtractedTag] = []
        if self.llm_extractor:
            try:
                llm_tags, raw = await self.llm_extractor.extract(full_text)
                result.raw_llm_output = raw
                result.model_version = raw.get("model", "")
                usage = raw.get("usage", {})
                result.token_count = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                logger.info(f"[{event_id}] LLM 提取 {len(llm_tags)} 个标签，{result.token_count} tokens")
            except Exception as e:
                logger.warning(f"[{event_id}] LLM 提取失败，降级为规则+TF-IDF: {e}")
                result.error = str(e)

        fused = self.fusion.fuse(rule_tags, llm_tags, tfidf_tags=tfidf_tags)
        result.tags = fused
        result.duration_ms = int((time.monotonic() - t0) * 1000)

        code_to_id = await self.persister.ensure_tags_exist(fused)
        saved = await self.persister.save_event_tags(event_id, fused, code_to_id)
        await self.persister.record_job(event_id, result)
        logger.info(f"[{event_id}] 融合后 {len(fused)} 个标签，入库 {saved} 条，耗时 {result.duration_ms}ms")

        return result

    async def batch_process(self, event_rows: list[dict], concurrency: int = 5) -> list[ExtractionResult]:
        sem = asyncio.Semaphore(concurrency)

        async def _one(row):
            async with sem:
                return await self.process_event(row["id"], row["title"], row["content"])

        return await asyncio.gather(*[_one(r) for r in event_rows])

    async def process_today_events(self) -> list[ExtractionResult]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT e.id::text, e.title, e.content
                FROM events e
                WHERE e.occurred_at >= CURRENT_DATE
                  AND NOT EXISTS (
                    SELECT 1 FROM event_tags et WHERE et.event_id = e.id
                  )
                ORDER BY e.occurred_at DESC
                LIMIT 200
                """
            )
        if not rows:
            logger.info("今日没有需要处理的事件")
            return []
        logger.info(f"开始批量处理 {len(rows)} 个今日事件")
        return await self.batch_process([dict(r) for r in rows])
