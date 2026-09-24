-- High-risk jurisdiction screen: either leg touches an offshore centre.
--
-- The list is derived from the portfolio rather than assumed. These five
-- countries are the long tail of the customer book (18-34 accounts each against
-- roughly 300 for every mainstream country), which is the shape a high-risk
-- list has against a retail book.
--
-- This is the noisiest rule in the system by a wide margin. 04_rule_contribution
-- quantifies what it actually buys.

SELECT t.transaction_id,
       t.timestamp,
       t.sender_country,
       t.receiver_country,
       ROUND(t.amount, 2) AS amount,
       CASE WHEN t.sender_country   IN ('Cyprus','Malta','Seychelles','Panama','Cayman Islands')
             AND t.receiver_country IN ('Cyprus','Malta','Seychelles','Panama','Cayman Islands')
            THEN 'both legs'
            WHEN t.sender_country   IN ('Cyprus','Malta','Seychelles','Panama','Cayman Islands')
            THEN 'sender'
            ELSE 'receiver'
       END AS exposure
FROM   transactions t
WHERE  t.sender_country   IN ('Cyprus','Malta','Seychelles','Panama','Cayman Islands')
   OR  t.receiver_country IN ('Cyprus','Malta','Seychelles','Panama','Cayman Islands')
ORDER  BY t.timestamp;
