# SQL

The rule layer expressed as SQL, the way it would run against a bank's
warehouse rather than in a pandas process.

These are not illustrations. `tests/test_sql.py` asserts that each query returns
**exactly the same transactions** as the corresponding function in
`src/rules.py`, so the two implementations cannot drift.

| Query | What it does |
|---|---|
| `01_structuring.sql` | Near-threshold bursts, using two window functions to find payments inside *any* qualifying seven-day window. Checks both the sender and the beneficiary side |
| `02_rapid_movement.sql` | Pass-through detection: credits where 80%+ leaves the account within 24 hours, returning both legs |
| `03_high_risk_country.sql` | Jurisdiction screen, with which leg caused the exposure |
| `04_rule_contribution.sql` | The project's central finding: alerts each rule raises that no other rule raises, and cases each rule finds that no other rule finds |

## Running them

```bash
python src/sql_runner.py        # runs every query and prints the first rows
```

SQLite, which ships with Python, so nothing needs installing. The loader puts
timestamps in as epoch seconds because SQLite window frames do arithmetic on
numbers: `RANGE BETWEEN CURRENT ROW AND 604800 FOLLOWING` is then exactly seven
days.

## The interesting one

`04_rule_contribution.sql` answers the question that drives the whole project.
Judging a rule by its own recall flatters it, because a rule that only ever
re-finds cases another rule already caught is pure alert volume. The last two
columns separate the two:

```
             rule  alerts  cases_caught  precision_pct  alerts_only_this_rule  cases_no_other_rule_found
high_risk_country    5178            13           0.25                   5158                          0
      structuring     100           100         100.00                     98                         98
   rapid_movement      80            40          50.00                     61                         25
     round_amount      49             2           4.08                     44                          0
```

One screen raises 5,158 alerts nobody else raises and finds nothing nobody else
found.

Only this query reads the labels table, because it is evaluation rather than
detection. A test enforces that the other three never touch it.
