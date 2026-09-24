-- Which rules earn their alert volume?
--
-- This is the query behind the project's central finding. Judging a rule by its
-- own recall flatters it: a rule that only ever re-finds cases another rule
-- already caught is pure alert volume, however many cases it "detects".
--
-- The last column is the one that matters: alerts this rule raises that no other
-- rule raises. Run it and the jurisdiction screen's position becomes obvious.
--
-- NOTE: this query reads the labels, so it belongs to evaluation, not detection.

WITH near_threshold AS (
    SELECT transaction_id, sender_account, receiver_account, ts
    FROM transactions WHERE amount >= 7000 AND amount < 10000
),
structuring AS (
    SELECT DISTINCT transaction_id FROM (
        SELECT transaction_id,
               MAX(CASE WHEN c >= 3 THEN 1 ELSE 0 END) OVER (
                   PARTITION BY account ORDER BY ts
                   RANGE BETWEEN 604800 PRECEDING AND CURRENT ROW) AS in_burst
        FROM (
            SELECT transaction_id, receiver_account AS account, ts,
                   COUNT(*) OVER (PARTITION BY receiver_account ORDER BY ts
                       RANGE BETWEEN CURRENT ROW AND 604800 FOLLOWING) AS c
            FROM near_threshold
            UNION ALL
            SELECT transaction_id, sender_account AS account, ts,
                   COUNT(*) OVER (PARTITION BY sender_account ORDER BY ts
                       RANGE BETWEEN CURRENT ROW AND 604800 FOLLOWING) AS c
            FROM near_threshold
        )
    ) WHERE in_burst = 1
),
credits AS (
    SELECT transaction_id, receiver_account AS account, amount, ts
    FROM transactions WHERE amount >= 1000
),
passthrough AS (
    SELECT c.transaction_id AS credit_id, c.account, c.ts
    FROM credits c
    JOIN transactions d ON d.sender_account = c.account
                       AND d.ts > c.ts AND d.ts <= c.ts + 86400
    GROUP BY c.transaction_id, c.account, c.amount, c.ts
    HAVING SUM(d.amount) >= 0.80 * c.amount
),
rapid_movement AS (
    SELECT credit_id AS transaction_id FROM passthrough
    UNION
    SELECT d.transaction_id FROM passthrough p
    JOIN transactions d ON d.sender_account = p.account
                       AND d.ts > p.ts AND d.ts <= p.ts + 86400
),
high_risk_country AS (
    SELECT transaction_id FROM transactions
    WHERE sender_country   IN ('Cyprus','Malta','Seychelles','Panama','Cayman Islands')
       OR receiver_country IN ('Cyprus','Malta','Seychelles','Panama','Cayman Islands')
),
round_amount AS (
    SELECT transaction_id FROM transactions
    WHERE amount = CAST(amount AS INTEGER) AND amount >= 1000
),

-- One row per (transaction, rule that fired).
fired AS (
    SELECT transaction_id, 'structuring'       AS rule FROM structuring
    UNION ALL SELECT transaction_id, 'rapid_movement'    FROM rapid_movement
    UNION ALL SELECT transaction_id, 'high_risk_country' FROM high_risk_country
    UNION ALL SELECT transaction_id, 'round_amount'      FROM round_amount
),
rule_count AS (
    SELECT transaction_id, COUNT(DISTINCT rule) AS rules_fired
    FROM fired GROUP BY transaction_id
)

SELECT f.rule,
       COUNT(*)                                                  AS alerts,
       SUM(l.is_laundering_pattern)                              AS cases_caught,
       ROUND(100.0 * SUM(l.is_laundering_pattern) / COUNT(*), 2) AS precision_pct,
       SUM(CASE WHEN rc.rules_fired = 1 THEN 1 ELSE 0 END)       AS alerts_only_this_rule,
       SUM(CASE WHEN rc.rules_fired = 1 THEN l.is_laundering_pattern ELSE 0 END)
                                                                 AS cases_no_other_rule_found
FROM       fired f
JOIN       rule_count rc ON rc.transaction_id = f.transaction_id
LEFT JOIN  labels l      ON l.transaction_id = f.transaction_id
GROUP BY   f.rule
ORDER BY   alerts DESC;
