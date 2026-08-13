-- 적재 요약. 여기 값이 이후 모든 비율의 분모가 된다
SELECT k, v FROM _meta;

-- 확장자별 파일 수와 분량
SELECT ext, count(*) AS files, sum(n_chars) AS chars,
       round(sum(n_chars) * 100.0 / sum(sum(n_chars)) OVER (), 1) AS chars_pct
FROM doc WHERE load_ok GROUP BY 1 ORDER BY chars DESC;

-- Q2 · 문서 길이 분포. 평균·중앙값만 보면 틀린다. p99 와 max 를 본다
SELECT count(*) AS n,
       min(n_chars) AS mn,
       quantile_cont(n_chars, 0.50)::BIGINT AS p50,
       quantile_cont(n_chars, 0.95)::BIGINT AS p95,
       quantile_cont(n_chars, 0.99)::BIGINT AS p99,
       max(n_chars) AS mx,
       sum(n_chars) AS total
FROM doc WHERE load_ok;

-- 길이 구간별 분포. 짧은 쪽 꼬리가 진짜 과제인 경우가 많다
SELECT CASE WHEN n_chars <     200 THEN 'a. <200'
            WHEN n_chars <   1000 THEN 'b. 200-1K'
            WHEN n_chars <   8000 THEN 'c. 1K-8K'
            WHEN n_chars <  50000 THEN 'd. 8K-50K'
            ELSE                       'e. 50K+' END AS bucket,
       count(*) AS files,
       round(count(*) * 100.0 / sum(count(*)) OVER (), 1) AS files_pct,
       sum(n_chars) AS chars,
       round(sum(n_chars) * 100.0 / sum(sum(n_chars)) OVER (), 1) AS chars_pct
FROM doc WHERE load_ok GROUP BY 1 ORDER BY 1;

-- Q8 · 같은 폴더에 문서가 여럿인가. 계층·위임 관계는 형제 문서에서 드러난다
SELECT sibling_n, count(DISTINCT dir) AS dirs, count(*) AS files
FROM doc GROUP BY 1 ORDER BY 1;

-- Q8 · 흔한 파일 조합. 대표 파일 선정과 중복·버전 판단의 근거
SELECT files, count(*) AS dirs FROM (
  SELECT dir, string_agg(name, ' · ' ORDER BY name) AS files
  FROM doc WHERE sibling_n BETWEEN 2 AND 6 GROUP BY dir
) GROUP BY 1 ORDER BY dirs DESC LIMIT 10;

-- Q8 · 같은 이름이 여러 폴더에 있는가 (중복·버전 후보)
SELECT name, count(*) AS n FROM doc
GROUP BY 1 HAVING n > 1 ORDER BY n DESC LIMIT 15;
