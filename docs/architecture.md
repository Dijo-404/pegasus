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
| `domain/` | Exact money rules, allowlists, invoice and x402 challenge validation, canonical intent digests and domain failures | `commerce_policy.py`, `x402_policy.py`, `canonicalization.py`, `exceptions.py` |
| `application/` | Propose, approve, execute and reconcile purchases; guard external API payments; create, verify and redeem private orders | `commerce_service.py`, `x402_service.py`, `private_checkout_service.py`, `ports.py` |
| `infrastructure/` | Implement external calls, encrypted persistence, execution-grant signing and environment configuration | `settings.py`, `providers/bitrefill_client.py`, `providers/zcash_client.py`, `providers/x402_client.py`, `persistence/sqlite_repository.py`, `security/hmac_grant_authority.py` |
| `presentation/` | Validate transport input, authenticate callers, call use cases and return safe response views | `http/`, `mcp/server.py`, `web/` |

The interfaces in `application/ports.py` describe the capabilities use cases need: `CommerceProvider`, `CommerceRepository`, `GrantAuthority`, `PaymentVerifier`, `PrivateOrderRepository` and `X402PaymentProvider`. Concrete clients and repositories implement those contracts. The use cases do not import their implementations.

The HTTP adapter owns routes, request schemas, authentication, middleware, error mapping and response projections. Private-order creation and fulfillment belong to `PrivateCheckoutService`; the HTTP route delegates to that service. Agent-visible response projections omit owner-only recipient details, payment links and provider access tokens.

The MCP adapter is a separate process with only the agent credential. It exposes bounded shopping tools through the local HTTP gateway and has no approval tool. The web directory holds the dashboard's `index.html`, `app.js`, `visuals.js`, `styles.css` and self-hosted `fonts/`. `visuals.js` draws decorative canvas scenes only; it reads the order status `app.js` already displays and never calls the API.

The optional **API payments** tab and three API-payment MCP tools call `X402Service` through `/api/x402/intents`. HTTP owns authentication and request validation; domain rules accept only an allowlisted HTTPS GET resource, Base Sepolia USDC and x402 v2 `exact` EIP-3009 terms. `X402Client` performs unpaid discovery and one manually invoked signed request. The optional SDK and operator-only key are loaded lazily when signing is attempted; a default-disabled application needs neither.

## Payment invariants

- Current provider data and deterministic policy must pass before approval and execution.
- An owner approves one canonical action. A signed grant binds that action and expires quickly.
- One SQLite transaction consumes the grant and reserves the approved maximum before invoice creation or x402 signing. Bitrefill and API payments use the same USD daily reservation table and India calendar day.
- A provider write is attempted once. An ambiguous result remains `UNCERTAIN` with its reservation retained.
- An invoice is payable only after its authoritative terms match the approval. Finalized invoices remain pending until every order is delivered.
- The independent Zcash merchant verifies mined shielded notes, the exact memo and the requested amount before issuing a five-minute, single-use entitlement. One transaction cannot fulfill two orders.
- x402 intent IDs begin `xi_` and carry `kind: "x402"`; commerce IDs begin `pi_`. Services filter their own kinds. Distinct signed actions, `x402.pay_request` and `bitrefill.create_invoice`, prevent cross-rail grant reuse.
- x402 approval binds the full selected payment requirement and resource metadata as well as URL, GET method, token, network, recipient, exact atomic amount, timeout and USD ceiling. The unsigned challenge is re-read before reservation; changed terms require a fresh approval.
- USDC has six decimal places: one USD cent is 10,000 atoms. Required cents round up, while the full approved cent ceiling is reserved. Floating-point prices and implicit cross-currency conversion are not used.
- x402 execution signs once and sends one paid GET. Redirects and automatic payment/retry wrappers are rejected. Destination DNS is checked for public addresses and a validated address is pinned for TLS with the original hostname preserved.
- x402 success requires a mined, status-1 receipt from the configured Base Sepolia RPC, an exact USDC transfer and `AuthorizationUsed` for the actual payer/nonce. An absent receipt is polled for at most 12 seconds, bounded by authorization expiry; signing and the paid GET are never repeated. HTTP 200 or a merchant receipt alone cannot establish settlement. The RPC remains a trusted external source, rather than a locally validated chain.
- x402 authorizations last at most 300 seconds; the owner execution grant defaults to 90 seconds. Failure or cancellation after reservation becomes `UNCERTAIN`, retains budget and cannot automatically sign again. On restart, persisted `EXECUTING` intents become `UNCERTAIN`.

The payment adapters settle independently. The x402 gateway holds a dedicated EVM key and its USDC transfers are public. The Zcash receiver uses viewing authority without spending authority. Neither path pays a Bitrefill invoice. See [x402 payments](x402-payments.md) for setup, custody and manual reconciliation. Alongside explicit test doubles, a [live Base Sepolia receipt](evidence/x402-testnet-payment.json) records one 0.001 test-USDC call to the official x402 demo, nonce verification and rejected replay. This separate run does not establish Bitrefill delivery.

These rules survive the package and filename changes. Local database migration preserves the existing encrypted records and keys. Real transaction evidence remains in `docs/evidence/`; old on-chain memo strings are historical facts and are not renamed.

## Tests and naming

Unit tests follow the layers under `tests/unit/`. Integration tests exercise the HTTP boundary, persistence and adapter protocols. `tests/test_architecture.py` checks dependency direction so inner layers cannot acquire transport or infrastructure imports unnoticed.

Use descriptive `snake_case` Python modules. Choose role names such as `commerce_service.py`, `sqlite_repository.py` and `bitrefill_client.py` instead of ambiguous files such as `service.py` or `store.py`. Use lowercase hyphenated guide filenames. The root retains the conventional `README.md` and the event-required `AGENTS.md` and `FEEDBACK.md`.

Run validation from the repository root:

```sh
uv run pytest -q
uv run ruff check .
node --check src/pegasus/presentation/web/app.js
node --check src/pegasus/presentation/web/visuals.js
```

The broader product proposal is in [project-specification.md](project-specification.md). Current setup, limits and live evidence are in the root [README](../README.md).
