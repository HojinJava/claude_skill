"""문서의 수치를 자동 검사한다. reporting.md 의 오류 8유형 중 1·5·6·8 을 검출한다.
낸 것은 후보이지 판정이 아니다. 판정 절차는 verifying.md.

  [1] 분모 미표기      비율 옆에 분모가 없다
  [5] 재현 불가 수치    산출물 어디에도 없는 값
  [6] 같은 지표 다중 값  같은 라벨에 값이 여럿(대개 정의가 여럿이다)
  [8] 문서 간 불일치    형제 문서와 같은 라벨인데 값이 다르다

**후보를 보고하는 것이지 판정이 아니다.** 오탐이 있다. 하나씩 원자료로 확인한다.
2·3·4·7 유형은 의미 판단이라 사람이 본다.

    python validate.py out/report.txt --sources out/ --peer out/other.txt
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import extract_numbers  # noqa: E402

RE_LABEL_CLEAN = re.compile(r"[^\w가-힣]+")
RE_OTHER_NUM = re.compile(r"\d")
TOL = 0.051          # 비율 반올림 허용치 (소수 첫째 자리)
SCALE = {"K": 1e3, "M": 1e6, "B": 1e9}
REL_TOL = 0.005      # K/M/B 로 줄여 쓴 값은 반올림되므로 상대 허용치를 쓴다
MIN_COMPARE = 10     # 이보다 작은 정수는 각주·목록 번호라 지표로 안 본다


def label_key(n: dict) -> str:
    """같은 지표를 묶는 키. 앞 문맥의 마지막 단어 몇 개를 쓴다."""
    before = RE_LABEL_CLEAN.sub(" ", n["before"]).strip()
    parts = [p for p in before.split() if not p.isdigit()]
    return " ".join(parts[-3:]).lower()


def load_source_values(root: Path) -> set[float]:
    """산출 JSON 에 등장하는 모든 수치. 문서 수치가 여기 없으면 재현 불가 후보다."""
    vals: set[float] = set()

    def walk(o) -> None:
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, bool):
            return
        elif isinstance(o, (int, float)):
            vals.add(float(o))
        elif isinstance(o, str):
            for m in re.finditer(r"\d+(?:\.\d+)?", o):
                vals.add(float(m.group()))

    for p in sorted(root.rglob("*.json")):
        try:
            walk(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return vals


def scaled(n: dict) -> float:
    """127.2M → 127,200,000. 단위를 안 풀면 멀쩡한 값이 재현 불가로 잡힌다."""
    return n["value"] * SCALE.get(n["unit"], 1)


def is_year(n: dict) -> bool:
    """1997 · 2010.5 같은 연도·날짜 조각. 지표가 아니다."""
    return (n["unit"] == "" and "," not in n["raw"]
            and 1900 <= n["value"] <= 2100)


def near(v: float, pool: set[float], rel: bool) -> bool:
    if v in pool:
        return True
    if rel:                                   # 줄여 쓴 값: 상대 허용치
        return any(abs(v - c) <= max(v, c) * REL_TOL for c in pool)
    return any(abs(v - c) <= TOL for c in pool if abs(v - c) <= 1)


def check_denominator(nums: list[dict]) -> list[dict]:
    """[1] 비율 옆에 다른 수치가 없으면 분모 미표기 후보."""
    hits = []
    for n in nums:
        if n["unit"] != "%":
            continue
        ctx = n["context"].replace(n["raw"], " ", 1)
        if not RE_OTHER_NUM.search(ctx):
            hits.append(n)
    return hits


def comparable(nums: list[dict]) -> dict[str, set[float]]:
    """지표로 볼 만한 것만 (라벨, 단위) 로 묶는다.
    단위가 다르면 같은 지표가 아니고, 한 자리 정수는 각주·목록 번호다."""
    by: dict[str, set[float]] = defaultdict(set)
    for n in nums:
        if is_year(n) or n["value"] < MIN_COMPARE:
            continue
        k = label_key(n)
        if len(k) >= 4:
            by[f"{k}\t{n['unit']}"].add(scaled(n))
    return by


def check_multi_value(nums: list[dict]) -> list[tuple[str, set[float]]]:
    """[6] 같은 라벨·같은 단위인데 값이 여럿. 대개 정의가 여럿이다."""
    out = [(k, v) for k, v in comparable(nums).items() if len(v) > 1]
    return sorted(out, key=lambda x: -len(x[1]))


def check_unreproducible(nums: list[dict], pool: set[float]) -> list[dict]:
    """[5] 산출물 어디에도 없는 값. 연도·작은 수는 건너뛴다."""
    hits = []
    for n in nums:
        if is_year(n) or n["value"] < 100:
            continue
        v = scaled(n)
        if not near(v, pool, rel=n["unit"] in SCALE):
            hits.append(n)
    return hits


def check_peer(nums: list[dict], peer: list[dict]) -> list[tuple[str, float, float]]:
    """[8] 같은 라벨·같은 단위인데 형제 문서와 값이 다르다."""
    mine, theirs = comparable(nums), comparable(peer)
    out = []
    for k in set(mine) & set(theirs):
        a, b = mine[k], theirs[k]
        if not (a & b):
            out.append((k.replace("\t", " "), sorted(a)[0], sorted(b)[0]))
    return sorted(out)


def read_nums(p: Path) -> list[dict]:
    if p.suffix == ".json":
        return json.loads(p.read_text(encoding="utf-8")).get("numbers", [])
    return extract_numbers(p.read_text(encoding="utf-8"))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="문서 수치 자동 검사 (오류 1·5·6·8 유형)")
    ap.add_argument("doc", type=Path, help=".txt 또는 .claims.json")
    ap.add_argument("--sources", type=Path, help="산출 JSON 이 있는 폴더 (5 유형)")
    ap.add_argument("--peer", type=Path, action="append", default=[],
                    help="형제 문서 (8 유형) · 여러 번 지정 가능")
    ap.add_argument("--limit", type=int, default=15)
    a = ap.parse_args()

    nums = read_nums(a.doc)
    print(f"{a.doc.name}: 수치 {len(nums):,}개\n")
    total = 0

    hits = check_denominator(nums)
    total += len(hits)
    print(f"[1] 분모 미표기 후보 {len(hits)}건")
    for n in hits[:a.limit]:
        print(f"    L{n['line']:<5} {n['raw']:>8}   {n['context'][:80]}")

    if a.sources:
        pool = load_source_values(a.sources)
        hits = check_unreproducible(nums, pool)
        total += len(hits)
        print(f"\n[5] 재현 불가 후보 {len(hits)}건 (산출값 {len(pool):,}개와 대조)")
        for n in hits[:a.limit]:
            print(f"    L{n['line']:<5} {n['raw']:>10}   {n['before'][-30:]} ⟨…⟩ {n['after'][:20]}")

    groups = check_multi_value(nums)
    total += len(groups)
    print(f"\n[6] 같은 라벨 · 같은 단위 · 다중 값 {len(groups)}건")
    for key, vals in groups[:a.limit]:
        lab, unit = key.split("\t")
        shown = ", ".join(f"{v:,.10g}{unit}" for v in sorted(vals)[:5])
        print(f"    {lab[:34]:<34} → {shown}")

    for pp in a.peer:
        diffs = check_peer(nums, read_nums(pp))
        total += len(diffs)
        print(f"\n[8] {pp.name} 와 불일치 {len(diffs)}건")
        for k, x, y in diffs[:a.limit]:
            print(f"    {k[:34]:<34} 이 문서 {x:,.10g}  vs  {y:,.10g}")

    print(f"\n총 {total}건 후보. 판정이 아니다. 하나씩 원자료로 확인한다.")


if __name__ == "__main__":
    main()
