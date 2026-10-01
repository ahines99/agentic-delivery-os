# Change records

Each change that produces verification evidence adds its own file here instead of
appending to `implementation-status.md` or `completion-audit.md`. Parallel branches
then touch different files and do not conflict.

- Name records `YYYY-MM-DD-short-slug.md`, using the date the change merges.
- State what changed and the exact commit, then the checks run with their results, and
  what remains unverified.
- Link the record from the PR. Periodically, one dedicated PR may fold settled records
  into the status documents; no other branch edits those documents.

Records are append-only history. Correct a record with a new dated note, not by rewriting it.
