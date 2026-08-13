"""HTML 리포트에서 본문 텍스트와 수치를 뽑는다.

Step 문서끼리 HTML 을 참조하면 태그 때문에 컨텍스트가 부푼다.
텍스트와 수치만 뽑아 참조하고, 원본 해시를 찍어 원본이 바뀌면 재생성되게 한다.
파생물은 gitignore 한다.

    python extract.py report.html -o out/report.txt
    python extract.py report.html -o out/report.txt --claims out/report.claims.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

DROP_TAGS = {"script", "style", "head", "noscript", "svg"}
BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "nav", "aside",
    "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "br", "hr",
    "table", "thead", "tbody", "details", "summary", "figure", "blockquote",
}

# 1,234 · 12.5 · 45.1% · 8K · 127.2M 를 잡는다. 단위는 raw 에 남긴다
RE_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([%KMB자건개곳종줄]?)")
RE_WS = re.compile(r"[ \t]+")


class Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_TAGS:
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.out.append("\n")
        elif tag == "td" or tag == "th":
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in DROP_TAGS and self.skip:
            self.skip -= 1
        elif tag in BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.out.append(RE_WS.sub(" ", data))


def to_text(html: str) -> str:
    p = Text()
    p.feed(html)
    raw = "".join(p.out)
    lines = [RE_WS.sub(" ", ln).strip(" |") for ln in raw.split("\n")]
    return "\n".join(ln for ln in lines if ln.strip())


def extract_numbers(text: str) -> list[dict]:
    """수치 + 앞뒤 문맥. 라벨은 검증에서 같은 지표를 묶는 키가 된다."""
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        for m in RE_NUM.finditer(line):
            digits, unit = m.group(1), m.group(2)
            try:
                val = float(digits.replace(",", ""))
            except ValueError:
                continue
            before = line[max(0, m.start() - 40):m.start()].strip()
            after = line[m.end():m.end() + 24].strip()
            out.append({
                "line": i,
                "raw": m.group(0).strip(),
                "value": val,
                "unit": unit,
                "before": before,
                "after": after,
                "context": line.strip()[:200],
            })
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="HTML → 텍스트 · 수치 추출")
    ap.add_argument("src", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--claims", type=Path, help="수치 목록 JSON 경로")
    a = ap.parse_args()

    raw = a.src.read_bytes()
    html = raw.decode("utf-8", errors="replace")
    text = to_text(html) if a.src.suffix.lower() in (".html", ".htm") else html
    digest = hashlib.sha256(raw).hexdigest()[:16]

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(
        f"<!-- source: {a.src} sha256:{digest} -->\n{text}\n", encoding="utf-8"
    )
    nums = extract_numbers(text)
    print(f"{a.src.name}: {len(html):,}자(HTML) → {len(text):,}자(텍스트) "
          f"· {(1 - len(text) / max(1, len(html))) * 100:.0f}% 감소 · 수치 {len(nums):,}개")
    print(f"→ {a.out}")

    if a.claims:
        a.claims.parent.mkdir(parents=True, exist_ok=True)
        a.claims.write_text(json.dumps(
            {"source": str(a.src), "sha256": digest, "numbers": nums},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"→ {a.claims}")


if __name__ == "__main__":
    main()
