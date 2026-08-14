"""load.py 의 fast · safe 두 경로가 같은 결과를 내는지 확인한다.

두 경로가 어긋나면 조용히 틀린 값이 나온다. 실제로 fast 경로에서 rel_path 접두어가
안 잘려 depth 가 통째로 어긋난 적이 있다. load.py 를 고치면 이걸 돌린다.

    python selftest.py <작은-폴더> [--glob "**/*.md"]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import duckdb
except ImportError:
    sys.exit("[중단] pip install duckdb")

HERE = Path(__file__).resolve().parent
CHECKS = {
    "files": "count(*)",
    "chars": "sum(n_chars)",
    "lines": "sum(n_lines)",
    "frontmatter": "count(fm_raw)",
    "depth합": "sum(depth)",
    "sibling합": "sum(sibling_n)",
    "본문합": "sum(length(body))",
    "경로_최소": "min(rel_path)",
    "경로_최대": "max(rel_path)",
    "ext종류": "count(DISTINCT ext)",
}


def build(folder: Path, glob: str, db: Path, safe: bool) -> None:
    cmd = [sys.executable, str(HERE / "load.py"), str(folder),
           "--db", str(db), "--glob", glob]
    if safe:
        cmd.append("--safe")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        sys.exit(f"[중단] load 실패({'safe' if safe else 'fast'})\n{r.stdout}\n{r.stderr}")
    if not safe and "(fast)" not in r.stdout:
        sys.exit(f"[중단] fast 경로가 safe 로 폴백했다. 등가 비교가 안 된다\n{r.stdout}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="fast · safe 적재 경로 등가성 검사")
    ap.add_argument("folder", type=Path)
    ap.add_argument("--glob", default="**/*.md")
    a = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        f, s = Path(tmp) / "fast.duckdb", Path(tmp) / "safe.duckdb"
        build(a.folder, a.glob, f, safe=False)
        build(a.folder, a.glob, s, safe=True)

        sql = "SELECT " + ", ".join(CHECKS.values()) + " FROM doc"
        fa = duckdb.connect(str(f), read_only=True).sql(sql).fetchone()
        sa = duckdb.connect(str(s), read_only=True).sql(sql).fetchone()

    bad = 0
    for name, x, y in zip(CHECKS, fa, sa):
        ok = x == y
        bad += not ok
        print(f"  {name:<10} fast={x!s:<28} safe={y!s:<28} {'OK' if ok else '### 불일치'}")
    print(f"\n{'통과' if not bad else f'실패 {bad}건'} · {len(CHECKS)}개 항목")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
