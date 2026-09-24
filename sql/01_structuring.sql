-- Structuring: repeated payments sitting just under the reporting threshold.
--
-- A payment is flagged when it falls inside ANY seven-day window holding three
-- or more near-threshold payments for the same account. The window need not
-- start or end at the payment itself: the middle payment of a three-payment
-- burst belongs to a qualifying window without anchoring one.
--
-- Checked on BOTH sides. Classic structuring is one sender splitting a deposit;
-- the pattern in this book is many senders funnelling into one beneficiary, and
-- a sender-only rule misses most of it.
--
-- Mirrors rule_structuring() in src/rules.py; tests/test_sql.py asserts they
-- return the same transactions.

WITH near_threshold AS (
    SELECT transaction_id, sender_account, receiver_account, amount, ts
    FROM   transactions
    WHERE  amount >= 10000 * 0.70      -- 70% of the threshold
      AND  amount <  10000
),

-- For every payment, how many near-threshold payments fall in the seven days
-- starting at it. A payment with 3+ ahead of it STARTS a qualifying window.
windows_by_beneficiary AS (
    SELECT transaction_id, receiver_account AS account, ts,
           COUNT(*) OVER (
               PARTITION BY receiver_account ORDER BY ts
               RANGE BETWEEN CURRENT ROW AND 604800 FOLLOWING
           ) AS payments_in_window
    FROM near_threshold
),
windows_by_sender AS (
    SELECT transaction_id, sender_account AS account, ts,
           COUNT(*) OVER (
               PARTITION BY sender_account ORDER BY ts
               RANGE BETWEEN CURRENT ROW AND 604800 FOLLOWING
           ) AS payments_in_window
    FROM near_threshold
),
window_starts AS (
    SELECT * FROM windows_by_beneficiary
    UNION ALL
    SELECT * FROM windows_by_sender
),

-- A payment is in a burst when a qualifying window STARTED within the seven
-- days before it, itself included.
flagged AS (
    SELECT transaction_id, account,
           MAX(CASE WHEN payments_in_window >= 3 THEN 1 ELSE 0 END) OVER (
               PARTITION BY account ORDER BY ts
               RANGE BETWEEN 604800 PRECEDING AND CURRENT ROW
           ) AS in_burst
    FROM window_starts
)

SELECT DISTINCT t.transaction_id,
       t.timestamp,
       t.sender_account,
       t.receiver_account,
       ROUND(t.amount, 2) AS amount
FROM   flagged f
JOIN   transactions t ON t.transaction_id = f.transaction_id
WHERE  f.in_burst = 1
ORDER  BY t.timestamp;
