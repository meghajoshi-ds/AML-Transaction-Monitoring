# Decisions log

Every judgement call made in this project, with the evidence behind it. The
numbers cited come from `outputs/profile_report.md` and `outputs/metrics.json`.

---

### 1. Mixed timestamp formats — parsed by subset, not by inference

3,008 rows use `DD/MM/YYYY HH:MM`, 57,146 use `YYYY-MM-DD HH:MM:SS`.

I split on the presence of `/` and parsed each subset with an explicit format
rather than letting `pd.to_datetime` infer. Inference on this column silently
reads `03/04/2025` as 4 March in some rows and 3 April in others. I confirmed
day-first by checking the first component's range in those rows: it runs 1–31,
so it cannot be a month. All 60,154 rows parsed; zero `NaT`.

### 2. Duplicate transaction IDs — genuine replays, removed in two passes

15 IDs appear twice. 14 pairs are identical across all ten columns. The 15th,
`TXN0029863`, differs *only* in timestamp formatting: `2025-11-21 06:30:52`
versus `21/11/2025 06:30` — the same event from a feed that truncates seconds.

That one detail decides the order of operations: **de-duplicate after parsing
timestamps, not before**, and match on a business key (same counterparties,
amount, type, same minute) rather than on exact row equality. Keeping the
higher-precision row removes all 15 replays and leaves zero duplicate IDs.

Why it matters beyond tidiness: replayed debits inflate account velocity and
would manufacture structuring alerts on their own.

### 3. Negative amounts — quarantined, not deleted and not absolute-valued

20 rows carry amounts from −£45 to −£3,022. The tempting read is "refunds," but
they are spread across all four transaction types, including 8 **deposits**, and
a negative deposit is not a refund. The schema has no reversal linkage
(no `original_transaction_id`), so there is nothing to validate a refund against.

I could not justify flipping the sign — that invents a transaction that may not
have happened. I moved them to `outputs/quarantined_rows.csv` with a reason
code, which is what a real pipeline does: excluded from detection, visible to
data-quality reporting, never silently dropped. Same treatment for the 60 rows
with missing `amount`, which no amount-based rule can score.

Verified afterwards: **none of the 80 quarantined rows is a known case**, so the
recall ceiling stays at 100%. Had one been, the pipeline could never have
recovered it, and the write-up would have to say so.

### 4. Missing `sender_country` — imputed from the customer file

601 rows. Before imputing I tested the assumption: where `sender_country` *is*
present, it equals the sending account's `home_country` in **99.79%** of rows.
That makes the customer file a reliable source, so the gap is filled by join.

Missing `channel` (1,203 rows) is handled differently — filled with `"unknown"`
as its own category. A failed feed is information, and there is no second source
to recover the true value from, so guessing would be fabrication.

### 5. Country name variants — folded to canonical spellings

`US` / `USA` / `U.S.A.` / `united states` and six spellings of the UK. Left
alone, any `groupby` or jurisdiction rule silently splits one country into eight
and under-counts it. Mapped to the 14 canonical names used in the customer file.

### 6. Outliers — kept, uncapped

Five transactions exceed £50,000, topping out at £373,928 against a median of
£245. Standard practice would winsorise. **In AML that deletes the thing you are
looking for** — a large unexplained transfer is signal, not noise. They are kept
at full value. The model sees them through `log_amount` and a per-account
z-score, so they inform the anomaly score without dominating the scale.

### 7. Two leakage paths closed before modelling

This is the decision I would lead with in an interview, because it is the one
that would have quietly invalidated the entire result.

**Path one — the ID column.** 60,014 rows are prefixed `TXN0`, but 101 are
`TXNS` (structuring) and 39 are `TXNR` (rapid movement) — exactly 140, exactly
matching the label file. The generator labelled its own answers in the primary
key. `transaction_id` is carried as a reference for the case list and never
reaches a feature matrix.

