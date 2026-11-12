# 5b · AI process log

**Bottom line:** AI wrote most of the SQL and text; I set the questions, the rules and the checks. AI was wrong at least 7 times in ways that mattered. 4 of them were caught by me, 3 by cross-checking one AI against the data. Every number in the hand-in is now computed by SQL from the raw files, never typed by hand.

## 1. Tools and what each did

| Tool | Used for |
|:--|:--|
| **Claude (Claude Code, desktop app)** | Main analyst: profiling queries, the DuckDB pipeline (`sql/00`–`06`), the clean layer, churn validation, Python report generators, this site. Ran every query against the real database. |
| **Gemini** | Second opinion: critical review of the Part 1a data-quality findings and of the renewal-window analysis. |
| **NotebookLM** | Debrief prep pack built from the reports (`prep/`), to rehearse explaining the choices. |

## 2. How I worked with them

- **Second opinions are checked, not trusted.** Every claim from Gemini was re-run in DuckDB before it went in.
- **No typed numbers.** Supporting numbers in the reports are computed by SQL at build time; text that drifted from the data was the trigger for this rule.
- **Every detection query is checked against its count.** If the query that lists an issue returns a different number of rows than the check that counts it, the build flags it.
- **Re-read the brief before ranking.** Severity = how much an issue changes the answers leadership asked for.
- **Same input, same output.** Consecutive runs of `run_all.py` give identical outputs.

## 3. Representative prompts

Paraphrased from the chat (originally in Hebrew), except the first, which is a file in the repo.

1. **Critical review (Gemini):** "You are a senior data analyst reviewing someone else's data-quality report. Be critical and specific. Do not praise. If you cannot verify a claim without the data, say so." Full prompt: `reports/gemini_review_prompt_1a.md`.
2. "Re-run Gemini's renewal-by-day numbers on the full data in DuckDB, using both export files."
3. "Break the days-to-renewal curve down by plan type and by auto-renew vs paying by hand. Show % of returners by day."
4. "Rank the issues by how much they affect the four leadership questions, not by how many rows they touch."
5. "Implement billing's churn definition on the clean layer and compare it with `churn_labels.csv`. Explain every disagreement group."

## 4. Cases where the AI was wrong

| # | Tool | What it got wrong | Who caught it, how | What changed |
|:--:|:--|:--|:--|:--|
| 1 | Gemini | Reported a sharp renewal spike on day 31 (17.5% vs 0.35% real) and 33.4% churn (real 43.5%), and invented a "card declined" reason. It had read only part of the data. | **Me.** The day-31 jump looked wrong. Claude re-ran it on the full data and got different numbers; Gemini then admitted it used a partial file. | Every second opinion is now re-run on the full data in DuckDB before use. |
| 2 | Gemini | "All 109,330 users missing from `users.csv` are paying users." | **Claude**, by re-running in DuckDB: only 53,023 of them ever paid. | Issue sized on paying users; revenue share reported (8.3%). |
| 3 | Gemini | Explained ages 106 and 112 with the Taiwan (ROC) calendar. | **Claude**: most age-106 users registered in 2014–15, and 112 matches no recent ROC year. | Story rejected; ages handled by the cleaning rule in `dim_user`. |
| 4 | Claude | "Plan type doesn't change the churn window." | **Me.** I insisted it does. Split by plan: auto-renew users were 97% back by day 1, people paying by hand about 37%. | Renewal timing is checked per plan type before fixing the window; the 30-day window plus 32 and 45-day checks follow from that. |
| 5 | Claude | Counted "11,560 conflicting versions between exports", matching rows on user + day, which is not a unique key. | **Claude itself**, while building the clean layer. Real conflicts: 747. | The worst one: keeping it would have treated about 10,800 real, separate purchases as duplicates and dropped them. |
| 6 | Claude | Kept billing's churn labels at Medium severity and defended "export split stays #1" without re-reading the brief's ranking rule. | **Me.** The labels are most likely the churn number the CEO already saw. | Labels moved to Critical, now issue #1. |
| 7 | Claude | Ranking was inconsistent and missed an issue: 2015 missing plan length under-rated (it touches 39.7% of users active Mar–Oct 2015), and early renewals (578,644 rows) missing from the list. | **Prompted by my questions** about wrongly computed plan durations. | Plan length moved to Critical; early renewals added at High (first rated Medium, then corrected). |

**Cases 6-7 in detail: the AI's original 1a ranking vs the final one** (the original is the first version uploaded to GitHub; only issues that moved are shown):

| Issue | AI's original rank | Final rank |
|:--|:--:|:--:|
| Billing's churn labels | 10 · Medium | 1 · Critical |
| 2015 paid rows missing plan length | 3 · High | 2 · Critical |
| Exports split by expiry date | 1 · Critical | 3 · Critical |
| Gender missing | 11 · Medium | 6 · High |
| Free periods with no price | 6 · Medium | 8 · High |
| Early renewals | not listed | 9 · High |

**Also caught by Claude itself** (smaller): a loader bug that left the file path in every row; a non-repeatable tie-break that changed churn-label counts between runs; a first duplicate fix that still over-counted (1,561 rows instead of 747). All fixed; listed in `py/01_dq_outputs.py` (CORRECTIONS).

## 5. What I'd keep doing

- Use one AI to check the other, but let **the data** decide.
- Ask "how do you know?" when a number looks too clean or a story too neat.
- Keep a log like this one while working, not after.
