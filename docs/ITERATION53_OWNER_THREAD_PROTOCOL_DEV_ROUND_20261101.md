# Iteration 53: managed owner-thread call contract

Repository: bt_api_base, branch: dev.

Scope: a neutral owner-thread call port and finite scheduling errors. A queued
call may be cancelled before the runtime atomically claims it; a timeout after
that transition is an unknown outcome. Owner-thread calls run inline and are
not interrupted by the cross-thread wait timeout. This contract grants no
trading authority.

Acceptance for this structural round: independent static source and dependency
review. No tests or provider operations were run. Mailbox implementation,
runtime integration, and account acceptance remain pending.

The commit containing this record identifies the structural round.
