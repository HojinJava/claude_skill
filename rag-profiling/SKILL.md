---
name: rag-profiling
description: >-
  Use when starting RAG on a new corpus and the chunking/loading design is not yet decided - runs as a team (one orchestrator dispatching measurer, reader, refuter, checker agents in parallel rounds), loads the corpus into a local DuckDB and measures the raw documents first, then picks chunking, enrichment, loading scope, metadata filters and cross-corpus links from evidence instead of defaults. The deliverable is a CONSULTING presentation, not a measurement log - its table of contents is the argument itself and every number traces back to a query. Scope is the corpus axis only: retrieval method, query transformation and post-processing need an evaluation set and stay unresolved here. Triggers on "RAG 프로파일링", "코퍼스 프로파일링", "이 데이터로 청킹 어떻게", "임베딩 대상 정해야 함", "코퍼스 분석부터", "어떤 RAG 기법 써야 하나", profiling a document folder before indexing.
---

# 코퍼스 프로파일링

> **검색 대상 데이터를 먼저 실측하고, 그 데이터에 맞춰 RAG 를 설계한다.**
> 산출은 **컨설팅 발표물**이고, 일은 **한 명이 아니라 팀이** 한다.

RAG 품질은 기법이 아니라 데이터가 정한다. 같은 기법도 데이터 생김새에 따라 효과가 뒤집힌다.
그래서 널리 좋다는 기법을 가져다 붙이지 않는다. 데이터를 먼저 재고, 그 값에 맞춰
**청킹 단위 · 검색 방식 · 인덱싱 대상 · 적재 범위**를 정한다.

실제 사례에서 실측 전에 세워둔 설계 **5건이 그대로 뒤집혔다.**
5단 계층 파서는 불필요했고(파일의 64.3%가 최소 단위만 씀), 과제는 긴 조각이 아니라 짧은 조각이었고,
판례 코퍼스는 586.7M자 전체가 임베딩 대상에서 빠졌다.

## 무엇을 내는가

**측정 기록이 아니라 컨설팅 산출물이다.** 이 스킬에서 가장 위에 있는 규칙이다.
남의 데이터를 분석해 주고 **"그래서 이렇게 하십시오"** 를 내놓는 자리다.
잰 것을 순서대로 늘어놓으면 컨설팅이 아니라 로그다.

**목차가 곧 발표 흐름이다.** 절 제목만 위에서 아래로 읽어도 이야기가 되어야 하고,
절마다 앞에서 받고 뒤로 넘긴다. 표준 목차와 이음매 규칙은 `references/narrative.md`.

## 어떻게 도는가

**한 에이전트가 처음부터 끝까지 하지 않는다.** 오케스트레이터 하나가 역할을 나눠 주고,
받은 것을 모아 판정하고, 다음 라운드를 건다. **토큰을 아끼려고 나누는 것이 아니라 정확도 때문에 나눈다.**
자기가 잰 값을 자기가 검증하면 통과하기 때문이다.

```
오케스트레이터  목차 · 용어 · 분모 고정 · 배분 · 충돌 판정 · 집필 · 원장 쓰기      항상 1
측량사          질문 1개를 SQL 로 잰다                                        질문 수만큼
정독자          표본을 직접 읽고 의미를 판정한다                                층 수만큼
반증자          채택된 판정을 깨러 간다                                       판정 수만큼
검사자 · 생독자   수치가 맞는지 · 절이 읽히는지                                  후보/절 수만큼
이음매 검사자    절과 절이 이야기가 되는지                                      항상 1
```

**집필과 원장 쓰기와 DB 쓰기는 안 나눈다.** 나머지는 나눈다.
팀 구성 · 배분 규약 · 라운드 · 동시성 함정은 `references/orchestration.md` 가 정본이다.

## 입력 전제

**로컬 폴더 하나.** 도메인·형식·출처를 가정하지 않는다.
GitHub 여부, 마크다운 여부, 한국어 여부 전부 알아내야 할 것이지 전제가 아니다.

## 언제 쓰지 않는가

- 코퍼스가 작고(수백 파일) 균질할 때. 그냥 다 임베딩하는 게 싸다.
- 청킹·검색 설계가 이미 정해졌고 그걸 바꿀 생각이 없을 때. 측정해도 결정이 안 바뀐다.
- 검색 품질이 아니라 인프라·비용만 문제일 때.

