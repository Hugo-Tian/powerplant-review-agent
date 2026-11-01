"""设备—部件知识库（data/knowledge/components.json）。

* rule_synonyms()：rule_safe 的叫法，启动时作为经作者审定的同义词加入规则词典；
* lookup()：审核智能体的 lookup_component 工具 —— 查部件属于哪个系统、哪个设备代码、哪些岗位负责；
* ambiguous_mentions()：原文里出现、但有歧义不能直接打标签的部件名，供分流说明。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from core.policy import NAMES, ROLE_RULES

KB_PATH = Path(__file__).resolve().parents[1] / "data/knowledge/components.json"


@lru_cache(maxsize=1)
def components() -> tuple[dict, ...]:
    if not KB_PATH.is_file():
        return ()
    return tuple(json.loads(KB_PATH.read_text(encoding="utf-8"))["components"])


def names_of(entry: dict) -> list[str]:
    return [entry["term"], *entry.get("aliases", [])]


def rule_synonyms() -> list[tuple[str, str]]:
    """(name, device code) for every rule-safe name."""
    return [(n, c["code"]) for c in components() if c.get("rule_safe") for n in names_of(c)]


def responsible_roles(code: str) -> dict:
    return {"核心设备": [r for r, (core, _) in ROLE_RULES.items() if code in core],
            "相关设备": [r for r, (_, rel) in ROLE_RULES.items() if code in rel]}


def _view(entry: dict, matched: str) -> dict:
    return {"matched": matched, "component": entry["term"], "system": entry["system"], "code": entry["code"],
            "device": NAMES.get(entry["code"], entry["code"]), "roles": responsible_roles(entry["code"]),
            "ambiguous": not entry.get("rule_safe"), "note": entry.get("note", "")}


def lookup(term: str | None = None, text: str = "") -> list[dict]:
    """With ``term``: entries whose names contain it or are contained in it. Without: every entry named in ``text``."""
    found = []
    for entry in components():
        names = names_of(entry)
        if term:
            hit = next((n for n in names if n and (n in term or term in n)), None)
        else:
            hit = next((n for n in sorted(names, key=len, reverse=True) if n and n in text), None)
        if hit:
            found.append(_view(entry, hit))
    return found


def ambiguous_mentions(text: str) -> list[dict]:
    return [v for v in lookup(text=text) if v["ambiguous"]]