**Path two — a stray category.** `transaction_type` has an undocumented fifth
value, `wire_transfer`, on precisely 39 rows — the same 39 rapid-movement rows,
all UK→UK, all £15k–£39k. One-hot encoded, that single dummy is a perfect
detector of an injected pattern. It is folded into `transfer`, which is what it
actually is.

A model left holding either of these scores near-perfectly and means nothing.

### 8. Structuring checked on both sides of the transaction

The textbook rule watches one sender splitting a deposit. Profiling the
£9,000–£9,999 band showed the opposite shape: the busiest *beneficiary*
accounts receive 10–12 near-threshold payments while no single *sender* exceeds
4. That is funnelling — many senders into one account.

The rule therefore runs over both `sender_account` and `receiver_account`.
A sender-only rule would have missed most of the pattern. This was found in the
raw data, without labels.

### 9. High-risk jurisdiction list — derived from the portfolio, not assumed

Cyprus, Malta, Seychelles, Panama, Cayman Islands: the long tail of the customer
book (18–34 accounts each, versus ~300 for every mainstream country). Chosen
because that is the shape a high-risk list has against a retail portfolio, not
because of any political judgement.

### 10. The anomaly model deliberately cannot see country risk

Isolation Forest gets amount shape, timing, velocity, counterparty spread and
account tenure — but **no high-risk-country feature**, even though it would
raise its standalone score. That signal already has a rule. Keeping it out means
the two layers fail independently, which is the only reason corroborating one
against the other adds information.

### 11. Unsupervised, not supervised — on purpose

With 139 labelled cases a classifier would score well and be useless. Real banks
have no trustworthy transaction-level laundering labels, only closed alerts
(mostly "no further action"). Training on the labels here would model this
generator, not laundering. The labels are opened in `evaluate.py` and nowhere
else.

### 12. The operating threshold is a policy choice, not an optimum

Pure optimisation degenerates. Because the broad screens contribute **zero**
unique detections, "fewest alerts that still hold recall" drives their threshold
to the top of the grid and effectively deletes them — 179 alerts at 77.7%
precision, and no jurisdiction coverage at all.

I did not take that operating point. Twelve months of synthetic data showing no
laundering through Cyprus is not evidence that none exists; a jurisdiction
screen also carries regulatory expectations a precision number does not capture.
So the threshold sits at the 99th percentile of anomaly score, keeping a
corroborated jurisdiction channel alive at a cost of 32 extra alerts, and
`tier_a_only` is reported beside it so the price of that caution is visible.

**Caveat stated plainly:** that threshold is calibrated against the labels. In
production you would calibrate it on historical investigated alerts and expect
some drift.

### 13. A latent bug in the structuring rule, found by writing tests

Worth recording because the failure mode is the interesting part.

The burst detector scored each transaction against windows *anchored* at it —
the window ending at it, and the window starting at it — and took the larger.
For three payments on days 0, 1 and 2, the middle one sees two events behind it
and two ahead, scores 2 against a `min_count` of 3, and escapes. The rule
returned `[True, False, True]` for a burst that should flag entirely.

The correct test is whether a transaction falls inside *any* qualifying window,
not one it happens to anchor. It is enough to check windows that begin at an
event, since any window can be slid right to start at its first member without
losing members.

**The fix changed nothing on this dataset.** Diffing old against new across all
60,059 rows: zero rows differ, because the planted clusters are dense enough
(payments hours apart) that every member anchors its own window. The bug would
surface on exactly three payments spread across a week — which is precisely the
sparse, deliberate pattern a careful launderer would use, and precisely what
this rule exists to catch.

This is the argument for testing detection logic directly rather than trusting
that plausible aggregate numbers mean the code is right. The metrics looked
correct throughout, because on this data they were.

### 14. Attacking the system, and what it revealed

The write-up's headline is a false-positive number measured against patterns
that sit still. Real laundering adapts, so the thresholds were attacked
directly: each scenario perturbs only the laundering transactions and re-runs
the full stack, with the model fitted once on the original book and then frozen
— the defender does not get to retrain after the attacker moves.

