# Solution Steps

1. Extend the PostgreSQL schema with a unique `(study_id, source_report_id)` intake constraint, idempotent follow-up keys, physician-review work, persisted dispositions, and a run-correlated audit index.

2. Register the intake case deterministically before model coordination. Use `INSERT ... ON CONFLICT DO NOTHING` followed by lookup so replaying a source report returns the original case rather than creating a duplicate.

3. Keep evidence access inside PostgreSQL-backed tools, limit result sizes, scope every model-requested tool call to the current study/site/subject/report, and return structured failures instead of hiding exceptions.

4. Make tool schemas strict with required fields, bounded limits, and `additionalProperties: false`. Do not expose case registration as a model-controlled tool because intake is an orchestration responsibility.

5. Bound each specialist to two tool rounds and six executions. Detect identical repeated calls, return an explicit duplicate-call failure, and produce an uncertain incomplete result when the budget is exhausted.

6. Always retain every specialist result by appending it to run state. Require evidence and safety specialists regardless of the model's plan, adding site operations when uncertainty is evident.

7. Build the final model prompt from all specialist evidence, then apply a deterministic safety gate. Seriousness markers, uncertainty markers, malformed model output, provider failures, tool failures, and budget exhaustion all force conservative handling.

8. Create or reuse a physician-review record for every serious or uncertain case. Only mark such a disposition completed when PostgreSQL contains a completed review with `reviewer_role='physician'` and a review timestamp.

9. Persist site follow-up with a hash-based deduplication key derived from study, source report, and normalized reason so retries and report replays cannot create duplicate work.

10. Persist the final disposition independently of the audit trail and explicitly include tool failures and evidence quality, preventing failed lookups from becoming confident clinical claims.

11. Fix audit correlation by writing the supplied run ID, not a new UUID. Privacy-minimize audit payloads by hashing source/subject identifiers, replacing narratives with length and digest metadata, and redacting email-like values.

12. Configure the real OpenAI-compatible client exclusively from `.env`, including provider key, base URL, and model name, while adding request timeouts, limited retries, and output-token bounds.

13. Run `./run.sh`, then execute a fixture with `python3 -m agent fixtures/portal_syncope.json`. Re-run the same fixture and verify the case and follow-up IDs are reused and the disposition remains awaiting physician review until a valid human physician review is completed.

