---
title: Gateway migration boundary | bt_api_base
---

# Gateway migration boundary

The standalone `bt_api_base.gateway` runtime, adapters, registrars, endpoint
configuration, and ZeroMQ transport have been removed from this package.
`bt_api_base` no longer provides a gateway runtime or gateway adapter API.

Use the exchange package's direct feed/plugin interfaces for direct market
access. Managed service deployments and their authenticated account or market
contracts are provided by the separate SDK service packages; they are not part
of `bt_api_base`.

## 网关迁移边界

独立的 `bt_api_base.gateway` runtime、adapter、registrar、endpoint 配置及 ZeroMQ
transport 已从本包移除。`bt_api_base` 不再提供 gateway runtime 或 gateway adapter API。

直接行情访问请使用交易所插件的 direct feed 接口。受管服务部署及其认证账户、行情契约由独立
SDK service 包提供，不属于 `bt_api_base`。
