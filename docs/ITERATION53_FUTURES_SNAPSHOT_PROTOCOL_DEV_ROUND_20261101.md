# Iteration 53: neutral futures snapshot contracts

Repository: bt_api_base, branch: dev.

Scope: extend neutral query contracts with futures session, product-universe,
catalog, quote, and depth families. Coverage binds the requested families and
filters to a single batch, source, and generation; unsupported product-universe
facts remain unavailable rather than being inferred from instrument rows.

Acceptance for this structural round: independent static review of the query,
coverage and product-universe contracts. No tests or provider operations were
run. Functional integration and real-account acceptance remain pending.

The commit containing this record identifies the structural round.
