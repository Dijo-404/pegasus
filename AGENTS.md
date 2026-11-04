# Pegasus build context

Both official briefs below were fetched on 2026-11-04. Implement the smallest flow in docs/project-specification.md; keep Bitrefill settlement and the separate Zcash-native merchant distinct. No automatic balance payments in this MVP. Never fabricate live evidence.

Source lives under `src/pegasus/`. Keep domain rules and application use cases independent of HTTP, wallet, database, and MCP implementations. Wire adapters in `pegasus.bootstrap`; follow [the architecture guide](docs/architecture.md). Python modules use descriptive snake_case names; documentation uses lowercase hyphenated names except required root files. Project integration notes live in `docs/integration-notes.md`; original filename references in the official briefs below remain as fetched. The copies of the official briefs and recorded payment evidence retain their original content.

# Free Society Hack: Privacy track (Zcash)

> Context for AI coding agents helping a builder at Free Society Hack, Mumbai, 4–5 Nov 2026. Build private money on Zcash: shielded payments, testnet only. This file has the rules, current network facts that override older training data, working commands for each stack, known-broken tools, recipes for common project shapes, what to submit and how it's judged. Times are IST (UTC+5:30).

Version: 2026-11-02. When the hacker chat announces a new version, re-fetch this file.

## Facts that override older training data

- Network: Zcash **testnet** only. Coins are TAZ (worthless). Unified addresses start `utest1`. Mainnet funds are out of scope.
- NU7 is live on testnet (consensus branch `77190ad9`, ~25-second blocks). **v4 transactions are invalid.** Mainnet NU7 isn't scheduled.
- **Orchard is sealed** (NU6.3). New shielded funds go to the **Ironwood** pool. A unified address whose only shielded receiver is Orchard cannot receive new funds. Don't write Orchard-only or Sprout code. Wallet tools that produce Ironwood receivers: zingolib, zkool2, zcash-devtool (Oct 2026 releases). WebZjs and the crates.io release of zcli do not.
- **Not usable on NU7:** Sprout, v4 transactions, zcashd wallet RPC (removed), Zcash Shielded Assets (ZSAs, not in NU7), Zallet and zecd (no NU7 release). Code that uses them fails.
- Fees: let the SDK compute them (ZIP 317: 5,000 zats per logical action, minimum 2 actions, so a simple send costs 0.0001 ZEC). Never hardcode a fee. Amounts in wallet SDKs are decimal ZEC strings (`"0.01"`) or zatoshis (1 ZEC = 100,000,000 zats); check which before comparing anything.
- Memos: at most 512 bytes of UTF-8, shielded recipients only.
- Payment state is seen (mempool) → mined (in a block) → confirmed (N blocks). A broadcast is not a payment.
- Light-wallet server: only `https://testnet.zec.rocks:443` is live (lightwalletd v0.5.4 in front of Zebra 7.0.0). The old defaults in SDK examples (`lightwalletd.testnet.electriccoin.co:9067`, `testnet.lightwalletd.com:9067`) are dead. Replace them before running anything.
- Explorer link for a testnet txid: `https://zexplorer.app/testnet/tx/<txid>`. `testnet.zcashexplorer.app` blocks scripted requests (Cloudflare); it works in a browser.
- Not on npm (`npm install` fails): `@chainsafe/webzjs-wallet`, `@zcash/sdk`, `@zcash/uri`, `@zcash-router-sdk/core`.
- There is no pure JavaScript or Python way to create an Ironwood address. Options: a Rust tool (zkool_graphql, zingo-cli, zcash-devtool) or the Noir testnet browser extension.

## First steps

Goal: one real shielded testnet payment, received and detected by your own code. Everything else builds on it.

1. **Make a testnet wallet and print a `utest1` address.** Confirm it has an Ironwood (or Sapling) receiver, not Orchard only. Ways to get one:
   - zkool_graphql: check https://github.com/hhanh00/zkool2/releases for a prebuilt binary for your OS; otherwise `cargo build` (about 30 min on 4 cores; start it first and keep working).
   - zingo-cli: `cargo build` (15–30 min).
   - Noir testnet browser extension: minutes, browser only; gives a `utest1` address and a wallet to send test payments from.
   - Rust tools download 50 MB of Sapling parameters (`sapling-spend.params`, `sapling-output.params`) from download.z.cash into `~/.zcash-params` on first start.
