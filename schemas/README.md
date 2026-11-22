# WebSocket protocol schema

**Normative machine-readable wire contract** for `WS /ws/accounts` messages exchanged between the P99 Login Proxy and an SSO backend. This repo owns it.

| Artifact | Role |
|---|---|
| [`ws-protocol.schema.json`](ws-protocol.schema.json) | Normative JSON Schema (draft 2020-12) for message envelopes |
| [`fixtures/`](fixtures/) | One example per message type (`inbound` = server→client, `outbound` = client→server) |
| [`../docs/backend-protocol.md`](../docs/backend-protocol.md) | **Additive** implementer guide (flows, crypto, RBAC, size caps, checklists). Does **not** replace this schema; must not diverge from it. |

`crates/runtime/tests/ws_contract.rs` validates every fixture against the schema and pins the proxy's typed messages to the fixtures.

## Backends

The schema and fixtures live only here; backends link to them rather than copying them. [roboToald](https://github.com/eq-p99-tools/roboToald), the reference backend, validates the fixtures and its live `full_state` / `delta` output against the schema in `tests/test_ws_protocol_schema.py`, loading them from a checkout of this repo (`P99_LOGIN_PROXY_DIR`, or a sibling `p99-login-proxy` directory). Its CI checks out the `rust` branch for that, so a wire change merged here is picked up there on its next run.