---

## 파이프라인

```
단계                          참조                        팀
S  폴더 탐색                  scripts/survey.py           1
0  기법 카탈로그 + 사전 조사     references/techniques.md    기법군 8 · 사전조사 축 5
L  적재 · 인덱스               scripts/load.py · index.py  1  (쓰기 락. 이 동안 아무도 못 읽는다)
1  측정 항목 설계              references/catalog.md       대표 파일 3~5
2  1차 측정                   scripts/q.py + queries/     질문 수만큼 (읽기 전용이라 충돌 없음)
3  LLM 판정                   references/llm-judgment.md  층 수만큼
4  가설 → 2차 교차검증          references/hypothesis-validation.md   H1~H4
5  기법 판정                   채택 · 보류 · 기각 + 근거     판정마다 반증자 1
6  확정 규칙 원본 재적용         queries/reapply_check.sql   1
7  원장에 기록                 scripts/ledger.py           1  (오케스트레이터 단독)
8  문서 검증                   references/verifying.md     절마다 생독자 1 + 이음매 1
        │
        └──── 보류·미해결이 다음 바퀴의 측정 항목이 된다 ────┘

⇒ 산출: 이 데이터에 맞춘 RAG 설계(청킹 단위 · 검색 방식 · 인덱싱 대상 · 적재 범위)
        정본은 원장(ledger.jsonl)이고 문서는 그것을 사람이 읽게 렌더한 것이다
        형태와 목차는 narrative.md · 표기는 reporting.md · 화면은 artifact.md · 검증은 verifying.md
```

**한 방향 파이프라인이 아니다.** 무엇을 측정할지 정하려면 기법 목록이 먼저 필요하고,
측정 결과가 다시 기법 판정을 뒤집는다.

**6단계를 건너뛰면 규칙이 종이 위에만 남는다.** 실제로 규칙을 전수 재적용하고 나서야
"마커 분할만으로는 길이 상한을 못 지킨다"가 드러나 슬라이딩 분할이 추가됐다.

### 바퀴는 시켜서 돌지 않는다

7단계에서 원장에 `next_measure` 를 적었으면 **거기서 멈추지 말고 그 항목으로 다음 바퀴를 시작한다.**
사람이 "그거 해줘" 할 때까지 기다리면 미해결이 쌓이기만 하고, 그게 1바퀴가 6단계를 통째로
건너뛴 채 닫힌 이유다. **다음 항목을 사람에게 묻지 않는다.** 물으면 그 순간 루프가 아니라 지시 대기다.
**한 번에 최대 네 바퀴다.**

멈춤 조건 다섯 · 다음 항목을 만드는 절차 · 바퀴 번호와 종료 판정은
`references/orchestration.md` 의 `바퀴`.

---

## 실행

`$S` 를 이 스킬의 `scripts/` 로 두고 프로젝트 루트에서 돌린다.

**자리를 먼저 정한다. 회차는 폴더가 아니라 파일명으로 가른다.**
`v1/` `v2/` 처럼 바퀴마다 폴더를 파면 같은 이름의 산출물이 여러 곳에 생겨
**어느 게 어느 바퀴 건지 폴더 위치로만 알게 된다.**
그리고 **회차와 무관한 것에는 회차 표시를 안 붙인다.** 코퍼스 DB 와 원장이 그렇다.
실제 사례에서 DB 를 1바퀴 폴더에 두었다가 2·3·4바퀴가 전부 그것을 쓰게 되어 이름과 실제가 어긋났다.

```
db/corpus.duckdb   코퍼스 DB.   회차 무관.  gitignore
ledger.jsonl       원장.        회차 무관.  정본이므로 gitignore 하지 않는다
out/R2.Q7.json     회차 산출물.  이름 앞에 회차.  gitignore
```

