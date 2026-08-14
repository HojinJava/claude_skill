"""S단계 · 폴더 탐색.

도메인을 모르는 상태에서 폴더 하나를 열어 다음을 알아낸다.
  - 무엇이 몇 개 있는가 (확장자 · 크기 · 깊이 · 인코딩)
  - 구조 마커 후보는 무엇인가 (줄머리 패턴을 골격으로 수집)
  - 폴더가 문서 묶음을 이루는가 (leaf 디렉터리 fan-out)
  - 메타(frontmatter)가 있는가
  - 대표 파일로 무엇을 읽어야 하는가 (구조 요소를 가장 많이 가진 파일)

도메인·형식·언어를 가정하지 않는다. 마커를 미리 알고 찾는 게 아니라 빈도로 떠오르게 한다.

    python survey.py <folder> [-o out/survey.json] [--sample 800] [--full]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ── 열거 기호. 언어권마다 다르므로 넉넉히 잡고 <E> 로 접는다 ──────────────────
ENUM_CHARS = (
    "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚"
    "❶❷❸❹❺❻❼❽❾❿"
    "ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹⅠⅡⅢⅣⅤ"
    "ⓐⓑⓒⓓⓔ㉮㉯㉰㉱"
)
RE_ENUM = re.compile(f"[{re.escape(ENUM_CHARS)}]+")
RE_DIGIT = re.compile(r"\d+")

# 줄머리에서 "선택적 기호 + 숫자를 낀 짧은 토큰" 을 잡는다.
# `## 제1조(목적)` → `## ` + `제1조` / `1.2.3 Overview` → `1` / `Article 12` → `Article 12`
RE_NUMBERED = re.compile(
    r"^(?P<punct>[^\w\s]{0,4}\s*)?"
    r"(?P<tok>(?:[^\W\d_]{1,8}\s*)?\d+(?:\s*[^\W\d_]{1,4})?)"
)
RE_FM_KEY = re.compile(r"^([^\s:][^:]{0,40}):")

TEXT_EXT = {
    ".md", ".markdown", ".txt", ".rst", ".adoc", ".org",
    ".json", ".jsonl", ".yaml", ".yml", ".csv", ".tsv",
    ".html", ".htm", ".xml", ".tex", ".log",
}
SKIP_DIR = {".git", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".idea"}
MAX_SKELETON = 24


def read_text(p: Path) -> tuple[str | None, str]:
    """(본문, 인코딩라벨). 실패하면 (None, 사유). 개행은 LF 로 정규화한다."""
    raw = p.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp949", "euc-kr", "cp1252"):
        try:
            return raw.decode(enc).replace("\r\n", "\n").replace("\r", "\n"), enc
        except UnicodeDecodeError:
            continue
    return None, "decode-failed"


def skeleton(line: str) -> str | None:
    """줄머리를 구조 마커 골격으로 접는다. 마커가 아니면 None."""
    s = line.strip()
    if not s:
        return None
    s = RE_ENUM.sub("<E>", s)

    # 짧고 기호로 시작하는 줄은 통째로 마커로 본다 (【이 유】 · --- · === 등)
    if len(s) <= MAX_SKELETON and not s[0].isalnum():
        return RE_DIGIT.sub("<N>", s)

    m = RE_NUMBERED.match(s)
    if m and ("<N>" not in s[: m.end()]):
        punct = (m.group("punct") or "").strip()
        tok = RE_DIGIT.sub("<N>", m.group("tok").strip())
        if "<N>" not in tok:
            return None
        out = f"{punct} {tok}".strip()
        return out[:MAX_SKELETON]

    if s.startswith("<E>"):
        return "<E>"
    return None


def scan(folder: Path, sample: int, full: bool) -> dict:
    files: list[Path] = []
    for p in folder.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIR for part in p.parts):
            continue
        files.append(p)
    if not files:
        sys.exit(f"[중단] 파일이 없다: {folder}")

    ext_ct = Counter(p.suffix.lower() or "<확장자없음>" for p in files)
    sizes = sorted(p.stat().st_size for p in files)
    depths = Counter(len(p.relative_to(folder).parts) - 1 for p in files)

    # leaf 디렉터리 fan-out: 폴더가 문서 묶음을 이루는지 본다
    per_dir: dict[Path, list[str]] = defaultdict(list)
    for p in files:
        per_dir[p.parent].append(p.name)
    fanout = Counter(len(v) for v in per_dir.values())
    nameset = Counter(
        " · ".join(sorted(v)) for v in per_dir.values() if 1 < len(v) <= 6
    )

    # 본문 분석 대상: 가장 흔한 텍스트 확장자
    main_ext = next(
        (e for e, _ in ext_ct.most_common() if e in TEXT_EXT),
        ext_ct.most_common(1)[0][0],
    )
    targets = [p for p in files if (p.suffix.lower() or "<확장자없음>") == main_ext]
    if not full and len(targets) > sample:
        random.seed(0)
        targets = random.sample(targets, sample)

    skel_files: Counter = Counter()   # 골격 → 등장한 파일 수
    skel_lines: Counter = Counter()   # 골격 → 총 등장 줄 수
    fm_keys: Counter = Counter()
    fm_vals: dict[str, Counter] = defaultdict(Counter)
    enc_ct: Counter = Counter()
    n_fm = 0
    chars_lf = 0
    chars_raw = 0
    per_file_skels: dict[str, set] = {}

    for p in targets:
        body, enc = read_text(p)
        enc_ct[enc] += 1
        if body is None:
            continue
        chars_lf += len(body)
        chars_raw += p.stat().st_size
        lines = body.split("\n")

        if lines and lines[0].strip() in ("---", "+++"):
            n_fm += 1
            for ln in lines[1:60]:
                if ln.strip() in ("---", "+++"):
                    break
                mk = RE_FM_KEY.match(ln)
                if mk:
                    k = mk.group(1).strip()
                    fm_keys[k] += 1
                    v = ln[mk.end():].strip()
                    if v and len(v) <= 40:
                        fm_vals[k][v] += 1

        seen = set()
        for ln in lines:
            sk = skeleton(ln)
            if sk:
                skel_lines[sk] += 1
                seen.add(sk)
        per_file_skels[str(p)] = seen
        for sk in seen:
            skel_files[sk] += 1

    n_read = max(1, sum(1 for v in per_file_skels.values()))
    markers = [
        {
            "골격": sk,
            "파일수": cnt,
            "파일비율": round(cnt * 100 / n_read, 1),
            "총줄수": skel_lines[sk],
        }
        for sk, cnt in skel_files.most_common(30)
        if cnt >= max(2, n_read * 0.02)
    ]

    # 대표 파일: 상위 마커를 가장 많이 포함하고, 같은 계열 문서가 함께 있는 것.
    # 형제가 있는 폴더를 우대한다. 계층·위임 관계는 형제 문서에서만 드러난다.
    top = {m["골격"] for m in markers[:12]}
    med = sizes[len(sizes) // 2] or 1
    scored = []
    for f, seen in per_file_skels.items():
        p = Path(f)
        sz = p.stat().st_size
        sib = len(per_dir[p.parent])
        hit = len(seen & top)
        penalty = 0.0 if med / 4 <= sz <= med * 20 else 0.5
        score = (hit + min(sib, 4) * 0.75) * (1 - penalty)
        scored.append((score, hit, sib, f, sz))
    scored.sort(reverse=True)

    return {
        "폴더": str(folder),
        "파일수": len(files),
        "확장자": dict(ext_ct.most_common(15)),
        "크기_바이트": {
            "합계": sum(sizes),
            "중앙값": sizes[len(sizes) // 2],
            "p95": sizes[int(len(sizes) * 0.95)],
            "최대": sizes[-1],
        },
        "깊이_분포": dict(sorted(depths.items())),
        "leaf폴더": {
            "개수": len(per_dir),
            "파일수_분포": dict(sorted(fanout.items())[:10]),
            "흔한_파일조합": dict(nameset.most_common(5)),
        },
        "본문분석": {
            "확장자": main_ext,
            "읽은_파일": len(targets),
            "전수여부": full or len(targets) == len([p for p in files if p.suffix.lower() == main_ext]),
            "인코딩": dict(enc_ct),
            "문자수_LF정규화": chars_lf,
            "바이트합": chars_raw,
        },
        "frontmatter": {
            "보유_파일": n_fm,
            "키": dict(fm_keys.most_common(20)),
            "키별_상위값": {
                k: dict(c.most_common(5)) for k, c in list(fm_vals.items())[:10]
            },
        },
        "구조마커_후보": markers,
        "대표파일_추천": [
            {"경로": f, "포함마커수": n, "형제파일": sib, "바이트": sz}
            for _, n, sib, f, sz in scored[:5]
        ],
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):        # 콘솔 코드페이지가 한글을 깨뜨린다
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="폴더 탐색 · 구조 마커 후보 · 대표 파일 추천")
    ap.add_argument("folder", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--sample", type=int, default=800, help="본문 분석 표본 수 (기본 800)")
    ap.add_argument("--full", action="store_true", help="표본 없이 전수 분석")
    a = ap.parse_args()

    if not a.folder.is_dir():
        sys.exit(f"[중단] 폴더가 아니다: {a.folder}")

    r = scan(a.folder, a.sample, a.full)

    b = r["본문분석"]
    print(f"파일 {r['파일수']:,}개 · {r['크기_바이트']['합계']:,}바이트")
    print(f"확장자 {r['확장자']}")
    print(f"leaf 폴더 {r['leaf폴더']['개수']:,}개 · 파일수 분포 {r['leaf폴더']['파일수_분포']}")
    print(f"본문 {b['확장자']} {b['읽은_파일']:,}개 읽음 · {b['문자수_LF정규화']:,}자(LF) · 인코딩 {b['인코딩']}")
    if r["frontmatter"]["보유_파일"]:
        print(f"frontmatter {r['frontmatter']['보유_파일']:,}개 · 키 {list(r['frontmatter']['키'])[:8]}")

    print("\n구조 마커 후보 (파일비율 순)")
    for m in r["구조마커_후보"][:12]:
        print(f"  {m['파일비율']:5.1f}%  {m['총줄수']:>9,}줄  {m['골격']!r}")

    print("\n대표 파일 추천 (직접 읽을 것 · 3~5건)")
    for d in r["대표파일_추천"]:
        print(f"  마커 {d['포함마커수']:2}종  형제 {d['형제파일']}  {d['바이트']:>9,}B  {d['경로']}")

    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n→ {a.out}")


if __name__ == "__main__":
    main()
