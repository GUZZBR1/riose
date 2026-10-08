# SC-1 Independent Red-Team Review

The read-only reviewer inspected the branch diff after implementation. Four actionable findings were raised and repaired:

1. A false verification result could leave a `CONFIRMED` request due immediately and hot-poll indefinitely. It now preserves the confirmed receipt and moves to `MANUAL_INTERVENTION` with `VERIFICATION_CONFLICT`. A regression verifies this behavior.
2. A forced `reconcile()` could observe before `available_at` and still replay saved bytes. Replay is now gated on the due time captured for that invocation; early reconciliation only observes. A regression checks the absence of an early send.
3. Missing adapters, invalid local binding, or invalid persisted payload after an attempt could request an illegal `PERMANENT_FAILURE` transition and raise. Requests with a persisted attempt now enter manual intervention, preserving the ambiguous or confirmed evidence. A regression covers missing adapter after ambiguous submission.
4. The reviewer highlighted immediate retry scheduling after observation errors. Backoff is now checked before replay, including forced reconciliation; a due scheduler invocation may replay the same signed attempt after observation, while an early forced observation may not.

The reviewer found no additional nonce-ordering issue in the inspected diff. Solana expiry fails closed to manual intervention and never builds replacement signed bytes. Crash-window tests label all receipt evidence `SIMULATED`; no mock is promoted to public-chain evidence.

Review was static and read-only. The role-specific reviewer runtime initially failed due unsupported model configuration; a default reviewer succeeded after using the app-supported model.