2. **Get TAZ.** Fauzec API, 1 TAZ per address per 24 h:
   ```
   curl -X POST https://fauzec.com/api/v1/claim -H 'Content-Type: application/json' \
     -d '{"network":"testnet","address":"utest1..."}'
   # 200 → {"request_id":"01M...","network":"testnet","state":"...", ...}
   # 400 → {"state":"failed","outcome":"refused","error_code":"unsupported_address_kind"}  (transparent or malformed address)
   curl https://fauzec.com/api/v1/status/testnet/<request_id>
   # poll until "state" is terminal; the body carries the txid once sent. 404 {"error_code":"claim_not_found"} = wrong id
   ```
   Fauzec takes `utest1` and `ztestsapling` addresses only (no transparent). Its web form has a Turnstile check; the API does not. OpenAPI: `https://fauzec.com/.well-known/openapi.json`. Valar (https://faucet.testnet.valargroup.dev/, `POST /api/claim`) gives 0.125 TAZ per **IP** per day, so at the venue it works once for the whole room. The Jino Labs faucet is paused for NU7. Any Zcash mentor can send TAZ: post your `utest1` address in the mentors chat.
3. **Watch it land.** Sync your wallet and list received notes or transactions; read the memo if one was sent. Record the txid and open it in the explorer. This is a candidate for the submission's testnet transaction ID: write it into README.md.
4. **Send one payment yourself** (wallet A → wallet B, or to your own address with a memo). Typical timings with zkool_graphql: faucet returns a txid at once; visible in the mempool within seconds; mined 1–2 minutes later. Own send: built and broadcast in ~10 s, mined within ~75 s.
5. **Write the plan**: one-line pitch, the one core flow, who the user is, and the trust-note hops (template below).

Stop and ask a mentor (in person or in the mentors chat) when: a faucet refuses you twice; a tool's sync is stuck below the NU7 height after 10 minutes; your `utest1` address shows only an "orchard" receiver; you want to use WebZjs or zcli; CipherPay rejects your key (tell Kenbak which host you used). Keep building the parts that don't depend on the answer.

## Testnet endpoints

- Public light-wallet server (lightwalletd gRPC): `https://testnet.zec.rocks:443`
- Faucets: [Fauzec](https://fauzec.com) (API above), [Valar](https://faucet.testnet.valargroup.dev/). Mentors send TAZ on request.
- Explorers: [Zexplorer](https://zexplorer.app) (`/testnet/tx/<txid>`), [testnet.zcashexplorer.app](https://testnet.zcashexplorer.app) (browser only).
- Local private network: [Thus Spoke Zakura v0.4.0](https://github.com/zcashlabs/thus-spoke-zakura/releases/tag/v0.4.0) (`curl … install.sh | sh`, needs Docker; `ths run`, `ths wallet faucet --accounts 2 --amount 1`, `ths endpoints --json`, `ths rpc`). NU7 on, own faucet, on-demand mining. It is **regtest**: addresses start `uregtest1` and its txids are not valid submission evidence.

## Stacks that work on NU7 testnet

| Building | Use | Install and run | Watch out |
| --- | --- | --- | --- |
| Backend, bot, payment watcher, anything headless | [zkool2](https://github.com/hhanh00/zkool2) `zkool_graphql`: GraphQL wallet server, NU7 + Ironwood, built-in NEAR Intents and FROST | See "zkool_graphql reference" below | Rust build (~30 min). The server exposes seeds when run unauthenticated (see below). |
| Hosted checkout, no wallet code | [CipherPay](https://cipherpay.app) testnet | See "CipherPay testnet" below | CipherPay holds your viewing key: it sees every payment and memo to that account. |
| Web dApp, user pays from their own wallet | [Noir Wallet SDK](https://docs.zknoir.com/noir-sdk-integration/) `npm i @noir-wallet/sdk` (0.1.9) | See "Noir Wallet SDK" below | Separate testnet extension build; SDK can't switch networks. |
| Rust CLI or bot | [Zingolib](https://github.com/zingolabs/zingolib) `zingo-cli` (8.0.0, Oct 2026, Ironwood) or [librustzcash](https://github.com/zcash/librustzcash) | `cargo build --release`; `zingo-cli --server https://testnet.zec.rocks:443 --chain testnet …`. Data dir and commands: `zingo-cli/README.md` | Long first build. |
| Terminal prototyping | [zcash-devtool](https://github.com/zcash/zcash-devtool) (Oct 2026, Ironwood) | `age-keygen -o id.txt`, then `cargo run --release -- wallet -w <dir> init --name demo -i id.txt -n test` (`-s zecrocks` picks the server), then `sync`, `balance`, `propose`/`send` | Not for production; long build. |
| Agent wallet with a spending cap over MCP | [zshield-mcp](https://github.com/Steeve-Crypto/zshield-mcp) | One tool `zcash_pay`: per-call cap, recipient allow-list, viewing-key-fingerprinted audit log. `npm run demo:mock` runs on a mock chain; the live adapter sends real testnet payments through zingo-cli | The default chain is a mock; a mocked payment is not a working demo. Replacing the stubbed chain layer with a real testnet backend is an open first issue (Steeve, maintainer). |
| Scaffold a Next.js shielded app | [create-zcash-app](https://www.npmjs.com/package/create-zcash-app) `npx create-zcash-app` (0.1.0-alpha.2, published 2 Nov) | Scaffolds Next.js + `@zcash-app/sdk` + `zcash-dev` (regtest helper: `mine`, `fund`, `switch`) | Alpha. Dre Kal (author) is a remote mentor after the hack. |
| Network privacy | [Nym Zcash SDK](https://zcash-sdk.nym.com/guidance/): `@nymproject/mix-fetch` 3.0.1 (browser); `nym-smolmix`, `nym-smoldvpn`, `nym-swizzle-zcash` crates (native) | mixFetch for **broadcast only**; compact-block sync over the mixnet is impractically slow. The 2-hop dVPN is for sync and needs NYM credentials (free subscription from Max Hampshire, Nym) | Example code hardcodes mainnet `zec.rocks`: point it at `testnet.zec.rocks`. Nym integrations can earn the Bonus point. |
| Read-only Zcash tools for an AI agent | [zcash-mcp](https://github.com/Frontier-Compute/zcash-mcp) `npx @frontiercompute/zcash-mcp` (1.4.0) | Block height, attestations, receipts | No spending, no payment detection. |
| Payment links and QR | ZIP 321 by hand: `zcash:utest1…?amount=0.01&memo=<base64url>`, or [@zcash/sdk](https://github.com/ronykris/zcash-sdk) `packages/uri` and `packages/qr` copied from the repo | Memo is base64url without padding | Not on npm. `@zcash/uri` only accepts `u1`, `zs1`, `t1` prefixes: patch it to allow `utest1`, `ztestsapling`, `tm`. |
| Zcash in MetaMask | [WebZjs Zcash Snap](https://npmjs.com/package/@chainsafe/webzjs-zcash-snap) 0.3.0, MetaMask Flask | | Built on WebZjs (see below): verify it can receive Ironwood funds before relying on it. |
| Android / iOS | [Zcash Android Wallet SDK](https://github.com/zcash/zcash-android-wallet-sdk), [Zcash Swift Wallet SDK](https://github.com/zcash/zcash-swift-wallet-sdk); reference apps [Zodl Android](https://github.com/zodl-inc/zodl-android), [Zodl iOS](https://github.com/zodl-inc/zodl-ios) | | Check the SDK version supports NU7 before building. |
| Shared custody | [FROST](https://frost.zfnd.org/); zkool2 has `frost*` and `dkg*` GraphQL operations | | |

## Tools that don't work on NU7 testnet or need workarounds

- **WebZjs** (`@chainsafe/webzjs-wallet`): not on npm; last commit April 2026; pinned to a ChainSafe NU6.1 fork of librustzcash (`librustzcash-nu61`, branch `feat/snap-nu61`) with no Ironwood support. Building it needs Rust nightly-2025-01-07, wasm-pack, `just`, yarn and a gRPC-web proxy (`docker-compose up`).
- **zcli / zecli**: `cargo install zecli` gives 0.6.0, which fails to build without `protoc` (`apt-get install protobuf-compiler`), then makes Orchard-only `utest1` addresses (cannot receive funds), and its backend answers "upgrade the client newer than 0.9.0". The git version (0.10.0, Ironwood) needs a `zidecar` server as its primary endpoint; none is hosted for testnet. Check any zcli with `zcli --testnet --json address`: if the only shielded key is `orchard`, the address cannot receive funds.
- **ZPay**: needs a separate `zinder` wallet-serving stack in Docker; no hosted instance exists.
- **Zallet**, **zecd**: no NU7 release.
- **Zcash Router SDK** (nufi): mainnet only (Solana↔Zcash via NEAR Intents), last commit Dec 2025, not on npm.

## zkool_graphql reference

Build: `git clone https://github.com/hhanh00/zkool2 && cd zkool2/rust && cargo build --release --features graphql --bin zkool_graphql`. The binary lands in `zkool2/target/release/`. Needs the Rust toolchain.

Run:
```
zkool_graphql -d wallet.db -p 8000 -l https://testnet.zec.rocks:443 -C 1 --allow-unauthenticated --allow-unencrypted-database
```
- `-C 1` = testnet; it applies only when creating a new database.
- **`--allow-unauthenticated` exposes every field, including `accounts { seed }`, to anyone who can reach the port.** Don't run an account with a seed that way on a network others can reach (venue wifi included). Run watch-only (UFVK) accounts on any reachable machine; keep seed accounts on localhost or behind JWT (`-j`).
- First start downloads the Sapling parameters (50 MB) from download.z.cash into `~/.zcash-params`.

GraphQL endpoint: `http://localhost:8000/graphql` (POST `{"query": "..."}`). Calls:
- `{ currentHeight }`
- `mutation { createAccount(newAccount: { name: "hack", key: "", useInternal: true, aindex: 0 }) }` → account id.
- Watch-only account: pass a `uviewtest…` UFVK as `key` and **set `birth`** to a height at or below the first payment you care about. Without `birth`, the account starts at the current tip and syncs with no history and balance 0. A watch-only account has no spending key: `pay` on it returns `{"errors":[{"message":"No Signing Key"}]}`.
- `{ addressByAccount(idAccount: 1) { ua } }` → `utest1…` with transparent, Sapling and Ironwood receivers (`pools: 4` gives an Ironwood-only UA).
- `{ unifiedFullViewingKey(idAccount: 1) }` → `uviewtest…`
- `mutation { synchronize(idAccounts: [1], fast: false) }` → height.
- `{ unconfirmedByAccount(idAccount: 1) { txid value } }`: payments seen in the mempool. It keeps listing txids after they are mined, so treat a txid as seen once and confirm it via `transactionsByAccount` height.
- `{ transactionsByAccount(idAccount: 1) { id txid height time value fee notes { pool value address scope memo } } }`:
  - `time` is the block time (UTC).
  - `value` is the net change of the whole account; a self-send with a memo shows `-0.0001` (just the fee). Test amount checks with a second wallet, not a self-send.
  - The amount a payer sent you is `notes[].value` on notes with `scope: 0`; `scope: 1` is change.
  - `notes[].memo` carries the memo. `pool`: 0 transparent, 1 Sapling, 2 Orchard, 3 Ironwood.
  - `id`s are per-account row ids; correlate on `txid`.
- `{ memosByTransaction(idAccount: 1, idTransaction: <id>) }` → `["ORDER-42"]`
- `{ balanceByAccount(idAccount: 1) { transparent sapling orchard ironwood } }`
- `mutation { pay(idAccount: 1, payment: { recipients: [{ address: "utest1…", amount: 0.01, memo: "ORDER-42" }], confirmations: 1 }) }` → txid in ~10 s. Run `synchronize(idAccounts: [1])` on the spending account before each `pay`, or the second one fails with `No feasible note selection found`.
- `{ transactionById(idAccount: 1, txid: "…") { height time value } }`
- Also available: `prepareSend`, `signTx`, `broadcastTx`, `mempoolStream`, `subscribe` (events), `nearIntentsQuote`, `nearIntentsSubmitDeposit`, `nearIntentsStatus`.
- Introspect anything else: `{ __type(name: "Mutation") { fields { name args { name type { name ofType { name } } } } } }`.
- Sample scripts: `example/sh`, `example/js`, `example/py`; MCP server: `example/zkool-mcp`.

## CipherPay testnet

Testnet is a separate environment from mainnet (`cipherpay.app`, `api.cipherpay.app`); there is no toggle.
1. Export your testnet UFVK (`uviewtest…`; zkool_graphql `unifiedFullViewingKey`, zingo-cli per its README).
2. Register at `https://testnet.cipherpay.app/dashboard/register` and paste it.
3. Dashboard: copy the API key `cpay_sk_…`; set the webhook URL (plain `http://` allowed on testnet; set in the dashboard, not per invoice) and copy the `whsec_…` secret from Settings.
4. `POST https://api.testnet.cipherpay.app/api/invoices` with `Authorization: Bearer cpay_sk_…` and `{"amount":0.5,"currency":"USD","product_name":"Order 42"}` → `{invoice_id, memo_code, price_zec, zcash_uri, payment_address, expires_at}`. Render `zcash_uri` as a QR (`npm i qrcode`) or link the hosted pay page on `testnet.cipherpay.app/pay/{invoice_id}`.

Webhooks:
- Events: `detected`, `confirmed`, `underpaid`, `expired`, `invoice.created`.
- Payload: `{event, invoice_id, txid, timestamp, price_zec, received_zec, overpaid}`.
- Headers: `X-CipherPay-Signature` = HMAC-SHA256 hex of `X-CipherPay-Timestamp + "." + raw body`, keyed with `whsec_…`. Verify over the raw bytes (not re-serialised JSON), compare in constant time, reject timestamps older than 5 minutes.
- `X-CipherPay-Delivery-Id`: retries happen, so dedupe on it. Return 200 for invoices you don't know.
- Fulfil on `confirmed` (1 block), never on `detected`.

Not in the public docs: a GET-invoice endpoint, the webhook retry count and window. Ask Kenbak (CipherPay, remote). CORS is open on testnet.

## Noir Wallet SDK

- `const w = getNoirWallet(); if (!w) …` reads `window.noirwallet`. It can be null on first render; retry after load.
- `const c = await w.zcash.connect()` must be called from a click. It returns `{ transparent, shielded, accounts[] }`. On reload, `await w.zcash.getAccounts()` is silent and returns `null` if not connected.
- Balance: `const b = await w.zcash.getBalance()` → `b.shielded` as a decimal ZEC string; `synced === false` means the value is cached.
- Fee for a confirmation screen: there is no per-amount estimate. `const { maxAmount, fee } = await w.zcash.getMaxTransfer({ to, memo, fundingSource: 'shielded' })` gives the ZIP 317 fee of the send-max proposal, which is approximate for smaller sends.
- Send: `await w.zcash.sendTransaction({ to: 'utest1…', amount: '0.01', memo: 'order 42', fundingSource: 'shielded' })` returns a txid after the user approves in the popup. `fundingSource` needs extension ≥1.0.27 (omitted, it defaults to shielded).
- Events: `w.zcash.on('accountsChanged', …)`.
- Testnet is a separate extension: download the release asset ending `-testnet.zip` from https://github.com/NoirWallet/noir-wallet/releases and load it unpacked. It installs as "[Testnet] Noir Wallet".
- `switchNetwork()` throws and there is no `getNetwork()`: validate the recipient prefix (`utest1`, `ztestsapling`) yourself.
- No confirmation API: watch the txid with your own viewing-key watcher or the explorer.
- Memo ≤512 bytes, shielded recipients only.
- The full API is in the SDK's `.d.ts` in `node_modules`.
- Noir's suggested first project is a React dApp that connects, shows the balance and sends a shielded payment. Noir integrations can earn the Bonus point. Questions (including which light-wallet server the testnet build syncs through): Max (Noir).

## Taking a payment (the pattern behind most projects)

1. Ask: a `zcash:` payment URI and QR ([ZIP 321](https://zips.z.cash/zip-0321)) with address, amount and the order ID in the memo. A memo is encrypted on-chain; only holders of the receiver's viewing key can read it.
2. Detect: give the server a **viewing key** ([ZIP 316](https://zips.z.cash/zip-0316) unified full viewing key, `uviewtest…`). It sees incoming payments and memos but can't spend. The spending key stays off the server.
3. Confirm: wait until the payment is mined; larger amounts warrant more confirmations. Act exactly once per txid (store txids you've acted on). State in the README which confirmation threshold you chose.

Testnet timing: mempool visibility within seconds, mined in ~30–90 s.

## Recipes for common project shapes

**A. Checkout matched by memo (Theme 1).** zkool_graphql watch-only account + ZIP 321 link. Server: create an invoice (order code → memo), show the URI and QR, poll `transactionsByAccount` and `memosByTransaction` (or `subscribe`), match the memo, mark paid after 1 block. Stranger test: a judge with a testnet wallet pays and sees "paid". Bonus candidate: publish the watcher as a small library or npm package.

**B. Hosted checkout (Theme 1).** CipherPay testnet invoice + webhook handler. Verify the signature over the raw body, dedupe on delivery ID, act on `confirmed` only, record `overpaid` for a manual refund, never fulfil `underpaid`. A local fake that signs test webhooks with the same HMAC lets you build before registering. A judge pays from a testnet wallet (Noir testnet extension, or Zingo! with testnet enabled).

**C. dApp with the user's own wallet (Theme 2, Noir partner).** React + `@noir-wallet/sdk`: connect, show balance, plain-language confirmation screen (who, how much, approximate fee from `getMaxTransfer().fee`, who can see it: the recipient sees amount and memo; chain observers see that a shielded tx happened and its fee; Noir's light-wallet server sees IP and timing; your page stores what you say it stores), send with memo, show the txid and explorer link, then watch confirmation with recipe A on the receiving side.

**D. Agent pays per call (Theme 1, HTTP 402).** An API that answers 402 with a ZIP 321 URI and a nonce in the memo; the agent wallet (zkool_graphql `pay`, or zshield-mcp `zcash_pay` with its cap) pays; the API's viewing-key watcher unlocks the call when the memo arrives. The spending cap lives in code, not in the prompt.

**E. Privacy beyond the transaction (Theme 3).** Viewing-key export to CSV/JSON: create a zkool_graphql account from the UFVK with `birth`, `synchronize`, then `transactionsByAccount { txid height time fee notes { value scope memo address } }` and emit one row per `scope: 0` note (txid, height, time, amount, memo, `https://zexplorer.app/testnet/tx/<txid>`). Prove read-only access by calling `pay` once on the watch-only account and quoting the `No Signing Key` error. A receipt for one txid: the explorer proves only existence, height and fee; amount and memo are checkable only by another holder of the viewing key. Other Theme 3 shapes: invoices or tickets in encrypted memos; broadcasts through Nym mixFetch (Nym is the host partner).

**F. Both tracks: shielded payment triggers a Bitrefill purchase (Lane 5 + Theme 1).** Testnet TAZ cannot pay Bitrefill. The loop: shielded testnet payment with an order code in the memo → your watch-only account sees it (`unconfirmedByAccount`), then confirms it mined (`transactionsByAccount` height) → guardrails (allowed product, cap, one purchase per txid, reserved before the call) → Bitrefill REST v2 `POST /invoices` with `payment_method: "balance"`, `auto_pay: true` from event credits → poll to `delivered` → receipt. The phone number for a top-up either travels in the memo (stored next to the txid until delivery) or sits in a server-side allowlist keyed by order code; the trust note says which. Accurate pitch: "a shielded payment authorises the purchase", not "pays for it". Exact Bitrefill fields: Agentic Commerce file.

**G. Mainnet route for real ZEC → Bitrefill (not testnet; no testnet exists for it).** Bitrefill takes no ZEC. Route: shielded ZEC → deshield to a transparent `t1` address → NEAR Intents 1Click (ZEC → USDC on Base, into a Base wallet you control) → Bitrefill `usdc_base` invoice paid from that wallet.
- API `https://1click.chaindefuser.com/v0` (docs: https://docs.near-intents.org, "1Click API"). `GET /v0/tokens` lists assets with decimals and a USD price.
- `POST /v0/quote` body: `{dry:true, swapType:"EXACT_INPUT", slippageTolerance:100, originAsset:"nep141:zec.omft.near", destinationAsset:"nep141:base-0x833589fcd6edb6e08f4c7c32d4f71b54bda02913.omft.near", amount:"1000000", depositType:"ORIGIN_CHAIN", refundTo:"t1…", refundType:"ORIGIN_CHAIN", recipient:"0x…", recipientType:"DESTINATION_CHAIN", deadline:"<ISO 8601>"}`. `dry:true` quotes without creating a deposit address.
- ZEC has 8 decimals (amount in zatoshis as a string); USDC has 6.
- `refundTo` must be a mainnet `t1…` (`utest1`, `u1`, `tm` and shielded addresses get 400 "refundTo is not valid"). `recipient` must be a Base account you control (burn addresses and token contracts get 400 "recipient is not valid").
- Minimum 132,000 zats (0.00132 ZEC); the error message names it.
- Example quote (ZEC ≈ $1,248): 0.01 ZEC → 12.40–12.45 USDC, fee $0.02–0.05, `timeEstimate` ≈ 460 s. The response carries `refundFee` (32,000 zats withheld on refunds), `withdrawFee`, and a default `appFees:[{fee:20}]` (20 bps) when none is passed.
- Live flow: `dry:false` returns `quote.depositAddress` and `deadline`; deshield exactly `amountIn` to it before the deadline; optionally `POST /v0/deposit/submit {txHash, depositAddress}`; poll `GET /v0/status?depositAddress=…` through `PENDING_DEPOSIT → KNOWN_DEPOSIT_TX → PROCESSING → SUCCESS` (or `REFUNDED`, `FAILED`, `INCOMPLETE_DEPOSIT`: late or short deposits are refunded to `refundTo` minus `refundFee`, publicly).
- Create the Bitrefill invoice (`POST /v2/invoices`, `payment_method:"usdc_base"`) only after the USDC lands (invoice quotes expire in minutes); pay it from the recipient wallet (needs a little ETH on Base for gas).
- zkool_graphql wraps this as `nearIntentsQuote`, `nearIntentsSubmitDeposit`, `nearIntentsStatus`.
- What's visible: deshielding publishes the deposit address, amount and timing; 1Click and its solvers see recipient, refundTo and your IP and hold the funds for ~8 minutes; Base shows USDC arriving and leaving for Bitrefill; Bitrefill links the paying address to the phone number or email.

## Themes (pick one, or bring an idea that fits one)

1. Private payment rails: checkout matched by memo, batch payouts, payment links, HTTP 402 per-call APIs, capped agent wallets, @zcash/sdk pieces, starter templates, MCP servers or an llms.txt so AI agents write current Zcash code.
2. The first five minutes: onboarding to a first shielded payment in minutes, paying a name, plain confirmation screens, translations, low-end phones. Test with someone who didn't build it.
3. Privacy beyond the transaction: viewing-key exports, verifiable receipts, 2-of-3 treasuries, tickets or invoices in encrypted memos, network privacy (Nym is the host partner).

Partners want to see: Noir Wallet (private payment and checkout apps, Zcash DeFi, AI apps that pay in shielded ZEC); Nym (network privacy, Theme 3). Stand-out Nym or Noir integrations can earn the Bonus point.

## Rules

- Hacking runs Wed 4 Nov 11:00 to Thu 5 Nov 00:00. All code is made in that window: new repo on the day, judges check commit history. Open-source libraries, SDKs and templates are fine.
- Solo or a team of up to 4 including the point person; the point person receives any prize.
- One submission per project: pick Privacy, or Both to enter and win in both tracks (then fill in both tracks' fields).
- Submit on [Stadium](https://stadium.joinwebzero.com/programs/free-society-hack-2026) with the point person's Luma email. Save a draft early (only you see it), give teammates edit access from the team list (their Luma email must be checked in), submit the event feedback, then click **Finalize and submit** by Wed 4 Nov 20:00 to be in the first judging session (20:00–22:00). Drafts are not judged. After finalizing you can keep editing until 00:00. Code after 00:00 isn't scored.
- Never put spending keys or seed phrases in code, logs, prompts or the repo. Viewing keys are fine on the server; label them.

## Submission checklist

Judges score from the submission only. Every item is required unless marked.

- [ ] One-line pitch: what it does and for whom. Works is scored against it.
- [ ] Public repo (new on the day) with a README that lists every technology used and the design decisions.
- [ ] One testnet transaction ID the project created (shielded, `utest1` addresses, public testnet, not Zakura). Stadium checks it and shows judges a badge; a failed check doesn't block you.
- [ ] Optional: the viewing key (uviewtest…) and birth height of the wallet that received the payment, so judges can see the amount and memo. Use the demo wallet: the key reveals that wallet’s whole history but cannot spend. zkool_graphql: unifiedFullViewingKey; zingo-cli: see its README.
- [ ] Public testnet URL if it's an app people use (web app, checkout, dashboard). SDKs, CLIs, bots, agents and backends skip it and show the transaction in the video or README (explorer link).
- [ ] Privacy and trust note (template below).
- [ ] Next step for the 30 days after, with links to anything started.
- [ ] Demo video, 2–3 minutes (judges watch only the first 3), every step real. Optional but the easiest way to prove Works.
- [ ] FEEDBACK.md in the repo (optional, not scored; it goes to the teams who fix things): what broke, confused or slowed the builder, by area. Paste it into Stadium's friction notes field and tag the areas. The builder writes the final version.

Privacy and trust note template:

```
1. What stays private: sender, receiver and amount are shielded on-chain; the memo is encrypted.
2. What the app reveals, to whom:
   - the light-wallet server (testnet.zec.rocks) sees the watcher's IP and sync timing
   - CipherPay (if used) holds our viewing key and sees invoices, txids, amounts and memos
   - our server stores <order codes / txids / nothing else>; emails or phone numbers <are / are not> stored next to txids
   - Bitrefill (if used) sees the purchase, the phone number or email, and our account
   - the AI model provider (if an LLM is in the loop) sees <what you send it>
3. Who users must trust: us as operator; <each party above>.
4. What we'd fix next: <e.g. Nym for the watcher's traffic; delete order data after delivery>.
```

FEEDBACK.md skeleton (delete empty areas):

```
# Feedback
## Faucet
## Node or indexer (lightwalletd, Zebra, Zaino)
## SDK or wallet tool (which one, which version)
## Wallet
## Docs
## Other
For each item: what you tried, what happened, what you expected, a link or error message.
```

Full README template (copy it into the repo as README.md): https://stadium.joinwebzero.com/programs/free-society-hack-2026/privacy/README-template.md

README skeleton:

```
# <Name>: <one-line pitch>
## Who it's for and the problem   (real evidence only: who you talked to, what they said)
## Demo: <video link> · <public URL> · testnet tx: <txid + https://zexplorer.app/testnet/tx/...> · viewing key (optional): <uviewtest…, birth height>
## Run it (under 15 minutes)
## How it works (core flow, step by step; mark any manual step)
## Privacy and trust note
1. What stays private  2. What the app reveals, to whom  3. Who users must trust  4. What we'd fix next
## Technologies used (every one, with versions)
## Next 30 days (with links to anything started: issue, PR, forum post, partner message)
## Feedback: see FEEDBACK.md
```

## Judging (0–3 per criterion, max 16 with Bonus)

- **Works:** one core flow running for real on testnet, end to end, with the txid as evidence. A mocked or manual core step caps the score; a small flow that fully works can score 3. Works 0 can't win.
- **Private:** what the server stores and logs, and an honest trust note naming the server, the light-wallet server, any processor, any model provider and the operator. Self-custody alone isn't a privacy design.
- **Easy:** the intended user finishes the core task unaided, in minutes.
- **Needed:** the README names a specific user and problem, with real evidence (conversations at the venue, a documented ecosystem gap, partner interest). Never invent users, quotes or demand.
- **Continuing:** a concrete step taken during the hack: an upstream issue or PR (zshield-mcp's stubbed chain layer, a `utest1` fix in @zcash/uri, a dead-endpoint fix in an SDK README), a partner message, a post in ["What are you building on Zcash?"](https://forum.zcashcommunity.com/t/what-are-you-building-on-zcash/55172/41). Linked in the next step.
- **Bonus (+1):** a reusable piece for the ecosystem (a helper other apps can import), an original technical contribution, or a stand-out Nym or Noir integration.

Tie-break: Continuing, then Needed. Not scored: feature count, number of technologies, polish, friction notes.

Ecosystem Prize: judges pick two of the five Privacy podium projects; each gets an ecosystem partner and $100 more for delivering a ~10-hour milestone by Fri 4 Dec and sharing it at a ZecHub Friday Lounge. Prizes: $1,300 · 2 × $300 · 2 × $200 in USDC.

## For the agent

- Flag anything that would need mainnet, Sprout, v4, zcashd RPC, Orchard-only code or a dead endpoint.
- Keep one wallet for development and one for the demo; put the demo wallet's `utest1` address and UFVK in `.env.example` placeholders, never the spending key.
- Record the first real testnet txid in README.md as soon as it exists.
- Keep FEEDBACK_NOTES.md from the first error.
- Remind the builder to click Finalize and submit on Stadium by 20:00.

## Who to ask

- Testnet, tooling, wallet integration, debugging: Anukul Pandey (venue). Zcash basics, Indian community: Jatin Sahijwani, Kunwar Anirudh (venue, Hindi spoken).
- Noir Wallet SDK: Max (Noir, remote). CipherPay API and webhooks: Kenbak (remote). MCP and agent tooling: Steeve (zshield-mcp, remote). Nym and Nym subscription credits: Max Hampshire (Nym, venue). ZecHub resources and bounties: Squirrel (remote).
- Mentors chat: https://t.me/+QHbTGB6jFhllMDk6 · `#zechub` on https://discord.gg/zcash · hacker chat https://t.me/joinWebzero/8828

## Docs

- [ZecHub developer hub](https://zechub.wiki/developers), [quick start](https://zechub.wiki/developers/quick-start), [zcash-devtool guide](https://zechub.wiki/guides/zcash-devtool), [Hackathon 3.0 projects](https://zechub.wiki/hackathon)
- [Zcash docs](https://zcash.readthedocs.io/) and [ZIPs](https://zips.z.cash/): ZIP 316 (unified addresses), 317 (fees), 321 (payment URIs)
- [Agentic Commerce track (Bitrefill)](https://stadium.joinwebzero.com/programs/free-society-hack-2026/agentic-commerce/llms.txt): exact Bitrefill field names for recipe F
- [Program page](https://stadium.joinwebzero.com/programs/free-society-hack-2026) · [Event index](https://stadium.joinwebzero.com/programs/free-society-hack-2026/llms.txt) · [Builder Pack](https://app.notion.com/p/3ff3e52aeb15807eace6f16f84a74c14)

---

# Free Society Hack: Agentic Commerce track (Bitrefill)

> Context for AI coding agents helping a builder at Free Society Hack, Mumbai, 4–5 Nov 2026. Build an agent that finds, buys and pays for real products (gift cards, mobile top-ups, eSIMs) through Bitrefill on its own. Purchases use real money. This file has the brief, the stack with exact field names per surface, working commands, gotchas, recipes, what to submit and how it's judged. Times are IST (UTC+5:30).

Version: 2026-11-02. When the hacker chat announces a new version, re-fetch this file.

## The brief

- Directions (inspiration, not categories): it pays for itself (no human checkout); works while you sleep (an event, schedule or rule triggers buying); shop from chat. Crypto payments and India-relevant products are encouraged.
- The loop: user → trigger → guarantee (budgets, approvals, receipts) → fulfillment (Bitrefill: search, buy, pay, deliver) → ending (redeemed, installed, delivered, reconciled). Bitrefill already covers fulfillment, and the Bitrefill Assistant on Telegram already turns a chat into an order. Ideas that stand out add a new trigger, guarantee, ending or user.
- Everything is real: real products, real delivery, real money. A delivered code can't be refunded. The Bitrefill team hands out event credits for testing.

## First steps

Goal: the exact product and price confirmed, a spend cap in code, one unpaid invoice created on a zero-balance account. Nothing bought yet.

1. **Install the CLI and confirm the catalog without an account:**
   ```
   npm i -g @bitrefill/cli          # 0.3.0
   bitrefill --json search-products --query airtel --country IN --intent "hackathon demo top-up"
   bitrefill --json get-product-details --product_id airtel-india
   bitrefill llm-context -o BITREFILL-MCP.md
   ```
   - `search-products` requires `--intent "<why>"` (not in the docs; the command errors without it; the MCP tool has the same required `intent`).
   - `get-product-details` takes `--product_id`, not `--id`. It returns `packages[{package_value:"10", package_currency:"INR", payment_price:"0.11", payment_currency:"USD"}]`, `recipient_type` (`phone_number`, `account`, `email`, `username`, `none`), `in_stock` and `payment_methods`.
   - `buy-products` carries no price: a spend cap must price the cart from `payment_price` first.
   - `bitrefill llm-context` works without an account and writes the MCP/CLI tool docs, including the only published copy of the full `buy-products` JSON schema. REST builders use the Docs MCP or https://docs.bitrefill.com/llms.txt instead.
2. **Write the guardrail module**: allowed product IDs and values, max per purchase, max per day, one purchase per trigger (dedupe key), what happens above the cap (nothing is bought; a human approves). "Guardrails" is a required submission item.
3. **Get an API key on a zero-balance account** at https://www.bitrefill.com/account/developers (API Keys tab); keep it in `.env` only. `POST /v2/invoices` with `payment_method: "lightning"` (or any crypto method) and no payment returns an unpaid invoice that expires. On a zero-balance account a bug can only create unpaid invoices.
4. **Ask the Bitrefill team** (Max N, Ankush Mehta, Aamir Shaikh, at the venue) for event credits, and whether free test products (`test-gift-card-code` on REST, `delos-syldavia` on MCP) can be enabled on your account.
5. **Once the guardrails pass**, switch to the credited account and make one real cheap purchase (₹50 Flipkart or ₹10 Airtel) through your own code. Record the invoice ID in README.md when it's delivered.

Stop and ask the Bitrefill team when: the MCP returns 401 with your key (header format), `buy-products` rejects a `package_value` you copied, your account hits a daily cap, an order is `failed` or an invoice `blocked`, or you need a second phone number to top up. Keep building the parts that don't depend on the answer.

## Surfaces

| Surface | Best for | How |
| --- | --- | --- |
| **eCommerce MCP** `https://api.bitrefill.com/mcp` | Agents in Claude, ChatGPT, Cursor, Codex, Gemini CLI or your own MCP client | Auth: OAuth when the client supports it (authorization server `https://api.bitrefill.com/oauth/mcp`, scopes `mcp`, `cli`), or the API key as `Authorization: Bearer <key>`, or in the path `https://api.bitrefill.com/mcp/<key>` for clients without headers. Unauthenticated requests get 401. Tools: `search-products`, `get-product-details`, `buy-products`, `get-invoice-by-id`, plus help-centre tools. Signed in: every tool and balance payments. Guest (OAuth client credentials): 7 tools, must give an `email`, pays with crypto or a payment link, reads the invoice with the `invoice_access_token` returned at purchase. |
| **Agent Skills** `npx skills add bitrefill/agents` | Adding Bitrefill to an existing agent | Claude Code / Cowork: `/plugin marketplace add bitrefill/agents` then `/plugin install bitrefill@bitrefill-skills`. Installs the skill and the MCP server. The skill confirms each purchase with the user by design; an autonomous agent calls the REST API or MCP directly with guardrails in code. |
| **REST API v2** `https://api.bitrefill.com/v2` | Backends and event-driven apps ("works while you sleep") | `Authorization: Bearer <key>`. `GET /ping`, `GET /accounts/balance`, `GET /products/search?q=…`, `GET /products/{id}`, `POST /invoices`, `POST /invoices/{id}/pay`, `GET /invoices/{id}`, `GET /orders/{id}`. `auto_pay: true` pays a balance invoice at once. `webhook_url` on the invoice gets a POST of the full invoice at a final state. |
| **CLI** `npm install -g @bitrefill/cli` (0.3.0) | Shell agents, scripts, cron jobs | Works without an account (returns a payment link) or `bitrefill login --email`. `--json` for machine output (results on stdout, messages on stderr). `bitrefill manifest` gives a JSON schema of every command. |
| **x402** `https://api.bitrefill.com/x402/*` | Agents with a wallet and no Bitrefill account | `/x402/invoice/create`, `/x402/invoice/pay`, `/x402/invoice/status`, `/x402/my/orders`, `/x402/my/esims`. Small USDC fee per call, free after `POST /x402/connect` (wallet sign-in). USDC, **mainnet only**. Poll `invoice/status` until `delivery_status: all_delivered`. |
| **Docs MCP** `https://docs.bitrefill.com/mcp` | Your coding agent while you build | Tools `list-endpoints`, `get-endpoint`, `search-endpoints`, `execute-request`, `get-server-variables`. Never give it your API key. Plain docs: https://docs.bitrefill.com/llms.txt |

Payment methods: balance (event credits), bitcoin, lightning, ark, ethereum, eth_base, eth_arbitrum, solana, litecoin, dogecoin, dash, ton, and USDC/USDT on Ethereum, Base, Polygon, Arbitrum, Solana, Tron, BSC or TON (`usdc_base`, `usdt_trc20`, …). For a crypto method the invoice response gives a payment address and exact amount; send from a wallet you control (USDC on Base needs a little ETH for gas). ZEC isn't accepted (see recipe E).

REST responses: every 2xx body is `{ "meta": {...}, "data": {...} }`; read `data`. `POST /invoices` and `GET /invoices/{id}` return the invoice: `data.id`, `data.status`, `data.payment.{method, status, price, currency}`, `data.orders[]` each with `id` and `status`. `GET /orders/{id}` returns `data.status` and `data.redemption_info`. `GET /products/{id}` returns `data.packages[]` with `value` and the USD price. Errors are flat: `{ "message": "...", "status": "invalid_token" }`. For any other field ask the Docs MCP (`get-endpoint` with path `/invoices`, method `POST`).

## Field names differ per surface

| | MCP and CLI `buy-products` | REST v2 `POST /invoices` |
| --- | --- | --- |
| Items | `cart_items: [{ product_id, package_value, refill_input? }]` (max 15) | `products: [{ product_id, quantity, value | package_id, phone_number? }]` (max 20) |
| Denomination | `package_value` copied from `get-product-details` → `packages[].package_value` (`"10"`, `"1GB, 7 Days"`); price it from the same package's `payment_price`/`payment_currency`. `package_id` is deprecated here | `value` (number in the product's currency, `10` for ₹10; the docs' own examples use it for fixed packages too) or `package_id` (only if the product lists one) |
| Phone for top-ups | `refill_input`: international format **without `+`** (`"919876543210"`) | `phone_number`: country code + number; the digits-only format is unconfirmed (ask the Bitrefill team) |
| Payment | `payment_method` (required): `"balance"`, a crypto method, or a fiat method (needs `billing_address`) | `payment_method`, `auto_pay: true` to pay from balance now |
| Receipt | `email` (required) | account email |
| Delivery event | poll `get-invoice-by-id` (`invoice_id`, plus `invoice_access_token` for guests) | `webhook_url` on the invoice, or poll `GET /invoices/{id}` then `GET /orders/{id}` |

Other gotchas:
- `package_value` is case-sensitive and Jio plan names contain en dashes: copy values, never retype them. Country codes are uppercase Alpha-2 (`IN`).
- `webhook_url` is in the Webhooks guide but missing from the OpenAPI spec the Docs MCP serves. It works.
- The OpenAPI `servers` entry says `api-bitrefill.com`; the real host is `api.bitrefill.com`.
- Rate limits: the MCP's `ratelimit-limit` header says 60 requests per 30 s per token (the docs say 30/min); x402 30/min and 10 invoice creations/min per IP. Cache the catalog.
- Tool names: commerce tools are hyphenated (`buy-products`); help-centre tools use underscores (`search_help_articles`, `get_help_article`).
- `buy-products` returns the invoice with `invoice_id` (and `invoice_access_token` for guests) and a `payment_link` for link-only methods; orders and codes arrive via `get-invoice-by-id`. A top-up with `recipient_type: phone_number` needs `refill_input`.
- MCP auth with an API key: the 401 carries no OAuth discovery metadata for API-key clients; pass the key as a Bearer header.
- Node's `fetch` ignores `HTTPS_PROXY`; behind a corporate or sandbox proxy, give the MCP SDK client an undici `EnvHttpProxyAgent`, or requests hang silently.
- Invoice quotes expire within minutes: create the invoice right before paying. x402 needs an invoice under 15 minutes old.
- x402 amount check: open issue [bitrefill/agents#11](https://github.com/bitrefill/agents/issues/11) reports that paying an MCP-created invoice's `x402_payment_url` can return a 1,000 USDC placeholder. Create x402 invoices with `/x402/invoice/create` and refuse any 402 challenge that doesn't match the invoice total.
- Bitrefill's x402 is mainnet only; your own x402 server can be tested on Base Sepolia with the x402.org testnet facilitator.
- MCP clients with auto-approve will run `buy-products` without asking.
- Daily caps per account: 5 phone top-ups (2 without an account) and 15 gift cards. Teams sharing one account share the caps.
- Free test products are hidden until Bitrefill enables them per account. Paying an MCP test product from balance debits the real balance.
- Codes are cash: never log, print, commit or post them; mask them on screen.

## Statuses and "done"

Three vocabularies; don't mix them.

- Invoice (`GET /invoices/{id}`, `get-invoice-by-id`): `unpaid` → `payment_detected` → `payment_confirmed` → `pending` → `complete`, or `blocked`, `denied`, `payment_error`. `complete` means the invoice is finalised, **not** that every order delivered.
- Order (`GET /orders/{id}`): `created` → `payment_detected` → `processing` → `delivered`, or `failed`, `refunded`. `delivered` is the finish line; `redemption_info` holds `code`, `link`, `pin`, `instructions`.
- x402: `delivery_status: all_delivered`.

Webhooks: the payload is the full invoice, POSTed at `complete`, `denied` or `payment_error`, retried on failure (so duplicates arrive), with **no signature header** documented. Respond 200 fast, then re-fetch the invoice and each order with your API key before acting, and dedupe on invoice ID. A random token in the webhook path (`webhook_url: "https://…/hooks/bitrefill/<random>"`) lets you reject other callers.

Cases to handle: `429` (back off, retry), expired quote (create a new invoice), `failed` order (report; retrying blindly can hit a cap), out of stock (`in_stock: false`), `blocked` (ask the Bitrefill team).

## Recipes

**A. Event-driven top-up worker (Lane 3 or 4, REST v2).** Trigger (webhook, cron, weather alert, merged PR) → guardrails → `POST /invoices {products:[{product_id:"airtel-india", value:10, quantity:1, phone_number:"91…"}], payment_method:"balance", auto_pay:true, webhook_url:"https://…"}` → on webhook or poll, `GET /orders/{id}` until `delivered` → notify. Dedupe on the trigger ID and reserve it in your store **before** the `POST`: a crash between the POST and your write would otherwise buy twice on replay.

**B. Spend firewall in front of the MCP (Lane 1).** Two transports: the agent (Claude Desktop, Cursor) launches your proxy as a local **stdio** MCP server from its config; your proxy connects to `https://api.bitrefill.com/mcp` as a **Streamable HTTP** client. With `@modelcontextprotocol/sdk`: `new StreamableHTTPClientTransport(new URL(url), { requestInit: { headers: { Authorization: "Bearer " + process.env.BITREFILL_API_KEY } } })`. On start, `listTools()` upstream and re-expose `search-products`, `get-product-details`, `get-invoice-by-id` with their schemas unchanged; intercept `buy-products`: price each `cart_items[]` entry from `get-product-details` → `packages[].payment_price` (cache it), enforce allow-list, per-purchase and per-day caps, and above the cap return a normal tool result `{status:"needs_approval", approval_id, total_usd}` without calling upstream. Approval happens out of band (CLI or Telegram), never through an MCP tool the agent can call. Claude Desktop config: `{"mcpServers":{"bitrefill-firewall":{"command":"node","args":["/abs/path/dist/proxy.js"],"env":{"BITREFILL_API_KEY":"..."}}}}`.

**C. Close the loop (Lane 2).** After `delivered`, use `redemption_info.link` or `code` in the user's own signed-in session (Playwright MCP or computer use) so nothing is copied by hand; or send the eSIM install link.

**D. Shop from chat with a guarantee.** Guest MCP (OAuth client credentials) or CLI: search → details → `buy-products` with crypto → payment link → poll with `invoice_access_token`. The Bitrefill Assistant already does chat ordering; it has no budget, approval or receipt layer.

**E. Lane 5, private by default (with Zcash).** Bitrefill doesn't take ZEC and has no testnet; the Privacy track is testnet only. For the hack: a **shielded testnet payment triggers and authorises** the purchase, which is paid from event credits within caps. Claiming that shielded ZEC pays for the gift card would be a faked step (it caps both "Works" and "Followed the requirements"). Zcash side: Privacy file recipe F (zkool_graphql watch-only account or CipherPay webhook, ZIP 321 memo carrying the order code, act once the payment is mined, once per txid). Bitrefill side: recipe A with `payment_method: "balance"`, `auto_pay: true`; `GET /products/{id}` gives `data.packages[]` with `value` and USD price for the cap. Real-money route (not the demo; no testnet): shielded ZEC → deshield to a `t1` address → NEAR Intents 1Click (`https://1click.chaindefuser.com/v0`, asset `nep141:zec.omft.near` → `nep141:base-0x833589fcd6edb6e08f4c7c32d4f71b54bda02913.omft.near`; minimum 132,000 zats; ~8 minutes; `refundTo` must be a mainnet `t1`, `recipient` a Base account you control) → USDC lands in that Base wallet → `POST /v2/invoices` with `payment_method:"usdc_base"`, created only after the USDC arrives → pay the invoice address from the wallet (needs ETH on Base for gas) → poll to `delivered`. Request fields, statuses and refund rules: Privacy file recipe G. Deshielding, the Base transfers and the Bitrefill payment are all public; only the shielded source is private.

## Lanes (optional brainstorming help)

| Lane | What's new | Example ideas | Question to test your idea |
| --- | --- | --- | --- |
| **1. Rails and guardrails** | The guarantee | Spend firewall · onchain allowance on x402 · commerce agent gym · signed agent receipts | Does it work with an agent you didn't write? |
| **2. Close the loop** | The ending | Auto-redeemer in the user's browser · gift on claim · eSIM install link · gift card vault | How many human steps are left between purchase and use? |
| **3. No prompt required** | The trigger | Back-in-stock auto-buyer · contributor payouts on merged PR · monsoon mode top-ups · subscription keeper | What stops it from firing twice? |
| **4. Home-cooked commerce** | The user | Family line keeper · pocket money payday · recharge rewards · shagun pool | Could your parents run it from your README? |
| **5. Private by default** (with Zcash) | The guarantee: no public trail from wallet to merchant | Shielded payment → recharge · private mutual aid → grocery credit · anonymous thank-you gifts | What's visible at each hop? |

Building blocks: official MCP SDKs (proxies) · Base spend permissions, ERC-7715 or session keys (allowances) · EIP-712 and ERC-8004 (receipts) · `webhook_url` on REST v2 invoices (delivery events) · Playwright MCP or a computer-use agent (redeeming) · GitHub, calendar and onchain webhooks, weather alert feeds (triggers).

## India catalog (prices change; confirm with get-product-details)

- Top-ups: Jio, Airtel, Vi, BSNL prepaid; DTH (Tata Play, Airtel DTH, Dish TV). Airtel talktime: ₹10 = $0.11, ₹120 = $1.31, ₹500 = $5.49. Talktime adds balance, not validity; Jio Bundles renews plans (data from ~₹12, plans from ~₹200).
- Gift cards (190): Swiggy Money, Zomato, Blinkit, BigBasket, JioMart, Flipkart, PhonePe, Uber, MakeMyTrip, BookMyShow, Apollo Pharmacy, Hotstar, HP and Shell fuel.
- eSIMs: Bitrefill eSIM India from $3.88 (1GB, 7 days) on Airtel, Jio and Vi; 190+ other destinations.

## Rules

- Use at least one Bitrefill surface (MCP, CLI, Agent Skills, x402, REST API). Show an agent-initiated purchase working in the demo, not mocked.
- Hacking runs Wed 4 Nov 11:00 to Thu 5 Nov 00:00; all code made in that window (new repo, commit history checked). Solo or a team of up to 4 including the point person. One submission per project: pick Agentic Commerce, or Both to enter and win in both tracks (then fill in both tracks' fields).
- Submit on [Stadium](https://stadium.joinwebzero.com/programs/free-society-hack-2026) with the point person's Luma email. Save a draft early, give teammates edit access from the team list (their Luma email must be checked in), submit the event feedback, then click **Finalize and submit** by Wed 4 Nov 20:00 to be in the first judging round. Drafts are not judged. After finalizing you can keep editing until 00:00. Code after 00:00 isn't scored.
- Codes are cash: never log, print, commit or post them; mask them in the demo. Small money only: dedicated low-balance account or wallet; never put a seed phrase, private key or API key in code or prompts.
- Redeem into your own accounts; top up team phones only. No CAPTCHA solving, credential collection or bulk accounts. Disqualified: promo or cashback farming, laundering, reselling codes at scale, getting around KYC or sanctions.

## Submission checklist

Judges score from the repo and video only. Every item is required.

- [ ] Public repo (new on the day) with a README: what it does, which lane (or own idea), how to run it in under 15 minutes.
- [ ] A 2–3 minute demo video (judges watch only the first 3) showing the real loop: trigger → agent buys → delivered → value lands. Mask codes on screen.
- [ ] One paragraph: which Bitrefill touchpoints (MCP, CLI, Skills, x402, REST), what was built versus reused.
- [ ] The invoice ID of at least one real purchase the project made.
- [ ] Guardrails: the most the agent can spend in this setup (per purchase, per day), and who approves above that.
- [ ] FEEDBACK.md: what broke, confused or slowed the builder down. The builder writes the final version (the $100 prize favours the human's own words).
- [ ] Entering the Zcash track too: which parts are for which track, plus everything the [Privacy track](https://stadium.joinwebzero.com/programs/free-society-hack-2026/privacy/llms.txt) requires (testnet txid, privacy and trust note).

Full README template (copy it into the repo as README.md): https://stadium.joinwebzero.com/programs/free-society-hack-2026/agentic-commerce/README-template.md

README skeleton:

```
# <Name>: <one line: who it's for, what the agent does>
## Lane: <1–5 or own idea> · The loop: <trigger> → <guarantee> → Bitrefill → <ending>
## Demo: <video link> · Real purchase invoice ID: <id>
## Run it (under 15 minutes)
## Bitrefill touchpoints (built vs reused)
## Guardrails: max <amount> per purchase, <amount> per day; approval above that by <who/how>
## Feedback: see FEEDBACK.md
```

## Judging (1–5 per criterion, three criteria, max 15)

- **Use of the Bitrefill tech stack:** the right surface for the job and the full core loop: poll or webhook until **delivered**, not just paid; handles expired quotes, 429s, failed orders and out-of-stock. Several surfaces combined sensibly (REST worker + MCP interface, say) score higher than one call wrapped in a script.
- **Followed the requirements:** every checklist item present and clear, and the agent itself starts and completes a real purchase on camera. A mocked or hand-done purchase, or a missing invoice ID, caps this at 1.
- **How innovative:** an idea that only lives in fulfillment (search, buy, pay) is what Bitrefill already has, and a plain chat bot is the Bitrefill Assistant. New triggers, guarantees, endings or users score higher.

Tie-break: higher innovation score. Prizes: $1,000 · $800 · $600 in Bitrefill gift cards, plus $100 for the best FEEDBACK.md.

## For the agent

- Guardrails (caps, approvals, dedupe) go in before `buy-products` or `POST /invoices` is wired to anything automatic.
- Develop on a zero-balance account with a crypto payment method; the demo purchase goes through the guarded code path, never by hand.
- Record the invoice ID in README.md when the first purchase is delivered.
- Keep FEEDBACK_NOTES.md from the first error.
- Remind the builder to click Finalize and submit on Stadium by 20:00.

## Docs and help

- [Bitrefill docs index](https://docs.bitrefill.com/llms.txt) · [eCommerce MCP](https://docs.bitrefill.com/docs/ecommerce-mcp) · [MCP partner integration guide](https://docs.bitrefill.com/docs/mcp-partner-integration-guide) · [Webhooks](https://docs.bitrefill.com/docs/webhooks) · [Core concepts and statuses](https://docs.bitrefill.com/docs/core-concepts)
- [bitrefill/agents](https://github.com/bitrefill/agents) (skill, with per-client MCP setup in `skills/bitrefill/references/touchpoints/mcp.md`) · [bitrefill/cli](https://github.com/bitrefill/cli)
- Bitrefill team on site (Max N, Ankush Mehta, Aamir Shaikh): event credits, account questions. Mentors chat https://t.me/+QHbTGB6jFhllMDk6
- [Privacy track (Zcash)](https://stadium.joinwebzero.com/programs/free-society-hack-2026/privacy/llms.txt) · [Program page](https://stadium.joinwebzero.com/programs/free-society-hack-2026) · [Event index](https://stadium.joinwebzero.com/programs/free-society-hack-2026/llms.txt) · [Builder Pack](https://app.notion.com/p/3ff3e52aeb15807eace6f16f84a74c14)