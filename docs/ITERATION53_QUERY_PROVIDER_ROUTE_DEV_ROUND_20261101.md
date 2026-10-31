# Iteration 53: query-provider route contract

Repository: bt_api_base, branch: dev.

Scope: add the provider-neutral selected-route and registry interfaces used by
bt_api_py query composition and provider plugins. The selected client is opaque;
provider-specific client interpretation remains inside its provider package.

Acceptance for this structural round: independent static review of the contract,
its package dependency direction and the shared route type used by the SDK and
CTP registrar. No tests or real-provider operations were run. Integration,
functional testing and account acceptance remain pending.

The commit containing this record identifies the accepted structural round.
