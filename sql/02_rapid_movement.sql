-- Rapid fund movement: money arriving in an account and leaving almost at once.
--
-- For every credit of GBP 1,000 or more, sum the debits from that same account
-- in the following 24 hours. If they return 80% or more of the credit, the
-- account was a conduit rather than a destination, and BOTH legs are flagged:
-- an analyst needs the pair to see the pattern.
--
-- Mirrors rule_rapid_movement() in src/rules.py.

WITH credits AS (
    SELECT transaction_id, receiver_account AS account, amount, ts
    FROM   transactions
    WHERE  amount >= 1000
),

-- Each credit paired with the debits that left the same account within 24h.
passthrough AS (
    SELECT c.transaction_id AS credit_id,
           c.account,
           c.amount         AS amount_in,
           SUM(d.amount)    AS amount_out
    FROM   credits c
    JOIN   transactions d
      ON   d.sender_account = c.account
     AND   d.ts >  c.ts
     AND   d.ts <= c.ts + 86400          -- 24 hours
    GROUP  BY c.transaction_id, c.account, c.amount, c.ts
    HAVING SUM(d.amount) >= 0.80 * c.amount
),

-- Both legs: the credit itself, and every debit inside its window.
legs AS (
    SELECT credit_id AS transaction_id FROM passthrough
    UNION
    SELECT d.transaction_id
    FROM   passthrough p
    JOIN   credits c ON c.transaction_id = p.credit_id
    JOIN   transactions d
      ON   d.sender_account = p.account
     AND   d.ts >  c.ts
     AND   d.ts <= c.ts + 86400
)

SELECT t.transaction_id,
       t.timestamp,
       t.sender_account,
       t.receiver_account,
       ROUND(t.amount, 2) AS amount
FROM   legs l
JOIN   transactions t ON t.transaction_id = l.transaction_id
ORDER  BY t.timestamp;
