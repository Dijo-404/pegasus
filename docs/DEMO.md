# VeilAgent demo guide

The dashboard uses real provider integrations. Without credentials or a receiving wallet it shows the missing connection and disables the dependent action. It never substitutes a mock catalog, transaction or delivery.

## Start locally

Follow the root README to install dependencies and generate the private local configuration. Start the API on loopback and open its root URL. Use **Connect session** to enter the generated owner token. The separate agent token is optional for interactive use and can prepare and execute intents; it cannot approve one. When both tokens are entered, the interactive dashboard uses the owner view so exact recipient details remain visible for review. Switching from an agent view requires a fresh owner review before approval. Tokens remain in this tab's session storage. Execution grants remain in page memory.

Never paste a Bitrefill API key, wallet seed or spending key into the dashboard. The owner token is a local application credential, not a provider key. Clearing the session removes local tokens and the in-memory grant.

## Commerce: show the boundary in under two minutes

1. Use the dedicated zero-balance Bitrefill account with the manual crypto payment method configured in the backend. Confirm your own receipt email, recipient and allowed product are configured in the local allowlists.
2. Enter a buying objective, product search and allowed country. **Search live catalog** only reads Bitrefill. Choose an actual returned product and denomination.
3. Enter the exact recipient and receipt email, choose a supported manual payment method, and set your maximum total. The configured per-purchase and per-day caps appear above the workspace.
4. **Prepare exact intent** fetches the current quote and runs server-side policy. A denied policy returns a reason and creates no purchase.
5. Review the product ID, denomination, quantity, country, recipient, email, method, quote and cap. The owner clicks **Approve these exact terms**. The resulting grant is bound to the canonical intent fingerprint and expires quickly.
6. Click **Create the approved invoice** once. The gateway rechecks terms, atomically consumes the grant, reserves budget, and calls the provider. The history and execution trail show the authoritative outcome.
7. Show **Unpaid** honestly. The provider payment page appears only when the backend verified the invoice terms. Completing checkout is a separate manual step in this MVP.
8. **Check provider status** reconciles the invoice. Delivery appears only when every order is delivered. An invoice finalized as `complete` alone does not prove delivery. Gift-card redemption secrets are never rendered.

For an adversarial demonstration, use the automated attack tests or call the API with the agent token to attempt approval, alter a digest, exceed a cap, or replay a consumed grant. Do not alter a live order simply to stage a rejection. Network ambiguity leaves an intent `UNCERTAIN`; do not automatically retry checkout.

## Privacy: verify one actual shielded testnet payment

This is an independent Zcash-native merchant. Testnet TAZ does not settle any Bitrefill order. Follow [ZCASH.md](ZCASH.md) to configure a watch-only testnet receiving account and a distinct payer wallet.

1. Open **Private resource** and create a testnet payment request. The backend returns the actual `utest1` receiving address, amount and unique encrypted order memo.
2. Use the ZIP 321 wallet link or **Connect & pay with Noir**. Noir must be the separate testnet extension. The wallet computes its own fee and asks the payer to approve a shielded send.
3. After broadcast the page still shows **Awaiting payment**. Use **Verify payment with receiving wallet** after a block is mined. The receiver verifies the memo, received-note amount, shielded pool and confirmation threshold; a browser-provided transaction ID cannot authorize access.
4. After **Confirmed**, redeem the single-use entitlement within the displayed five-minute deadline. A second redemption is rejected. Record the independently verified txid and explorer URL in the README only after this real flow works.

Keep demo and development wallets separate. Hide tokens and personal recipient details while recording. The on-chain amount and memo are shielded; the merchant's viewing wallet sees them, and the light-wallet server sees connection metadata. See the root privacy and trust note for the complete trust boundary.

## Submission evidence

Record only evidence you actually obtained: delivered Bitrefill invoice ID, mined shielded testnet txid, explorer link, demo video and public deployment/repository links. No fixture output qualifies as live evidence. The human builder writes the final `FEEDBACK.md` from the accumulated notes.

The official briefs request **Finalize and submit** on Stadium by **4 November 2026, 20:00 IST** for the first judging round; draft submissions are not judged. Editing can continue until **5 November 2026, 00:00 IST**.
