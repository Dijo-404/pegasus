# Separate Zcash testnet merchant

This path sells access to VeilAgent's own protected demo resource. It does not settle a Bitrefill invoice. TAZ is worthless public-testnet currency. The merchant releases access only after its own receiving-wallet watcher verifies a mined Sapling or Ironwood note, the order memo, the requested amount, and the configured confirmation threshold.

## Wallet setup

The release inspected on 4 November 2026 was [zkool-v6.36.0](https://github.com/hhanh00/zkool2/releases/tag/zkool-v6.36.0). It includes a Linux x86_64 `zkool_graphql` binary; other platforms may need a source build. Review the release before downloading. No executable is vendored in this repository.

```sh
mkdir -p .local/bin .local/zcash
chmod 700 .local .local/bin .local/zcash
curl -fL https://github.com/hhanh00/zkool2/releases/download/zkool-v6.36.0/zkool_graphql -o .local/bin/zkool_graphql
chmod 700 .local/bin/zkool_graphql
.local/bin/zkool_graphql --help
```

Start two independent processes in separate terminals. The first holds disposable testnet signing accounts. The second receives only the merchant's viewing key. Always bind both to loopback; `--allow-unauthenticated` grants full access to any process that can reach the service. The application should use port 8000 only.

```sh
umask 077
.local/bin/zkool_graphql --db-path .local/zcash/signing.db --port 8001 --bind-address 127.0.0.1 --lwd-url https://testnet.zec.rocks:443 --coin 1 --allow-unauthenticated --allow-unencrypted-database
```

```sh
umask 077
.local/bin/zkool_graphql --db-path .local/zcash/watch.db --port 8000 --bind-address 127.0.0.1 --lwd-url https://testnet.zec.rocks:443 --coin 1 --allow-unauthenticated --allow-unencrypted-database
```

Use fresh databases: `--coin 1` cannot change the network of an existing database. Initial startup may download Sapling parameters. The state and databases remain under ignored `.local/` with restrictive permissions. These commands deliberately use disposable testnet wallets; they are not a production custody configuration.

## One actual shielded payment

Run from the repository root after `uv sync --dev`. Setup creates separate payer and merchant signing accounts, imports only the merchant UFVK into the independent watcher with a birth height ten blocks below setup, and prints account IDs and public addresses. It never requests, prints or persists a seed. The UFVK passes between the two local wallet processes in memory and resides in the watch-only wallet database.

```sh
PYTHONPATH=. uv run python scripts/zcash_testnet.py setup
PYTHONPATH=. uv run python scripts/zcash_testnet.py faucet
PYTHONPATH=. uv run python scripts/zcash_testnet.py faucet-status
```

`faucet` reserves its attempt before calling the [Fauzec API](https://fauzec.com/.well-known/openapi.json). It never automatically repeats a request after an ambiguous timeout. Poll `faucet-status` until accepted and confirmed; a refusal needs help from a mentor. Then send and detect:

```sh
PYTHONPATH=. uv run python scripts/zcash_testnet.py send --amount-zats 100000 --memo VEILAGENT-TESTNET-FIRST-PAYMENT-20261104
PYTHONPATH=. uv run python scripts/zcash_testnet.py watch --timeout 180
```

The script caps its one send at 100,000 zats (0.001 TAZ), reserves the attempt before broadcasting, and uses Sapling/Ironwood funds only (`srcPools: 10`, the source pool bitmask). It does not override fees; zkool computes them. A returned txid means **broadcast**, not payment completion. `watch` independently synchronizes the watch-only receiving database and verifies mined note-level evidence. If the send fails after the attempt is reserved, inspect and reconcile the wallet instead of clearing the flag blindly.

For an application order, use the memo and amount from that order instead of the example memo. A separate state file permits an explicitly approved second demo, but does not replace the application's cumulative spend policy. The wallet script is a testnet development tool, outside the commerce authorization gateway.

## Watcher contract

`ZcashClient(url, account_id, confirmations)` supports `address()`, `check()` and `find_payment(memo, amount_zats)`.

- Endpoint must be HTTP on a loopback IP or `localhost`, with exact `/graphql` path. Proxies and redirects are disabled for wallet traffic.
- Account address must start `utest1`; the wallet must expose a Sapling or Ironwood receiver. Mainnet, regtest and Orchard-only configurations fail closed.
- Verification synchronizes the receiving account, obtains current height and transactions, and caps confirmations at the synchronized height.
- Only external notes (`scope: 0`) in Sapling (`pool: 1`) or Ironwood (`pool: 3`) whose memo exactly matches the order contribute to the payment. Change and account net balance do not count.
- Decimal ZEC values become integer zats without float arithmetic. Underpayment does not fulfill. Overpayment is accepted and the actual received amount is returned; refunds are not automated.
- The application must enforce one fulfillment per txid and one redemption per entitlement transactionally. The adapter itself has no persistence and never grants access.
- `payment_uri()` creates a [ZIP 321](https://zips.z.cash/zip-0321) link with the amount and a base64url, unpadded UTF-8 memo of at most 512 bytes. A URI is not proof of payment.

The trusted wallet service determines network membership and valid mined notes. Prefix checking and loopback restrictions do not independently verify consensus. The adapter does not query seed fields and has no spending method. A compromised local wallet process or operator can fabricate responses; this is an explicit trust boundary.

## Privacy and trust

Shielded payment values, recipients and memos are hidden from public chain observers; the merchant and anyone holding its viewing key can read its receiving history. `testnet.zec.rocks` sees watcher IP and synchronization timing. The local operator can associate order memos, transaction IDs and resource access. The signing wallet remains on the same development machine in this demo, so the operator controls the disposable payer too. Production separates the customer's wallet and runs the watcher with only the receiving UFVK.

No third-party hosted payment processor or language model sees wallet records in this path. The application stores order/payment evidence needed for fulfillment; it should not log full wallet responses or viewing keys. Public evidence is voluntary and reveals transaction timing and the demo recipient address, while public explorers cannot reveal the shielded amount or memo. Receipts and the disclosed wallet records provide that verification.

## Validation

`uv run pytest tests/test_zcash.py` exercises protocol fixtures for wrong memo, amount, scope, pool, unmined state, inadequate confirmations, unsafe endpoints, and decimal precision. These are offline tests. The live evidence section below is populated only after an actual payment is independently observed.

## Live evidence

On 4 November 2026 the project sent and independently detected **0.001 TAZ** in Ironwood (`pool: 3`) at mined height **4581917**, with at least one confirmation. Transaction: [`d95a809359a47156c20d63eb560dabb99bdc3462d60f23e17689f73f7ffaefe5`](https://zexplorer.app/testnet/tx/d95a809359a47156c20d63eb560dabb99bdc3462d60f23e17689f73f7ffaefe5).

The receiving service used a separate database imported from the merchant's UFVK. It verified the external note, exact memo `VEILAGENT-TESTNET-FIRST-PAYMENT-20261104`, amount and mined height using this repository's `find_payment()` implementation. [Public receipt](evidence/zcash-testnet.json) contains no signing or viewing keys. This proves the wallet adapter's real send/detect path; it does not by itself prove that an application entitlement was issued or a Bitrefill purchase delivered.


### Application order and single-use resource

A second 0.001 TAZ Ironwood payment used an actual API-generated order memo. Transaction: [`ef7f9cf6132cbf4df41a5195e6ebbd4034b09efbd53828f35a276afa17485b10`](https://zexplorer.app/testnet/tx/ef7f9cf6132cbf4df41a5195e6ebbd4034b09efbd53828f35a276afa17485b10), mined at height **4581925**.

The temporary test API process was terminated after broadcast, losing its temporary in-memory database encryption key. The pending order was recovered into the main local application database from its retained API-generated ID, memo, amount, and known merchant address. No replacement payment was sent. The running HTTP API then verified the existing payment through the independent watch-only receiver (five confirmations at verification), issued a 300-second entitlement, returned the protected resource once (HTTP 200), and rejected repeat redemption (HTTP 409, `NOT_REDEEMABLE`).

[Application receipt and recovery disclosure](evidence/private-merchant-e2e.json) records the real flow and its interruption. This demonstrates live payment verification and access enforcement after recovery; it is not evidence of an uninterrupted end-to-end run. The main local database retains the redeemed order.
