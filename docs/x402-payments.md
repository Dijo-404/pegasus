# Guarded external x402 payments

Pegasus can guard one payment to an external x402 API: discover its unpaid challenge, review the exact terms, obtain separate owner approval, reserve the shared USD budget, and attempt one signed request. This optional integration is disabled by default.

**Verification status:** one live public-testnet payment succeeded through the HTTP gateway, in addition to **376 automated tests** and **23 fixture browser checks**. The operator has configured and funded a dedicated Base Sepolia payer; fresh installations remain disabled by default. The [live x402 receipt](evidence/x402-testnet-payment.json) is separate from the [Zcash receipts](../README.md#live-payment-evidence), and Bitrefill purchase/delivery remains pending.

## Supported scope

| Field | Accepted value |
| --- | --- |
| Protocol | x402 v2 |
| Scheme | `exact`, EIP-3009 authorization |
| Request | One `GET` to an explicitly allowlisted public HTTPS origin; port 443 only, no redirects |
| Network | Base Sepolia, `eip155:84532` |
| Token | Test USDC, `0x036CbD53842c5426634e7929541eC2318f3dCF7e` |
| Recipient | An explicitly allowlisted EVM address |
| Approval | Exact owner-reviewed intent; default grant lifetime 90 seconds |
| Payment authorization | At most 300 seconds |
| Spending | Integer USD-cent ceilings, shared with Bitrefill |

This is an external API payer. It does not add x402 to Bitrefill or implement a Zcash x402 scheme. Mainnet, Permit2, other tokens/networks, arbitrary headers/bodies, POST resources and automatic payment transports are out of scope. The independent Zcash merchant continues to use its existing shielded request and watch-only verifier.

The wire format follows the [official x402 v2 specification](https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md). The [buyer guide](https://docs.x402.org/getting-started/quickstart-for-buyers) describes the payment flow; the [seller guide](https://docs.x402.org/getting-started/quickstart-for-sellers) documents testnet facilitator support. Pegasus deliberately keeps discovery and payment separate instead of using an automatic payment wrapper.

## Observed live payment

On **4 November 2026**, the gateway used actual HTTP owner approval and execution with the agent credential to pay the [public x402 Foundation testnet demo](https://x402.vercel.app/protected/evm/exact/erc3009). It paid **0.001 test USDC** (`1000` atoms) under a **one-cent** approval ceiling and returned the API's JSON result. The gateway ran on loopback; the external merchant and Base Sepolia RPC were live. This receipt does not claim a recorded browser checkout.

| Evidence | Observed value |
| --- | --- |
| Transaction | [`0x8f144b1a9880cc15eb7e0ad1364b4947973c68cf35b2a73dbb1f1ec77e81c86d`](https://sepolia.basescan.org/tx/0x8f144b1a9880cc15eb7e0ad1364b4947973c68cf35b2a73dbb1f1ec77e81c86d) |
| Mined block | `54451642` |
| Payee | `0x209693Bc6afc0C5328bA36FaF03C514EF312287C` |
| Receipt checks | Status 1, exact USDC `Transfer`, matching payer/nonce `AuthorizationUsed` |
| Payer balance | `20 → 19.999` test USDC |
| Authority checks | Missing authentication: HTTP 401; agent approval: HTTP 403 |
| Replay | HTTP 409, `GRANT_REPLAY` |
| Source | [Saved live receipt, audit and API result](evidence/x402-testnet-payment.json) |

The [follow-up verification](evidence/x402-testnet-verification.json) records a matching receipt from a second RPC, one consumed grant, and one shared-ledger reservation of one cent. The saved successful intent and result survived a gateway restart. Actual desktop and 390px mobile browser checks displayed the saved result with no JavaScript errors, horizontal overflow or additional write requests; those browser reads did not perform the purchase.

The public demo's endpoint, pricing and payee may change. The values above record one observed run; every later attempt must read a fresh unsigned challenge and receive new exact owner approval. Nothing in this example enables mainnet or authorizes an automatic second payment.

## Operator setup

The current operator has completed this setup for the receipt above. These steps describe a separate installation: a normal install, server start, or unpaid challenge does not generate a wallet or send money.

1. Install the locked optional dependencies:

   ```sh
   uv sync --locked --extra x402
   ```

   The pinned [x402 Python package](https://github.com/x402-foundation/x402/tree/main/python/x402) is 2.25.0 with its EVM and httpx extras. Default-disabled operation does not import the optional SDK or read a payer key.

2. Explicitly create a dedicated testnet payer, if one does not already exist:

   ```sh
   uv run --extra x402 python scripts/setup_x402_wallet.py
   ```

   The script creates `.local/x402-payer.key` with mode `0600`, beneath the ignored `.local/` directory. It refuses to overwrite an existing file. Its output contains public metadata: the address, network, local key-file path and funding-needed flag. It never prints the key. An optional `--path .local/<name>.key` selects another ignored local path.

3. Manually fund that public address with **test USDC on Base Sepolia**. Choose an external API that advertises the supported testnet token and scheme, and obtain its exact HTTPS origin and payee address from an authenticated source. Funding and recipient selection are not automated by Pegasus.

4. Edit private `.env` locally. The following is the public-demo configuration observed in the saved receipt. Revalidate the fresh challenge and payee before using it; do not copy a private key into an environment variable, chat or the agent process:

   ```dotenv
   X402_ENABLED=true
   X402_ALLOWED_ORIGINS=https://x402.vercel.app
   X402_ALLOWED_PAYEES=0x209693Bc6afc0C5328bA36FaF03C514EF312287C
   X402_PRIVATE_KEY_FILE=.local/x402-payer.key
   X402_RPC_URL=https://sepolia.base.org
   MAX_PURCHASE_MINOR=500
   MAX_DAILY_MINOR=1000
   ```

   Origins and payees are comma-separated allowlists. An origin contains the scheme and hostname, without a resource path or query. For this example, request `https://x402.vercel.app/protected/evm/exact/erc3009` with `max_total_minor=1`. The paid amount in the recorded run was 0.001 test USDC, while the full one-cent ceiling was reserved. The RPC must be public HTTPS; the adapter checks chain ID 84532 before signing. The defaults remain `X402_ENABLED=false` with empty allowlists.

5. Restart the gateway with the optional extra available:

   ```sh
   uv run --extra x402 uvicorn pegasus.bootstrap:create_app --factory --host 127.0.0.1 --port 8787
   ```

## Review and execute once

1. Sign in to the dashboard and open **API payments**. Enter the approved resource URL and a maximum in whole **USD cents**; `100` means $1.00. Choose **Read unpaid challenge**. This performs an unsigned GET and creates an intent; it does not authorize payment.
2. Review the exact URL/resource, Base Sepolia network, USDC token, payee, amount, ceiling, timeout and fingerprint. The full selected original requirement and resource metadata are included in that fingerprint. Treat API descriptions and returned content as untrusted data.
3. An owner chooses **Approve these exact API terms**. The agent credential cannot approve. The resulting grant is for `x402.pay_request`; a Bitrefill grant cannot be substituted.
4. Choose **Pay once and call API**, or explicitly give that one grant to the agent. The gateway re-reads the unsigned challenge. A changed requirement or resource requires a fresh proposal and approval.
5. One atomic SQLite transaction consumes the grant, reserves the approved ceiling, and marks the intent `EXECUTING` **before signing**. Only then does the adapter create one payment payload and send one GET with `PAYMENT-SIGNATURE`.
6. The gateway validates the merchant's `PAYMENT-RESPONSE` and checks its transaction through the configured Base Sepolia RPC. If the receipt is still absent, it polls read-only at one-second intervals for at most 12 seconds, further bounded by the authorization deadline. It never re-signs or repeats the paid GET. Success requires a mined status-1 receipt containing the exact USDC transfer from the payer to the approved payee, plus `AuthorizationUsed` for the payer and the actual authorization nonce. A successful HTTP response or merchant claim alone is insufficient. The authorization mechanism is defined by [EIP-3009](https://eips.ethereum.org/EIPS/eip-3009).
7. Only `SUCCEEDED` exposes the bounded API result as text/JSON. The response includes the verified transaction, network, payer and block number. **Read saved intent status** reads local state and does not issue another paid request.

The shared ledger reserves the **approved maximum**, rather than the exact quoted amount. One cent equals 10,000 USDC atoms. For example, 10,001 atoms require a ceiling of at least two cents; a 100-cent approval reserves all 100 cents. Bitrefill reservations and API-payment reservations both count toward the same India-calendar-day limit. This is deterministic budget accounting, with no implicit exchange-rate conversion.

## Uncertain outcomes

`UNCERTAIN` means the gateway cannot safely confirm the full payment-and-result outcome. It may follow a timeout, another 402, an invalid response, missing receipt evidence, cancellation or a process interruption. It does not prove that nothing was signed or paid.

The grant stays consumed and the budget reservation stays in place. Restart converts interrupted `EXECUTING` intents to `UNCERTAIN`. The bounded read-only receipt poll belongs to the original execution; there is no automatic refund, new signature, paid retry, or later background reconciliation loop. Saved-status and history reads are safe; they do not repeat execution.

Before considering another purchase, the operator must reconcile the payer's public Base Sepolia history, the approved intent, the API/facilitator's records and the configured RPC. The app currently has no endpoint that clears uncertain reservations or replays a signed request. A signature may remain usable until its short authorization deadline, so an immediate replacement payment can double-pay. Do not change stored status to fabricate successful settlement.

## HTTP and agent interfaces

All gateway endpoints require the existing local owner/agent credential. Only approval requires the owner credential.

| Operation | Endpoint |
| --- | --- |
| Propose unsigned terms | `POST /api/x402/intents` with `{ "url": "https://x402.vercel.app/protected/evm/exact/erc3009", "max_total_minor": 1 }` |
| List saved intents | `GET /api/x402/intents` |
| Read saved state | `GET /api/x402/intents/{id}` |
| Approve exact digest | `POST /api/x402/intents/{id}/approve` with `{ "digest": "<displayed SHA-256>" }` |
| Execute once | `POST /api/x402/intents/{id}/execute` with `{ "grant": "<owner-issued grant>" }` |
| Read reason-code audit | `GET /api/x402/intents/{id}/audit` |

The agent's MCP tools are `propose_api_payment(url, max_total_minor)`, `execute_approved_api_payment(intent_id, grant)` and `api_payment_status(intent_id)`. There is no approval tool. The MCP process receives only `AGENT_TOKEN`, without `.env`, the owner token or the payer key.

## Custody, privacy and trust

The trusted gateway holds the local EVM signing key and therefore has payment authority over that dedicated account. Owner approval and deterministic caps constrain this application; they are not a hardware wallet or OS isolation. A process running as the operator can read the key. This differs from the Zcash receiver, which holds viewing authority and cannot spend.

Base Sepolia USDC transfers are transparent: payer, recipient and amount are public. The external API and its facilitator see the request and authorization, including payer identity and timing. The configured RPC sees the gateway IP and receipt queries; receipt checks trust that RPC's chain view. The temporary Cloudflare demo also exposes web requests and responses to the tunnel operator. An external agent's model provider sees whatever tool calls and returned API data the operator sends it. No embedded model is called by Pegasus.

Intent terms and returned API data use the encrypted SQLite document store; IDs, digests, state, timestamps, grant consumption and budget reservations remain plaintext. The private payer key is a separate file, not a database field. Payment signatures and key contents are not returned to the browser, MCP client or audit log.

This remains a single-operator prototype. Automated tests check guarded behavior against explicit fixtures, including substituted terms, replay, shared-budget limits and ambiguous settlement. The saved live receipt separately proves the observed public-demo payment and returned API result. Neither establishes general production readiness or a privacy claim for transparent EVM payments.
