# Third repeated implementation failure

Prompt: The same issue, failed command and Git baseline have failed for the third time. Try one more ordinary repair automatically.

Expected contract: use `failure-record` to preserve the third attempt in the append-only manifest, block ordinary repair on 第三次 failure, and require `grh-recover` plus an explicit user-approved recovery decision.
