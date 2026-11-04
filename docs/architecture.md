# Pegasus architecture

Pegasus separates purchase rules, application workflows, external adapters and user interfaces. Dependencies point inward. The domain and application layers can run without FastAPI, MCP, a wallet service or a database.

```text
presentation ──► application ──► domain
infrastructure ──► application / domain
bootstrap ──► concrete adapters + application services + presentation
```

`src/pegasus/bootstrap.py` is the composition root. It reads local settings, constructs adapters, injects them into application services and builds the HTTP application. It contains no purchase policy.

## Layers

| Layer | Responsibility | Main files |
| --- | --- | --- |
| `domain/` | Exact money rules, allowlists, invoice validation, canonical intent digests and domain failures | `commerce_policy.py`, `canonicalization.py`, `exceptions.py` |
| `application/` | Propose, approve, execute and reconcile purchases; create, verify and redeem private orders | `commerce_service.py`, `private_checkout_service.py`, `ports.py` |
| `infrastructure/` | Implement external calls, encrypted persistence, execution-grant signing and environment configuration | `settings.py`, `providers/bitrefill_client.py`, `providers/zcash_client.py`, `persistence/sqlite_repository.py`, `security/hmac_grant_authority.py` |
| `presentation/` | Validate transport input, authenticate callers, call use cases and return safe response views | `http/`, `mcp/server.py`, `web/` |

The interfaces in `application/ports.py` describe the capabilities use cases need: `CommerceProvider`, `CommerceRepository`, `GrantAuthority`, `PaymentVerifier` and `PrivateOrderRepository`. Concrete clients and repositories implement those contracts. The use cases do not import their implementations.

The HTTP adapter owns routes, request schemas, authentication, middleware, error mapping and response projections. Private-order creation and fulfillment belong to `PrivateCheckoutService`; the HTTP route delegates to that service. Agent-visible response projections omit owner-only recipient details, payment links and provider access tokens.

The MCP adapter is a separate process with only the agent credential. It exposes bounded shopping tools through the local HTTP gateway and has no approval tool. The web directory holds the dashboard's `index.html`, `app.js` and `styles.css`.

## Payment invariants

- Current provider data and deterministic policy must pass before approval and execution.
- An owner approves one canonical action. A signed grant binds that action and expires quickly.
- One SQLite transaction consumes the grant and reserves the approved maximum before invoice creation.
- A provider write is attempted once. An ambiguous result remains `UNCERTAIN` with its reservation retained.
- An invoice is payable only after its authoritative terms match the approval. Finalized invoices remain pending until every order is delivered.
- The independent Zcash merchant verifies mined shielded notes, the exact memo and the requested amount before issuing a five-minute, single-use entitlement. One transaction cannot fulfill two orders.

These rules survive the package and filename changes. Local database migration preserves the existing encrypted records and keys. Real transaction evidence remains in `docs/evidence/`; old on-chain memo strings are historical facts and are not renamed.

## Tests and naming

Unit tests follow the layers under `tests/unit/`. Integration tests exercise the HTTP boundary, persistence and adapter protocols. `tests/test_architecture.py` checks dependency direction so inner layers cannot acquire transport or infrastructure imports unnoticed.

Use descriptive `snake_case` Python modules. Choose role names such as `commerce_service.py`, `sqlite_repository.py` and `bitrefill_client.py` instead of ambiguous files such as `service.py` or `store.py`. Use lowercase hyphenated guide filenames. The root retains the conventional `README.md` and the event-required `AGENTS.md` and `FEEDBACK.md`.

Run validation from the repository root:

```sh
uv run pytest -q
uv run ruff check .
node --check src/pegasus/presentation/web/app.js
```

The broader product proposal is in [project-specification.md](project-specification.md). Current setup, limits and live evidence are in the root [README](../README.md).