```bash
pip install duckdb

# S · 폴더에 뭐가 있는지. 구조 마커 후보와 대표 파일을 추천한다
python $S/survey.py <folder> -o out/survey.json

# L · 로컬 DB 로 적재. 1회만. 이후 측정은 쿼리만 추가한다
python $S/load.py <folder> --db db/corpus.duckdb --name mycorpus --glob "**/*.md"

# L · 줄머리 마커 인덱스 tok + meta 뷰. 1회만. 이후 마커 질문이 원문 전수 스캔을 안 한다
python $S/index.py db/corpus.duckdb

# 2 · 측정. 항목이 늘면 스크립트가 아니라 쿼리를 추가한다
#     --write 가 없으면 읽기 전용으로 열리므로 측량사 여럿이 동시에 돌아도 안전하다
#     산출 JSON 은 결과와 함께 sql 을 담는다. 문서의 쿼리 버튼이 그것을 그대로 꺼내 쓴다
python $S/q.py db/corpus.duckdb $S/queries/basics.sql
python $S/q.py db/corpus.duckdb $S/queries/outliers.sql
python $S/q.py db/corpus.duckdb $S/queries/markers.sql      # Q1 마커 일관성 · Q4 맥락 존재
python $S/q.py db/corpus.duckdb -e "SELECT ext, count(*) FROM doc GROUP BY 1" --json out/R1.ext.json

# 4 · 코퍼스가 둘 이상일 때. 참조가 상대 코퍼스에 실재하는지 (Q7)
python $S/q.py db/corpus.duckdb $S/queries/crosslink.sql

# 6 · 확정 규칙을 전수에 다시 돌린 결과를 검증한다
python $S/q.py db/corpus.duckdb $S/queries/reapply_check.sql

# 8 · 오류 1·5·6·8 유형 자동 검출. 나온 것은 후보다. 판정 절차는 references/verifying.md
python $S/extract.py report.html -o out/report.txt --claims out/report.claims.json
python $S/validate.py out/report.claims.json --sources out/ --peer out/other.claims.json

# 7 · 원장. 바퀴마다 파일이 새로 생기지 않고 레코드가 쌓인다. 첫 줄이 목차다
#     팀은 레코드 JSON 만 내고 넣는 것은 오케스트레이터 단독이다 (동시에 넣으면 레코드가 사라진다)
python $S/ledger.py init  ledger.jsonl
python $S/ledger.py add   ledger.jsonl --file out/R2.Q7.rec.json
python $S/ledger.py check ledger.jsonl                    # 분모 누락 · 현행 충돌 · 끊긴 사슬
python $S/ledger.py show  ledger.jsonl --q Q7 --all       # 그 항목의 바퀴 전체

# 8 · 문서. 판정표 · 미해결 · 종료 판정은 손으로 쓰지 않는다. 원장에서 뽑아 표시 사이에 끼운다
#     문서에 <!-- GEN:verdicts --> … <!-- /GEN:verdicts --> 를 두면 그 사이를 갈아 끼운다
python $S/render.py ledger.jsonl report.html
python $S/render.py ledger.jsonl report.html --check    # 어긋났는지만 본다. 어긋나면 종료코드 1

# load.py 를 고쳤으면 두 적재 경로가 같은 값을 내는지 확인한다
python $S/selftest.py <작은-폴더> --glob "**/*.md"
```

**적재되는 것**: `doc(rel_path, dir, name, ext, depth, sibling_n, encoding, load_ok,
hash, n_bytes, n_chars, n_lines, fm_raw, body)` + frontmatter 를 뺀 `doc_text.text` 뷰 +
분모가 될 값들이 담긴 `_meta`.
**파생 컬럼을 늘리지 않는다.** 파싱을 적재에 밀어넣으면 파서를 고칠 때마다 재적재해야 한다.

**`index.py` 가 덧붙이는 것**: 줄머리 마커 테이블 `tok` + `tok_skel` · `tok_variant` 뷰 +
frontmatter 를 키/값으로 편 `meta(doc_id, key, val)` 뷰.
**측정 비용을 줄이는 법과 그 경계 둘**(줄머리만 담는다 · 골격은 26자)은 `references/catalog.md`.

---

## 판정은 세 값이다

**채택 · 보류 · 기각.** 좋아 보여도 **우리 데이터로 효과를 재본 적 없으면 보류**다.

**채택 근거를 표시한다**: `실측` / `오답 비용 판단` / `이미 구현됨`.
실제 사례에서 채택 8건 중 실측이 근거인 것은 **4건**이었다.
나머지를 실측인 척 적으면 문서가 실제 데이터보다 단단해 보인다.
**반증자가 `확인 불가` 를 낸 판정은 `실측` 이 아니다.**

