-- 6단계 · 확정 규칙 원본 재적용 검증. `q.py --write` 가 필요하다(설정 테이블을 만든다).
--
-- 이 단계를 건너뛰면 규칙이 종이 위에만 남는다. 실제 사례에서 재적용을 하고 나서야
-- "마커 분할만으로는 길이 상한을 못 지킨다"가 드러나 슬라이딩 분할이 추가됐다.
--
-- 계약 · 자기 청킹 규칙을 코드로 돌려 아래 테이블을 먼저 만든다.
--   chunk(doc_id INTEGER, seq INTEGER, n_chars BIGINT, marker VARCHAR)
--     doc_id   doc.doc_id 와 같은 값. 이게 어긋나면 [4] [5] 가 통째로 틀린다
--     seq      문서 안에서의 조각 순번 (1부터)
--     n_chars  조각의 문자 수. doc.n_chars 와 같은 기준(LF 정규화 후)으로 센다
--     marker   그 조각을 만든 마커 원문. 마커 없이 잘린 조각(슬라이딩 분할 등)은 NULL
--   컬럼을 더 넣어도 된다. 조각을 만들 때 특징을 한 번에 다 뽑아두면
--   나중 질문이 스캔 없이 끝난다.

-- [설정] 길이 상한 · 하한. 여기 두 값만 바꾼다.
--   상한은 임베딩 모델 컨텍스트와 검색 단위에서 온다. 하한은 단독으로 근거가 되는 최소 길이다
CREATE OR REPLACE TABLE rc_cfg AS SELECT 2000 AS max_chars, 50 AS min_chars;

-- [1] 재적용 규모. 아래 모든 비율의 분모다
SELECT (SELECT count(*) FROM doc WHERE load_ok) AS 원본_문서,
       (SELECT count(DISTINCT doc_id) FROM chunk) AS 조각이_나온_문서,
       (SELECT count(*) FROM chunk) AS 조각,
       (SELECT round(count(*) * 1.0 / nullif(count(DISTINCT doc_id), 0), 1) FROM chunk) AS 문서당_조각;

-- [2] 길이 상한 준수율. 마커 분할만으로는 상한을 못 지키는 경우가 많다.
--     넘는 조각이 남으면 규칙이 아직 안 끝난 것이다(슬라이딩 분할 등을 더한다)
SELECT count(*) AS 조각,
       count(*) FILTER (WHERE n_chars > (SELECT max_chars FROM rc_cfg)) AS 상한_초과,
       round(count(*) FILTER (WHERE n_chars > (SELECT max_chars FROM rc_cfg)) * 100.0
             / nullif(count(*), 0), 2) AS 초과_pct,
       max(n_chars) AS 최장_조각,
       (SELECT max_chars FROM rc_cfg) AS 상한
FROM chunk;

-- [3] 길이 하한. 짧은 쪽 꼬리가 진짜 과제인 경우가 많다.
--     버릴 대상인지 단독으로 완결된 조각인지는 수치로 안 정한다. 3단계 LLM 판정으로 넘긴다
SELECT count(*) AS 조각,
       count(*) FILTER (WHERE n_chars < (SELECT min_chars FROM rc_cfg)) AS 하한_미만,
       round(count(*) FILTER (WHERE n_chars < (SELECT min_chars FROM rc_cfg)) * 100.0
             / nullif(count(*), 0), 2) AS 미만_pct,
       min(n_chars) AS 최단_조각,
       (SELECT min_chars FROM rc_cfg) AS 하한
FROM chunk;

-- [4] 문자 보존율. 규칙이 원문을 흘리지 않았는지 본다.
--     100% 미만이면 어딘가를 못 담은 것이고, 겹침(오버랩) 규칙이면 100%를 넘는 게 정상이다.
--
--     **분모 함정**: 적재 범위(Q5)에서 뺀 것은 대개 문서가 아니라 문서 *안*에 있다
--     (부칙 · 머리말 · 삭제 단위). 그건 문서 단위 분모로는 안 잡혀서, 설계대로 뺀 것까지
--     "못 담았다"로 세어 보존율이 실제보다 훨씬 낮게 보인다.
--     실제 사례에서 전체 대비 63.3% 였는데, 설계상 뺀 것을 걷어낸 분모로는 92.7% 였다.
--     그래서 비율 하나로 판정하지 않는다. **못 담은 문자가 어디로 갔는지 끝까지 가른다.**
--     맨 오른쪽 값이 0 에 가까워질 때까지 설명이 끝난 게 아니다. 남으면 그게 규칙의 누수다.
SELECT (SELECT sum(n_chars) FROM chunk) AS 조각_문자,
       (SELECT sum(n_chars) FROM doc WHERE load_ok) AS 원본_문자_전체,
       round((SELECT sum(n_chars) FROM chunk) * 100.0
             / nullif((SELECT sum(n_chars) FROM doc WHERE load_ok), 0), 1) AS 보존율_전체_pct,
       (SELECT sum(n_chars) FROM doc WHERE load_ok)
         - (SELECT sum(n_chars) FROM chunk)                      AS 안_담긴_문자,
       (SELECT sum(length(fm_raw)) FROM doc WHERE load_ok)       AS 머리말_문자,
       (SELECT sum(d.n_chars) FROM doc d WHERE d.load_ok
          AND NOT EXISTS (SELECT 1 FROM chunk c WHERE c.doc_id = d.doc_id)) AS 누락문서_문자,
       (SELECT sum(n_chars) FROM doc WHERE load_ok)
         - (SELECT sum(n_chars) FROM chunk)
         - (SELECT sum(length(fm_raw)) FROM doc WHERE load_ok)
         - coalesce((SELECT sum(d.n_chars) FROM doc d WHERE d.load_ok
              AND NOT EXISTS (SELECT 1 FROM chunk c WHERE c.doc_id = d.doc_id)), 0)
                                                                 AS 아직_설명_안_된_문자;

