"""Similar historical work orders (offline, no external API).

similarity = 0.7 x cosine(char 2-3gram TF-IDF of title + content)
           + 0.3 x Jaccard(tag codes)

Character n-grams work for Chinese without a tokenizer and are robust to
synonyms sharing characters (汽机 / 汽轮机). The text matrix is rebuilt only when
the stored orders change; tags are updated per order after each prediction.
"""
from __future__ import annotations

from typing import Iterable, Optional

TEXT_WEIGHT, TAG_WEIGHT = 0.7, 0.3


def order_text(order: dict) -> str:
    return f"{order.get('title', '')}\n{order.get('content', '')}"


class SimilarityIndex:
    def __init__(self, orders: list[dict], tags_by_event: dict[str, set[str]]):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.orders = orders
        self.ids = [o["event_id"] for o in orders]
        self.tags = tags_by_event
        self._vectorizer = None
        self._matrix = None
        if orders:
            self._vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3),
                                               sublinear_tf=True, min_df=1)
            self._matrix = self._vectorizer.fit_transform([order_text(o) for o in orders])

    def set_tags(self, event_id: str, tags: Iterable[str]) -> None:
        """Update one order's tags after a new prediction, without refitting the text matrix."""
        self.tags[event_id] = set(tags)

    def query(self, text: str, tags: Iterable[str], *, exclude: Optional[str] = None,
              k: int = 5, min_score: float = 0.15) -> list[dict]:
        if self._vectorizer is None:
            return []
        q = self._vectorizer.transform([text])
        cos = (self._matrix @ q.T).toarray().ravel()  # rows are L2-normalised
        qtags = set(tags)
        results = []
        for i, event_id in enumerate(self.ids):
            if event_id == exclude:
                continue
            other = self.tags.get(event_id, set())
            union = qtags | other
            jac = len(qtags & other) / len(union) if union else 0.0
            score = TEXT_WEIGHT * float(cos[i]) + TAG_WEIGHT * jac
            if score >= min_score:
                results.append((score, float(cos[i]), jac, i))
        results.sort(key=lambda r: r[0], reverse=True)
        out = []
        for score, text_sim, jac, i in results[:k]:
            o = self.orders[i]
            out.append({
                "event_id": o["event_id"], "title": o["title"], "level": o.get("level"),
                "unit_no": o.get("unit_no"), "similarity": round(score, 4),
                "text_similarity": round(text_sim, 4), "tag_overlap": round(jac, 4),
                "shared_tags": sorted(qtags & self.tags.get(o["event_id"], set())),
            })
        return out
