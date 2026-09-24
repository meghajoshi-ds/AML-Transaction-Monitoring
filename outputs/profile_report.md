# Data profile - raw transactions

60,154 rows x 10 columns. Generated before any cleaning.

## Missing values

|                |   missing |
|:---------------|----------:|
| amount         |        60 |
| sender_country |       601 |
| channel        |      1203 |

## Duplicate transaction_id

- 15 ids appear more than once, covering 30 rows.
- Rows that are identical across **all 10 columns**: 28.

Sample of the duplicated ids:

| transaction_id   | timestamp           | sender_account   | receiver_account   |   amount | currency   | sender_country   | receiver_country   | transaction_type   | channel         |
|:-----------------|:--------------------|:-----------------|:-------------------|---------:|:-----------|:-----------------|:-------------------|:-------------------|:----------------|
| TXN0003384       | 2025-09-20 03:26:04 | ACC102970        | ACC101671          |    91.83 | GBP        | Germany          | France             | payment            | mobile_app      |
| TXN0003384       | 2025-09-20 03:26:04 | ACC102970        | ACC101671          |    91.83 | GBP        | Germany          | France             | payment            | mobile_app      |
| TXN0007315       | 2025-02-25 14:18:00 | ACC100293        | ACC101583          |   150    | GBP        | United States    | United States      | deposit            | card_payment    |
| TXN0007315       | 2025-02-25 14:18:00 | ACC100293        | ACC101583          |   150    | GBP        | United States    | United States      | deposit            | card_payment    |
| TXN0010404       | 2025-11-17 21:55:37 | ACC101320        | ACC100044          |   324.47 | GBP        | Canada           | Germany            | transfer           | online_transfer |
| TXN0010404       | 2025-11-17 21:55:37 | ACC101320        | ACC100044          |   324.47 | GBP        | Canada           | Germany            | transfer           | online_transfer |
| TXN0015648       | 2025-01-29 00:49:37 | ACC102426        | ACC102721          |   444.3  | GBP        | Ireland          | United States      | deposit            | mobile_app      |
| TXN0015648       | 2025-01-29 00:49:37 | ACC102426        | ACC102721          |   444.3  | GBP        | Ireland          | United States      | deposit            | mobile_app      |
| TXN0019781       | 2025-08-05 19:38:48 | ACC102804        | ACC102972          |  2350.44 | GBP        | Spain            | France             | payment            | online_transfer |
| TXN0019781       | 2025-08-05 19:38:48 | ACC102804        | ACC102972          |  2350.44 | GBP        | Spain            | France             | payment            | online_transfer |

## Negative amounts

- 20 rows with amount < 0, range -3022.10 to -45.18.

Transaction types they carry:

| transaction_type   |   rows |
|:-------------------|-------:|
| deposit            |      8 |
| withdrawal         |      7 |
| payment            |      3 |
| transfer           |      2 |

## Amount distribution

|       |     amount |
|:------|-----------:|
| count |  60074     |
| mean  |    488.4   |
| std   |   1998.33  |
| min   |      2.65  |
| 50%   |    245.005 |
| 90%   |   1000.38  |
| 99%   |   3436.8   |
| 99.9% |  12288.1   |
| max   | 373928     |

- Rows above GBP 50,000: 5
- Largest single amount: GBP 373,928.04

## Timestamp formats

- `YYYY-MM-DD HH:MM:SS`: 57,146
- `DD/MM/YYYY HH:MM`: 3,008
- In the slash-format rows the first component ranges 1-31, i.e. >12 occurs, confirming day-first not month-first.

## Country value formatting

|                |   rows |
|:---------------|-------:|
| Spain          |  13364 |
| France         |  13140 |
| Ireland        |  12510 |
| Netherlands    |  12309 |
| Canada         |  12219 |
| Germany        |  12132 |
| Australia      |  12029 |
| United States  |  10430 |
| United Kingdom |   9925 |
| Cyprus         |   1394 |
| Malta          |   1318 |
| Seychelles     |   1072 |
| US             |    835 |
| united states  |    821 |
| Panama         |    816 |
| USA            |    815 |
| U.K.           |    806 |
| U.S.A.         |    800 |
| uk             |    770 |
| United kingdom |    765 |
| UK             |    752 |
| Cayman Islands |    685 |
| nan            |    601 |

Canonical country names in the customer file: ['Australia', 'Canada', 'Cayman Islands', 'Cyprus', 'France', 'Germany', 'Ireland', 'Malta', 'Netherlands', 'Panama', 'Seychelles', 'Spain', 'United Kingdom', 'United States']

## Categorical columns


**currency**

| currency   |   rows |
|:-----------|-------:|
| GBP        |  60154 |

**transaction_type**

| transaction_type   |   rows |
|:-------------------|-------:|
| transfer           |  15235 |
| deposit            |  14984 |
| withdrawal         |  14971 |
| payment            |  14925 |
| wire_transfer      |     39 |

**channel**

| channel         |   rows |
|:----------------|-------:|
| online_transfer |  11860 |
| wire_transfer   |  11824 |
| mobile_app      |  11790 |
| atm_withdrawal  |  11774 |
| card_payment    |  11703 |
| nan             |   1203 |

## transaction_id prefix check

The id column is supposed to be an opaque reference. It is not:

| transaction_id   |   rows |
|:-----------------|-------:|
| TXN0             |  60014 |
| TXNS             |    101 |
| TXNR             |     39 |

`TXNS`/`TXNR` are the injected structuring and rapid-movement rows. Any feature derived from the id would score perfectly and mean nothing, so the column is dropped before modelling.

## Account-level activity

- Distinct sending accounts: 3,000
- Transactions sent per account: median 20, p99 32, max 43
- Accounts appearing in transactions but missing from the customer file: 0