The labels and the TXNS/TXNR prefixes *are* used to locate the patterns to
perturb. That is legitimate for a red-team harness and is why `adversarial.py`
sits outside the pipeline: it attacks the system, it is not part of it.

Three results changed how I read my own project.

**The rule layer is brittle.** 139 cases down to 14 against a launderer who
knows all four thresholds. Nothing exotic — smaller payments, longer gaps.

**The model is the robust half.** 120 down to 44 under the same attack, and it
beats the rules in every single evasion scenario. It keys on behaviour rather
than on a number, so evading it costs the launderer something real. This
inverts the main finding: on clean data the rules detect and the model
suppresses noise; under adaptation the roles reverse.

**The architecture is the weakness.** Under full evasion the shipped system
catches 39 where the model alone at the same budget catches 44. Gating the
model behind rule corroboration is correct against noise and wrong against an
adversary. The fix is to treat the tiering as a dial: widen the model-only
channel when rule detections fall.

I have left the shipped configuration as it is rather than tuning it to the
attack. Tuning against evasions I invented would be fitting to my own
imagination of a launderer, which is a worse error than the one it fixes.

### 15. A reproducibility bug found by an external reviewer

Worth recording because I did not find this one, and because of how it failed.

A reviewer cloned the repo, installed dependencies fresh, and got different
numbers: recall 95% instead of 100%, 191 alerts instead of 211, six failing
tests. Nothing errored. `pip install pandas` now fetches pandas 3, which stores
timestamps as `datetime64[us]` where pandas 2 used `datetime64[ns]`. The rules
cast timestamps with `.astype("int64")` - returning whatever unit the column
carries - and compared the result against windows built from
`pd.Timedelta(...).value`, which is always nanoseconds. Every window came out
1000x too wide.

Reproducing it locally by forcing the column to `datetime64[us]` showed it was
worse than the report: the rapid-movement rule returned **zero** alerts, and
structuring flagged 101 because an effectively infinite window made every
near-threshold cluster qualify.

Three things came out of it:

1. All time arithmetic now goes through `src/timeutils.epoch_ns`, so the unit is
   pinned in one place.
2. Tests assert the rules give identical results under `ns`, `us`, `ms` and `s`,
   and CI runs the suite against both pandas 2 and pandas 3.
3. `requirements.txt` pins the versions the published numbers came from.

The lesson is the same one as the burst bug in entry 13, arriving from the
other direction. That bug was caught by tests and turned out to be latent; this
one was invisible to a test suite that only ever ran on one library version. A
silent wrong answer is worse than a crash, and "it works on my machine" is a
reproducibility claim I had not actually tested.

### 16. Removing lookahead from the account features

A reviewer pointed out that the per-account features were computed over the
whole twelve months. `amount_z_vs_account` compared a January transaction to
that account's mean for the entire year, including the following December, and
the counterparty counts worked the same way. No production system has that
information at decision time.

All account statistics are now expanding windows shifted by one row, so a
transaction is scored only against what the account did before it, and never
contributes to its own baseline. Counterparty counts accumulate through a
single pass in time order.

One thing surfaced while fixing it: with only two prior transactions the
expanding standard deviation can be near zero, which sent z-scores into the
thousands. A model would cheerfully key on that noise, so the z-score now needs
five prior transactions before it is trusted.

The cost is visible and was worth paying:

| | Before (lookahead) | After (trailing) |
|---|---:|---:|
| Alerts | 211 | 228 |
| False positives | 72 | 89 |
| Precision | 65.9% | 61.0% |
| FP reduction | 98.6% | 98.3% |
| Cases caught | 139/139 | 139/139 |

The anomaly layer was flattered by roughly 17 alerts' worth of hindsight. The
rule layer is unaffected, since no rule uses account statistics, which is why
recall does not move. The earlier figure was not wrong arithmetic; it was a
measurement of a system that could not exist.

*Entry 14 was re-measured after entry 16 removed lookahead from the features.
The conclusions were unchanged: the rules still collapse to 14, the model still
degrades rather than collapsing, and it still beats the shipped architecture
under full evasion. Only the magnitudes moved.*