-- [5] 누락 문서. 조각이 하나도 안 나온 문서다. 파서 버그가 여기서 드러난다.
--     의도한 제외(Q5)인지 규칙이 못 읽은 것인지 rel_path 를 열어 확인한다
SELECT count(*) AS 누락_문서,
       round(count(*) * 100.0 / nullif((SELECT count(*) FROM doc WHERE load_ok), 0), 1) AS 누락_pct,
       sum(n_chars) AS 누락_문자
FROM doc d WHERE d.load_ok AND NOT EXISTS (SELECT 1 FROM chunk c WHERE c.doc_id = d.doc_id);

-- [5] 누락 문서 표본. 길이 순으로 본다. 큰 문서가 통째로 빠지면 규칙이 아니라 버그다
SELECT d.rel_path, d.n_chars, d.n_lines
FROM doc d WHERE d.load_ok AND NOT EXISTS (SELECT 1 FROM chunk c WHERE c.doc_id = d.doc_id)
ORDER BY d.n_chars DESC LIMIT 15;

-- [6] 문서당 조각 수 분포. 평균만 보면 틀린다. p99 와 max 를 본다.
--     max 가 튀면 그 문서 하나가 검색 결과를 덮을 수 있다
SELECT count(*) AS 문서,
       min(n) AS mn,
       quantile_cont(n, 0.50)::BIGINT AS p50,
       quantile_cont(n, 0.95)::BIGINT AS p95,
       quantile_cont(n, 0.99)::BIGINT AS p99,
       max(n) AS mx
FROM (SELECT doc_id, count(*) AS n FROM chunk GROUP BY 1);

-- [6] 조각 길이 구간별 분포. 건수와 문자 수를 같이 낸다.
--     임베딩 비용은 건수가 아니라 문자 수에 걸려 있다
SELECT CASE WHEN n_chars <    50 THEN 'a. <50'
            WHEN n_chars <   200 THEN 'b. 50-200'
            WHEN n_chars <  1000 THEN 'c. 200-1K'
            WHEN n_chars <  2000 THEN 'd. 1K-2K'
            ELSE                      'e. 2K+' END AS bucket,
       count(*) AS 조각,
       round(count(*) * 100.0 / sum(count(*)) OVER (), 1) AS 조각_pct,
       sum(n_chars) AS 문자,
       round(sum(n_chars) * 100.0 / sum(sum(n_chars)) OVER (), 1) AS 문자_pct
FROM chunk GROUP BY 1 ORDER BY 1;

-- [7] 어느 규칙이 조각을 만들었는가. marker 가 NULL 인 몫이 마커 분할로 못 자른 부분이다.
--     그 몫이 크면 구조 기반 청킹 채택 근거(Q1)가 실제로는 약한 것이다
SELECT coalesce(regexp_replace(regexp_replace(marker, '[0-9]+', '<N>', 'g'), '\s+', ' ', 'g'),
                '(마커 없음)') AS 마커_골격,
       count(*) AS 조각,
       round(count(*) * 100.0 / sum(count(*)) OVER (), 1) AS 조각_pct,
       quantile_cont(n_chars, 0.50)::BIGINT AS p50,
       max(n_chars) AS mx
FROM chunk GROUP BY 1 ORDER BY 조각 DESC LIMIT 20;

-- [8] 상한 초과 표본. 어떤 문서의 어느 조각이 안 잘렸는지 직접 본다.
--     여기 걸린 것이 다음 바퀴의 규칙 수정 입력이다
SELECT c.doc_id, d.rel_path, c.seq, c.n_chars, c.marker
FROM chunk c LEFT JOIN doc d USING (doc_id)
WHERE c.n_chars > (SELECT max_chars FROM rc_cfg)
ORDER BY c.n_chars DESC LIMIT 15;
