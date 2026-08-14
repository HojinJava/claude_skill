-- 2단계 · Q1 문서를 자르는 구조 마커가 일관된가 · Q4 조각 앞에 붙일 맥락이 원문에 있는가.
-- index.py 가 만든 tok · tok_skel · tok_variant 만 읽는다. 원문(doc.body) 전수 스캔을 새로 걸지 않는다.
-- 그게 tok 을 만든 이유다. 여기에 원문 정규식을 추가하면 이득이 사라진다.
-- 깊이(tok.hlevel)는 줄머리 `#` 개수다. 헤딩이 없는 코퍼스는 hlevel 이 전부 0이라
-- [3]~[7] 이 빈 표로 나온다. 그때는 [1] 의 골격 접두를 깊이 대신 쓴다.

-- [1] Q1 · 골격별 출현 파일 비율. 줄 수가 아니라 docs_pct 를 먼저 본다.
--     파일의 몇 %가 그 마커를 갖는가가 구조 기반 청킹 채택 여부를 가른다
SELECT skel, lines, docs, docs_pct FROM tok_skel
ORDER BY docs DESC, lines DESC LIMIT 25;

-- [2] Q1 · 골격 커버리지. 상위 k개 골격만 파서에 넣으면 마커 줄의 몇 %를 덮는가.
--     꼬리가 길면 규칙을 늘려도 안 덮인다. 파서 규칙 개수를 여기서 정한다
WITH r AS (
  SELECT lines, row_number() OVER (ORDER BY lines DESC) AS rk, sum(lines) OVER () AS tot
  FROM tok_skel
)
SELECT k AS 상위_골격수,
       (SELECT count(*) FROM tok_skel) AS 전체_골격수,
       sum(r.lines) FILTER (WHERE r.rk <= k) AS 덮는_줄,
       round(sum(r.lines) FILTER (WHERE r.rk <= k) * 100.0 / max(r.tot), 1) AS 줄_pct
FROM r, (VALUES (5), (10), (20), (50), (100), (500)) v(k)
GROUP BY k ORDER BY k;

-- [3] Q1 · 깊이 사용률. 마커 계층이 여러 단이어도 실제로는 한 단만 쓸 수 있다.
--     실제 사례에서 파일의 64.3%가 최소 단위만 써서 5단 파서를 폐기했다.
--     분모는 적재 성공 문서 전체다. 헤딩이 없는 문서는 행이 없으므로 합이 100% 미만일 수 있다
WITH d AS (
  SELECT doc_id, count(DISTINCT hlevel) AS n_lv, min(hlevel) AS top_lv, max(hlevel) AS leaf_lv
  FROM tok WHERE hlevel > 0 GROUP BY 1
)
SELECT n_lv AS 사용_깊이_단수, count(*) AS docs,
       round(count(*) * 100.0 / (SELECT count(*) FROM doc WHERE load_ok), 1) AS docs_pct,
       min(top_lv) AS 가장_얕은_단, max(leaf_lv) AS 가장_깊은_단
FROM d GROUP BY 1 ORDER BY 1;

-- [4] Q1 · 실제로 쓰인 깊이 조합. 단수만 보면 어느 단을 건너뛰었는지 안 보인다.
--     `1·2·5` 처럼 중간이 비면 그 단을 가정한 파서가 조용히 빈다
WITH lv AS (SELECT DISTINCT doc_id, hlevel FROM tok WHERE hlevel > 0),
     d AS (SELECT doc_id, string_agg(hlevel::VARCHAR, '·' ORDER BY hlevel) AS used FROM lv GROUP BY 1)
SELECT used AS 사용_깊이, count(*) AS docs,
       round(count(*) * 100.0 / (SELECT count(*) FROM doc WHERE load_ok), 1) AS docs_pct
FROM d GROUP BY 1 ORDER BY docs DESC LIMIT 15;

-- [5] Q1 · 표기 변종. 공백만 다른 같은 마커다.
--     한 형태로 정규식을 쓰면 나머지를 통째로 놓쳐 측정이 조용히 틀린다
SELECT norm, variants, lines, docs, forms
FROM tok_variant ORDER BY lines DESC LIMIT 20;

-- [6] Q4 · 하위 조각 위에 상위 마커가 실제로 있는가 (조각 기준).
--     있으면 문자열로 붙이면 되고(공짜), 없으면 LLM 생성을 검토해야 한다(비쌈).
--     상위 = 그 문서가 쓴 가장 얕은 단, 하위 = 가장 깊은 단. 한 단만 쓰는 문서는 제외한다
WITH lv AS (
  SELECT doc_id, min(hlevel) AS top_lv, max(hlevel) AS leaf_lv
  FROM tok WHERE hlevel > 0 GROUP BY 1 HAVING min(hlevel) < max(hlevel)
),
x AS (
  SELECT t.doc_id, t.hlevel, lv.leaf_lv,
         last_value(CASE WHEN t.hlevel = lv.top_lv THEN t.raw END IGNORE NULLS)
           OVER (PARTITION BY t.doc_id ORDER BY t.seq ROWS UNBOUNDED PRECEDING) AS carried
  FROM tok t JOIN lv USING (doc_id) WHERE t.hlevel > 0
)
SELECT count(*) AS 하위조각,
       count(carried) AS 상위마커_선행,
       round(count(carried) * 100.0 / nullif(count(*), 0), 1) AS 맥락존재_pct,
       count(DISTINCT doc_id) AS 다단_문서
FROM x WHERE hlevel = leaf_lv;

-- [7] Q4 · 문서당 상위 마커 개수. 1개면 문서마다 붙일 문자열이 하나로 정해진다.
--     여러 개면 조각마다 직전 상위 마커를 찾아 붙여야 한다(구현 비용이 다르다)
WITH lv AS (
  SELECT doc_id, min(hlevel) AS top_lv
  FROM tok WHERE hlevel > 0 GROUP BY 1 HAVING min(hlevel) < max(hlevel)
),
c AS (
  SELECT t.doc_id, count(*) AS n_top
  FROM tok t JOIN lv USING (doc_id) WHERE t.hlevel = lv.top_lv GROUP BY 1
)
SELECT n_top AS 문서당_상위마커수, count(*) AS docs,
       round(count(*) * 100.0 / sum(count(*)) OVER (), 1) AS docs_pct
FROM c GROUP BY 1 ORDER BY 1 LIMIT 15;

-- [8] Q4 · 붙일 맥락의 실물. 수치만 보고 정하지 않는다.
--     상위 마커 원문이 조각 앞에 붙일 값으로 쓸 만한지 눈으로 확인한다
WITH lv AS (
  SELECT doc_id, min(hlevel) AS top_lv, max(hlevel) AS leaf_lv
  FROM tok WHERE hlevel > 0 GROUP BY 1 HAVING min(hlevel) < max(hlevel)
),
x AS (
  SELECT t.doc_id, t.seq, t.raw, t.hlevel, lv.leaf_lv,
         last_value(CASE WHEN t.hlevel = lv.top_lv THEN t.raw END IGNORE NULLS)
           OVER (PARTITION BY t.doc_id ORDER BY t.seq ROWS UNBOUNDED PRECEDING) AS carried
  FROM tok t JOIN lv USING (doc_id) WHERE t.hlevel > 0
)
SELECT doc_id, carried AS 붙일_맥락, raw AS 조각_머리
FROM x WHERE hlevel = leaf_lv ORDER BY doc_id, seq LIMIT 12;
