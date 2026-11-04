# VeilAgent

Policy-bound shopping for people who want an agent to prepare purchases while keeping exact approval and spending authority outside the model.

**Implemented:** live Bitrefill MCP adapter, separate owner approval, signed single-use execution grants, USD spend caps, encrypted SQLite records, an agent-facing MCP interface, and an independent Zcash testnet resource checkout. The dashboard runs locally with no frontend build step.

**Live evidence:** an independently verified shielded public-testnet payment of **0.001 TAZ**, Ironwood pool, mined at height **4581917**:
[`d95a809359a47156c20d63eb560dabb99bdc3462d60f23e17689f73f7ffaefe5`](https://zexplorer.app/testnet/tx/d95a809359a47156c20d63eb560dabb99bdc3462d60f23e17689f73f7ffaefe5).
The receipt from the project's own watch-only verifier is in [docs/evidence/zcash-testnet.json](docs/evidence/zcash-testnet.json). The explorer does not reveal shielded amount or memo; those facts came from the receiver's authorized wallet.

The separate API order also received a real 0.001 TAZ transfer, verified five confirmations, released its resource, and rejected a second redemption with HTTP 409. [Full API evidence](docs/evidence/private-merchant-e2e.json) records the test interruption and recovery: the original order fields were restored after a temporary test process lost its ephemeral encryption key. No payment was resent during recovery, and this is not claimed as an uninterrupted run.

**Bitrefill live purchase invoice:** not yet created. No Bitrefill developer credential was available. [Public CLI catalog reads](docs/evidence/bitrefill-catalog.json) succeeded; unit fixtures are never used by the runtime. A shielded transfer settles the separate demo resource; it does not pay Bitrefill.

## Run locally

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). Node is only needed for optional Bitrefill CLI diagnostics and browser checks.

```sh
uv sync --locked
uv run python scripts/bootstrap.py
uv run uvicorn veilagent.app:create_app --factory --host 127.0.0.1 --port 8787
```

Open <http://127.0.0.1:8787>. Open the private `.env` locally and paste **OWNER_TOKEN** into the dashboard's session control. Bootstrap creates random credentials with mode 0600, does not print them, and never overwrites an existing `.env`.

To enable commerce, set these values in `.env`, then restart the server:

```dotenv
BITREFILL_API_KEY=<your backend-only developer key>
ALLOWED_EMAILS=<your receipt email>
ALLOWED_RECIPIENTS=<your team phone, international digits without +>
ALLOWED_PRODUCTS=airtel-india
ALLOWED_COUNTRIES=IN
MAX_PURCHASE_MINOR=500
MAX_DAILY_MINOR=1000
```

Use a zero-balance Bitrefill account and a manual crypto method for development. This MVP rejects balance/cashback payments and has no wallet-payment signer. Above a cap, no invoice is created; the operator must change local policy and restart before making and approving a fresh proposal. There is no agent-callable override.

The Zcash path uses a local watch-only `zkool_graphql` account. Set `ZCASH_ENABLED=true` only when that receiver is running. See [docs/ZCASH.md](docs/ZCASH.md) for safe wallet setup, faucet, actual send and verification commands. The live wallets created during implementation stay in ignored `.local/zcash/`; these are testnet development wallets, not production custody.

## Core flow

1. Search the real catalog and select an exact provider denomination, region, receipt email, recipient and manual payment method.
2. Deterministic code verifies current prices with exact decimal arithmetic. Default maximums are **$5 per purchase and $10 per India calendar day**. The user can choose a smaller limit.
3. The owner reviews the canonical fields and approves their SHA-256 digest. The authority issues a **90-second** HMAC-signed grant. The agent credential cannot approve.
4. The gateway independently re-reads the catalog. Changed terms require fresh approval. One SQLite transaction consumes the grant and reserves the approved maximum against the daily cap before calling `buy-products`.
5. There is one provider write attempt. A timeout or process interruption retains the grant consumption and budget reservation and records `UNCERTAIN`; it never blindly buys again.
6. The authoritative invoice must match the approved items, recipient, receipt email, payment method, currency and ceiling. Missing or mismatched evidence blocks the payment link. Guest links are owner-only because they can embed invoice access tokens.
7. The owner may pay the provider's manual checkout link. Refresh obtains provider state. Invoice `complete` is still pending until all orders are `delivered`. Redemption codes are never returned to the agent or stored in audit logs.

The independent privacy flow is **create resource order → ZIP 321 request → user-approved shielded testnet send → watch-only verification of mined notes and memo → five-minute single-use entitlement**. Broadcast alone never unlocks the resource. One chain transaction cannot fulfil two orders.

## Connect an agent