**모든 기법에 대응하는 측정이 있지는 않다.** 재랭킹·인용 강제·질의 라우팅처럼
데이터를 재도 안 갈리는 기법은 오답 비용으로 정한다. 억지로 측정을 만들어 붙이지 않는다.

---

## 반드시 지킬 것

**원본을 잰다. 청킹 후를 재지 않는다.**
청킹 후를 재면 자기 규칙의 사후 평가가 되어 순환 논리에 빠진다.
청킹 전략은 프로파일링 결과로 **나중에** 정한다.

**측정 항목을 고르는 기준은 하나다: 그 값이 설계를 바꾸는가.**
바꾸지 못하는 측정은 비용만 늘리고 문서를 흐린다.
모든 측정은 `측정 → 결과 → 결정` 세 줄로 쓴다. 결정이 안 나오면 넣지 않는다.

**표기가 갈리는 것을 먼저 하나로 맞춘다.**
같은 것이 두 가지로 적혀 있는데 한쪽만 세면 **틀렸다고 에러가 나지 않고 조용히 다른 값이 나온다.**
이게 이 스킬에서 가장 자주 나오는 사고이고, 걸리는 자리가 둘이다.

```
적재 시점   개행(CRLF/LF)      한 번 정하면 끝난다.  load.py 가 자동으로 하고 양쪽 값을 _meta 에 남긴다
측정 시점   마커 표기 변종       질문할 때마다 걸린다. outliers.sql [8] · markers.sql [5] 가 신고한다
```

실측으로 얼마나 갈리는지 보면 둘 다 무시할 수 없다.
CRLF 를 그대로 두면 문자 수가 **법령 +3.2%**(131,276,684 → 127,194,318) · **판례 +1.4%** 부풀려진다.
길이·비용 추정이 전부 이 값에 걸려 있다.
마커는 더 크다. `【주 문】` 한 형태로만 세면 보유율이 **70.2%** 인데 공백을 허용하면 **98.7%** 다.
28.5 포인트가 표기 하나에서 갈린다. `【이 유】` 는 3종 124,509건, `【피고,상고인】` 은 11종이다.

**측정하기 전에 변종부터 확인한다.** 값을 얻고 나서 확인하면 그 값이 맞는지 알 방법이 없다.

**수치를 뒤집는 판단은 원자료로 되짚는다.**
검토자를 여럿 돌리면 판정이 충돌한다. 다수결로 정하지 않고 오케스트레이터가 직접 센다.

---

## 참조 문서

| 파일 | 언제 읽는가 |
|---|---|
| `references/orchestration.md` | **일을 나누기 전에.** 팀 구성 · 배분 규약 · 라운드 · 동시성 함정 |
| `references/techniques.md` | 0단계. 후보 기법과 각 기법이 성립하는 조건 |
| `references/catalog.md` | 1단계. 측정 항목 8종 · 항목이 나오는 네 자리 · 전수 스캔 줄이기 |
| `references/llm-judgment.md` | 3단계. LLM 개입 5지점 · 표본 뽑는 법 · 흔적 형식 |
| `references/hypothesis-validation.md` | 4단계. 가설화 · 교차검증 · 기각 전 실패 표본 규칙 |
| `references/narrative.md` | **문서를 시작할 때.** 컨설팅 산출물의 형태 · 표준 목차 · 이음매 |
| `references/reporting.md` | 문서에 **수치와 표를 적을 때.** 오류 8유형 · 표기 규칙 |
| `references/artifact.md` | 문서를 **화면에 띄울 때.** 렌더 제약 · 게시 |
| `references/verifying.md` | 쓴 것을 **검증하고 고칠** 때. 검사기 · 후보 판정 · 읽히는지 · 이음매 |
| `scripts/queries/basics.sql` · `outliers.sql` | 2단계. 분모·길이 분포 · 예상 밖 값 8종 탐지 |
| `scripts/queries/markers.sql` | 2단계. Q1 구조 마커 일관성 · Q4 맥락 존재 여부 |
| `scripts/queries/crosslink.sql` | 4단계. Q7 코퍼스 간 연결. 참조가 상대에 실재하는지 |
| `scripts/queries/reapply_check.sql` | 6단계. 확정 규칙 재적용 결과 검증 |
