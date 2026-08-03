"""orchestration/target_gate.py — 성능 목표 게이트 + 주지표 선택 (P1: 완주→성능추구).

역할:
- `primary_metric(metrics)`: 실제 결과에서 "주지표"(정확도/top1/f1/auc/r2 또는 rmse/mae 등)를
  골라 (이름, 값, higher_is_better)를 반환 → 개선 outer loop의 best-so-far·수렴 판정에 사용.
- `parse_targets(success_criteria)`: 계획에 명시된 정량 목표(예 "top1 ≥ 70%")를 파싱.
- `evaluate(metrics, targets)`: 주지표를 목표와 대조해 met / missed / no_target 판정.

결정론적·LLM 불필요. 명시 목표가 없으면(대개 정성적 criteria) no_target → 루프는 "정체될 때까지
학습예산 증대"(수렴 추구) 정책으로 동작.
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional

# higher-is-better / lower-is-better 지표 토큰
_HIGHER = ("top1", "top-1", "top5", "top-5", "accuracy", "acc", "f1", "auc", "auroc",
           "roc", "precision", "recall", "r2", "r_squared", "map", "ndcg", "bleu", "iou", "dice")
_LOWER = ("rmse", "mae", "mse", "smape", "mape", "perplexity")

# 주지표 우선순위(앞선 것이 존재하면 주지표로 채택)
_PRIMARY_PRIORITY = ("top1", "accuracy", "acc", "f1", "auc", "roc", "r2", "rmse", "mae", "smape")

# 주지표에서 제외할 파생/부가 지표 토큰(비교/효율/시간/파라미터 등)
_EXCLUDE = ("diff", "delta", "ratio", "per_", "_per", "param", "time", "epoch",
            "loss", "train", "std", "var", "_run", "corr", "overlap", "importance")


def _flatten(metrics: dict) -> "list[tuple[str, Any]]":
    items: list[tuple[str, Any]] = []

    def _rec(d, p=""):
        if isinstance(d, dict):
            for k, v in d.items():
                kk = f"{p}{k}"
                if isinstance(v, dict):
                    _rec(v, kk + ".")
                else:
                    items.append((kk, v))

    _rec(metrics)
    return items


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def primary_metric(metrics: dict) -> "Optional[tuple[str, float, bool]]":
    """(주지표 토큰, 대표값, higher_is_better). 모델 여러 개면 higher는 max·lower는 min. 없으면 None."""
    if not isinstance(metrics, dict):
        return None
    inner = metrics.get("metrics", metrics)
    if not isinstance(inner, dict):
        inner = metrics
    items = [(k, float(v)) for k, v in _flatten(inner) if _is_num(v)]
    if not items:
        return None
    for tok in _PRIMARY_PRIORITY:
        cand = [(k, v) for k, v in items
                if tok in k.lower() and not any(x in k.lower() for x in _EXCLUDE)]
        if cand:
            higher = tok in _HIGHER
            val = max(v for _, v in cand) if higher else min(v for _, v in cand)
            return (tok, float(val), higher)
    return None


# "top1 >= 70%", "accuracy 0.85 이상", "R2 ≥ 0.75", "rmse <= 0.5" 등
_METRIC_ALT = r"(top-?1|top-?5|accuracy|acc|f1|auc|auroc|roc|r\^?2|r_squared|r2|rmse|mae|mse|smape|mape)"
_COMP_HIGHER = ("≥", ">=", ">", "at least", "above", "over", "최소", "이상", "초과")
_COMP_LOWER = ("≤", "<=", "<", "below", "under", "이하", "미만")
_TARGET_RE = re.compile(
    _METRIC_ALT + r"\s*(?:of|is|=|:)?\s*"
    r"(≥|<=|>=|≤|>|<|at least|above|over|below|under|최소|이상|초과|이하|미만)?\s*"
    r"([0-9]*\.?[0-9]+)\s*(%|percent|퍼센트)?",
    re.IGNORECASE,
)


def _norm_metric(m: str) -> str:
    m = m.lower().replace("-", "").replace("^", "")
    if m in ("r2", "r_squared", "rsquared"):
        return "r2"
    return m


def parse_targets(success_criteria) -> "list[dict]":
    """success_criteria(list[str])에서 정량 성능 목표를 추출. 없으면 []."""
    targets: list[dict] = []
    for c in success_criteria or []:
        for mobj in _TARGET_RE.finditer(str(c)):
            metric, comp, num, pct = mobj.groups()
            try:
                val = float(num)
            except (TypeError, ValueError):
                continue
            metric_n = _norm_metric(metric)
            higher = metric_n in [t.replace("-", "") for t in _HIGHER]
            # 방향: 명시 비교연산자 우선, 없으면 지표 성격(정확도=높을수록/오차=낮을수록)
            if comp:
                cl = comp.lower()
                direction = "higher" if any(x in cl for x in _COMP_HIGHER) else "lower"
            else:
                direction = "higher" if higher else "lower"
            # 퍼센트/스케일: % 표기거나 정확도류인데 값>1이면 0-1 스케일로 정규화 후보도 저장
            if pct or (higher and val > 1.0):
                val_frac = val / 100.0
            else:
                val_frac = val
            targets.append({
                "metric": metric_n, "direction": direction,
                "value": val, "value_frac": val_frac, "raw": mobj.group(0).strip(),
            })
    return targets


def evaluate(metrics: dict, targets: "list[dict]") -> dict:
    """주지표를 목표와 대조. status ∈ {met, missed, no_target}."""
    pm = primary_metric(metrics)
    if not targets:
        return {"status": "no_target", "primary": pm, "detail": "명시 성능 목표 없음(수렴 정책 사용)"}
    if pm is None:
        return {"status": "missed", "primary": None, "detail": "주지표를 찾지 못함"}
    name, value, higher = pm
    # 주지표와 같은 계열의 목표를 우선 매칭, 없으면 첫 목표
    matched = next((t for t in targets if t["metric"] in name or name in t["metric"]), targets[0])
    # 값 스케일 정합: 지표가 0-1인데 목표가 %면 value*100로 비교
    tgt = matched["value_frac"] if value <= 1.0 else matched["value"]
    ok = (value >= tgt) if matched["direction"] == "higher" else (value <= tgt)
    return {
        "status": "met" if ok else "missed",
        "primary": pm,
        "target": matched,
        "detail": f"{name}={value:.4f} vs 목표 {matched['direction']} {tgt} → {'달성' if ok else '미달'}",
    }


def is_better(new_val: float, old_val: Optional[float], higher_is_better: bool) -> bool:
    """best-so-far 비교."""
    if old_val is None:
        return True
    return (new_val > old_val) if higher_is_better else (new_val < old_val)