The application supports an external MCP-capable coding or shopping agent. There is no embedded LLM, paid model dependency, or simulated autonomous purchase. This is the small trusted authority boundary around an agent.

Start `veilagent.mcp_gateway` in a separate process with **only AGENT_TOKEN**, while the trusted HTTP gateway runs on loopback port 8787. The MCP process deliberately does not load `.env`.

```json
{
  "mcpServers": {
    "veilagent": {
      "command": "/absolute/path/to/pegasus/.venv/bin/python",
      "args": ["/absolute/path/to/pegasus/veilagent/mcp_gateway.py"],
      "env": {"AGENT_TOKEN": "<copy only the local AGENT_TOKEN>"}
    }
  }
}
```

Tools: `search_products`, `product_details`, `propose_purchase`, `execute_approved_purchase`, `purchase_status`. Approval happens in the owner dashboard. The dashboard can execute the approved grant itself; an external agent can execute a grant explicitly supplied by the owner. The agent never gets the owner credential, Bitrefill key, invoice access token or guest payment link.

## Verification

```sh
uv run pytest -q
uv run ruff check .
node --check veilagent/static/app.js
```

Tests exercise tampered/expired/replayed grants, concurrent execution, durable daily caps, recipient and product swaps, ten injection strings, precise money arithmetic, ambiguous writes, status integrity, secret redaction, memo/pool/confirmation checks and entitlement replay. All fixtures are explicit test doubles. Real testnet evidence lives separately in `docs/evidence/`.

The dashboard was also checked with Playwright on desktop and mobile: no JavaScript errors, no horizontal overflow, token entry works, and unconfigured actions remain disabled. See [docs/DEMO.md](docs/DEMO.md) for the walkthrough.

## Privacy and trust

1. **Shielded on-chain:** the separate merchant payment uses Ironwood/Sapling notes. Its amount and memo are visible to the receiver's viewing key, not the public explorer. Bitrefill commerce has no Zcash privacy claim.
2. **App storage:** purchase fields, recipients, private orders and provider access tokens are Fernet-encrypted at rest. Intent IDs, digests, states, timestamps, grant consumption and budget reservations remain plaintext. Audit events contain reason codes, not recipients or codes. The operator holds the encryption key in local `.env` and can decrypt records.
3. **Other parties:** `testnet.zec.rocks` sees wallet IP and sync timing. Fauzec sees the payer address and request IP. Bitrefill sees its account, purchase, receipt email and recipient. The watch-only service can see the receiving account's whole history but cannot spend. No CipherPay or Nym service is used. No LLM provider receives data from this app; any external agent's provider sees the tool calls you send it.
4. **Trust and next fixes:** trust the local operator, wallet software, light-wallet server, provider and their reported chain/order state. Loopback binding, separate owner/agent credentials and no CORS serve a **single-operator local demo**. A compromised local process running as the operator can read `.env` and wallet databases; this is not OS isolation. Add real user sessions, per-user ownership, process isolation, quote fees verification, hardened deployment, reorg handling and data-retention controls before public hosting.

## Built versus reused

Lane 1 (rails and guardrails), with a separate Privacy merchant. New code implements the authority, SQLite ledger, policy, dashboard, read-only watcher and adapters. It uses the official MCP Python SDK, Bitrefill MCP, zkool2 `zkool_graphql`, optional Noir browser provider, FastAPI, httpx, jsonschema, TOON decoding and cryptography. Versions are pinned by [uv.lock](uv.lock); wallet release details are in the receipt. No code was copied from the repositories proposed in `project.md`, so their license/compatibility questions do not block this small implementation.

The two official llms.txt briefs are saved intact in [AGENTS.md](AGENTS.md), with separate source copies in [docs/briefs](docs/briefs). `project.md` is the original design; its broader TypeScript planner and production architecture remain future work.

## Next 30 days and submission

- Complete a credential-backed Bitrefill catalog/invoice/delivery run, record its real invoice ID here and make a 2–3 minute demo video. Neither is claimed yet.
- Validate missing invoice fields with the Bitrefill team before relaxing a fail-closed parser.
- Run the UI with an actual target user and record their own feedback. No user demand evidence has been invented.
- Extract the reusable memo/confirmation verifier and spend gateway after review. No upstream issue, PR or partner outreach has been created in this session.
- Write final [FEEDBACK.md](FEEDBACK.md) in the human builder's words. Engineering notes are in [FEEDBACK_NOTES.md](FEEDBACK_NOTES.md).

For this event, finalize and submit on [Stadium](https://stadium.joinwebzero.com/programs/free-society-hack-2026) by **4 November 2026, 20:00 IST** for the first judging round. Drafts are not judged; edits continue until midnight. Public repo publication, public hosting, video and final submission are still pending.
