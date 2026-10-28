"""Learning from human feedback (step 5). Nothing here changes the live system by
itself: every function returns *suggestions*; the API applies them only after a
person approves.

* fit_weights      – refit the four dimension weights from reviewed predictions
* profile_suggestions – turn repeated human corrections into per-user interest
                        adjustments (deterministic, evidence attached)
* feedback_metrics – how well model scores agree with human judgement
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

DIMENSIONS = ("device_type", "behavior", "role", "manufacturer")
MIN_SAMPLES = 10


def human_score(sample: dict) -> float:
    """Human-judged score: corrected value if any, otherwise the confirmed model score."""
    if "target" in sample:  # fixed when the sample was re-based onto a newer prediction
        return float(sample["target"])
    fb = sample["feedback"]
    if fb["action"] == "correct" and fb.get("corrected_score") is not None:
        return float(fb["corrected_score"])
    return float(sample["result"]["score"])


def rebase(samples: list[dict], latest: dict) -> list[dict]:
    """Keep each human target, but use the latest prediction's breakdown, so that
    weights are fitted against the current scoring formula and profiles."""
    out = []
    for s in samples:
        new = latest.get((s["result"]["user_id"], s["order"]["event_id"]))
        out.append(dict(s, target=human_score(s), result=new) if new else s)
    return out


def _predict(breakdown: dict, w: dict) -> float:
    return min(1.0, sum(breakdown.get(d, 0.0) * w[d] for d in DIMENSIONS))


def fit_weights(samples: list[dict], current: dict) -> dict:
    """Constrained least squares: w >= 0, sum(w) = 1, each w <= 0.7.

    Emergency-floor results are excluded (their score is fixed at >= 0.75, so the
    weights do not explain it). Returns suggested weights and before/after MAE.
    """
    rows = [s for s in samples if s["result"].get("push_type") != "emergency"
            and (s["result"].get("effective_level") or s["order"].get("level")) != "紧急"]
    if len(rows) < MIN_SAMPLES:
        return {"status": "insufficient", "samples": len(rows), "required": MIN_SAMPLES,
                "current": current}
    import numpy as np
    from scipy.optimize import minimize

    X = np.array([[s["result"]["breakdown"].get(d, 0.0) for d in DIMENSIONS] for s in rows])
    y = np.array([human_score(s) for s in rows])
    w0 = np.array([current[d] for d in DIMENSIONS])

    def loss(w):
        return float(np.mean((X @ w - y) ** 2))

    res = minimize(loss, w0, method="SLSQP", bounds=[(0.0, 0.7)] * 4,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}])
    w = np.clip(res.x, 0, None)
    w = w / w.sum()
    suggested = {d: round(float(v), 4) for d, v in zip(DIMENSIONS, w)}
    # keep sum exactly 1 after rounding
    suggested[DIMENSIONS[0]] = round(1 - sum(suggested[d] for d in DIMENSIONS[1:]), 4)
    mae = lambda weights: float(np.mean([abs(_predict(s["result"]["breakdown"], weights) - human_score(s))  # noqa: E731
                                         for s in rows]))
    return {"status": "ok", "samples": len(rows), "current": current, "suggested": suggested,
            "mae_current": round(mae(current), 4), "mae_suggested": round(mae(suggested), 4),
            "note": "样本内拟合结果，样本少时可能过拟合；已排除紧急保底工单。"}


def profile_suggestions(samples: list[dict], *, min_evidence: int = 2,
                        threshold: float = 0.2, step: float = 0.2) -> list[dict]:
    """Aggregate corrections per (user, tag). If humans repeatedly lowered (raised)
    scores of orders carrying a tag the user is interested in (not interested in),
    suggest lowering (raising) that interest. Only corrections count."""
    buckets = {"device_type": "device_interests", "fault_type": "fault_interests",
               "keyword": "keyword_interests", "manufacturer": "mfr_interests"}
    votes: dict[tuple, dict] = defaultdict(lambda: {"down": [], "up": [], "name": "", "current": 0.0})
    for s in samples:
        fb = s["feedback"]
        if fb["action"] != "correct" or fb.get("corrected_score") is None:
            continue
        delta = float(fb["corrected_score"]) - float(s["result"]["score"])
        if abs(delta) < threshold:
            continue
        profile = s["profile"]
        for tag in s["result"]["tags"]:
            bucket = buckets.get(tag["category"])
            if not bucket:
                continue
            interest = float(profile.get(bucket, {}).get(tag["code"], 0.0))
            key = (s["result"]["user_id"], bucket, tag["code"])
            v = votes[key]
            v["name"], v["current"] = tag["name"], interest
            evidence = {"prediction_id": s["result"]["prediction_id"], "event_id": s["order"]["event_id"],
                        "title": s["order"]["title"], "model_score": s["result"]["score"],
                        "corrected_score": fb["corrected_score"], "comment": fb.get("comment", "")}
            if delta < 0 and interest > 0:
                v["down"].append(evidence)
            elif delta > 0 and interest < 1:
                v["up"].append(evidence)
    out = []
    for (user_id, bucket, code), v in votes.items():
        for direction, ev in (("down", v["down"]), ("up", v["up"])):
            other = v["up"] if direction == "down" else v["down"]
            if len(ev) >= min_evidence and len(ev) > len(other):
                new = v["current"] - step if direction == "down" else v["current"] + step
                out.append({"user_id": user_id, "bucket": bucket, "code": code, "name": v["name"],
                            "direction": direction, "current": round(v["current"], 4),
                            "suggested": round(min(1.0, max(0.0, new)), 4),
                            "evidence": ev[:5], "evidence_count": len(ev)})
    out.sort(key=lambda x: x["evidence_count"], reverse=True)
    return out


def feedback_metrics(samples: list[dict], push_threshold: float = 0.5) -> dict:
    """Agreement between model and human. One sample = latest feedback of a prediction."""
    n = len(samples)
    if not n:
        return {"reviewed": 0}
    corrected = [s for s in samples if s["feedback"]["action"] == "correct"]
    errors = [abs(float(s["result"]["score"]) - human_score(s)) for s in samples]
    agree = sum((s["result"]["score"] >= push_threshold) == (human_score(s) >= push_threshold) for s in samples)
    flagged = [s for s in samples if (s["result"].get("triage") or {}).get("needs_review")]
    flagged_corrected = [s for s in corrected if (s["result"].get("triage") or {}).get("needs_review")]
    by_mode: dict[str, list] = defaultdict(list)
    for s, e in zip(samples, errors):
        by_mode[s["result"].get("inference_mode", "unknown")].append(e)
    return {
        "reviewed": n,
        "confirm_rate": round(1 - len(corrected) / n, 4),
        "correct_rate": round(len(corrected) / n, 4),
        "mae": round(sum(errors) / n, 4),
        "push_decision_agreement": round(agree / n, 4),
        "push_threshold": push_threshold,
        "flagged": len(flagged),
        "triage_recall": round(len(flagged_corrected) / len(corrected), 4) if corrected else None,
        "mae_by_inference_mode": {m: round(sum(v) / len(v), 4) for m, v in by_mode.items()},
        "note": "以人工审核结果为参照：确认视为认可模型分数，修改以修正值为准。只统计有人工反馈的推送。",
    }


def before_after(samples: list[dict], latest: dict, push_threshold: float = 0.5) -> dict:
    """Compare the reviewed prediction and the *latest* prediction of the same
    (user, order) against the human-judged score. ``latest`` maps
    (user_id, event_id) -> latest result. Shows whether later changes (weights,
    profile, vocabulary) moved scores toward human judgement."""
    pairs = []
    for s in samples:
        key = (s["result"]["user_id"], s["order"]["event_id"])
        new = latest.get(key)
        if new is None or new["prediction_id"] == s["result"]["prediction_id"]:
            continue
        pairs.append((float(s["result"]["score"]), float(new["score"]), human_score(s)))
    if not pairs:
        return {"compared": 0, "note": "被审核的工单还没有新的预测；调整设置后点击“按最新画像重新推送”再看。"}
    n = len(pairs)
    mae_b = sum(abs(b - h) for b, _, h in pairs) / n
    mae_a = sum(abs(a - h) for _, a, h in pairs) / n
    agree = lambda i: sum((p[i] >= push_threshold) == (p[2] >= push_threshold) for p in pairs) / n  # noqa: E731
    return {"compared": n, "mae_before": round(mae_b, 4), "mae_after": round(mae_a, 4),
            "agreement_before": round(agree(0), 4), "agreement_after": round(agree(1), 4),
            "push_threshold": push_threshold,
            "note": "同一批被审核工单：审核时的分数 vs 最新预测分数，均以审核结论为参照。"}
