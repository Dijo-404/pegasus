# Pitch and demo video

The **approved v4 pitch is exported and verified**: **120 seconds (2:00), eight scenes, 3,600 frames**, at 1920 × 1080 (16:9)/30 fps, using HyperFrames 0.9.12. It leads with delegated-spending authority and brings the saved verified x402 result forward to **12 seconds**. [Actual narration used](demo-narration.md) · [Live API-payment receipt](evidence/x402-testnet-payment.json) · [v4 export receipt](evidence/demo-video-export-v4.json).

The user approved the pitch preview before final export. The current repository MP4 is v4. The 144.466667-second v3 preview was superseded without export; the older v2 export receipt remains unchanged as historical evidence.

[![Watch the verified v4 pitch](assets/demo-video-poster.jpg)](assets/pegasus-pitch-demo.mp4)

[**Watch or download the verified pitch**](assets/pegasus-pitch-demo.mp4) · [Poster](assets/demo-video-poster.jpg) · **16.7 MiB** · [Export receipt](evidence/demo-video-export-v4.json)

## Current pitch and animation

The new story is **delegate the task → real API proof → exact permission → one shared budget → shielded access → honest commerce status → trust → invitation to build**. It presents the product's value before a technical walkthrough. No target-user validation, customer adoption or demand is invented.

One blue approval boundary travels across the product frame, exact-terms explanation and budget ledger. Masked headline reveals land and hold; matched product-frame movement carries the viewer into actual evidence. The private checkout changes to its real black/gold UI, then returns to paper/blue for commerce and the closing mark. These are source-backed frame carries and line draws, rather than a curtain wipe on every cut. Explanations remain labelled and never imitate a performed approval.

| Time | Pitch scene | Main evidence or reading |
| --- | --- | --- |
| 0–12s | Delegate the task. Keep the authority. | New opening and actual workspace; the owner retains payment authority. |
| 12–35s | Already proven on testnet. | Actual saved x402 result, terms and audit, captured after settlement. |
| 35–48s | Your approval binds the action. | Labelled approval-model explanation; changed terms require fresh approval. |
| 48–60s | One budget. One attempt. | Labelled guard-policy explanation; reserve the approved maximum before signing. |
| 60–83s | Shielded payment. Real access. | Recorded manual Zcash checkout, mined confirmation and single-use access. |
| 83–95s | Verified catalog. Delivery comes next. | Actual Bitrefill catalog and review; purchase/delivery remain pending. |
| 95–108s | Clear authority. Explicit trust. | EVM signer vs watch-only receiver, operator and external services. |
| 108–120s | Build with agents. Keep decisions yours. | New closing, original mark, repository and testnet-demo invitation. |

## Actual narration and local review

The audio uses a **new 48-word opening/closing take**, source duration **20.114285714 seconds**, plus whole-sentence excerpts of the existing stock narration and the earlier x402 paragraph. The full rewritten pitch draft was not used. [The published script](demo-narration.md) matches the actual source map, rather than a draft that has not been synthesized.

Every voice clip has one pitch-preserved **1.10×** playback adjustment. Narration clip playback totals **96.815028 seconds** across the two-minute timeline; the remaining time contains short reading holds, handoffs and the final frame. The opening runs approximately 0.5–9.091 seconds; the closing approximately 108.5–118.195 seconds. Background music continues beneath the sequence. Encoded audio measures **−14.30 LUFS integrated, −1.92 dBTP true peak and 6.6 LU loudness range**. The user approved the preview; agents do not claim subjective listening.

Preview: <http://localhost:3004/#project/pegasus-film>. It works on the operator's machine while the preview server is running and is separate from the public application tunnel. The ignored editable project is `.local/video/pegasus-film/`. **PITCH-TIMING.json** is the authoritative v4 scene/voice source map; **PITCH-NARRATION.txt** contains the exact spoken text. `frame.md`, `STORYBOARD.md`, `BRIEF.md` and `SPEC.md` record motion, source and evidence constraints.

The approved preview and exported film now represent the same v4 pitch. The preview remains editable for future revisions. Previous approvals and measurements remain associated with their own historical exports.

## Verified output (v4)

| Property | Measured result |
| --- | --- |
| File | `docs/assets/pegasus-pitch-demo.mp4` |
| Duration / frames | 120.000000 seconds / 3,600 frames |
| Picture | 1920 × 1080, 30 fps, H.264, `yuv420p` |
| Audio | AAC, 48 kHz, stereo |
| Size | 17,476,449 bytes, approximately 16.67 MiB |
| Full audio/video decode | Passed without errors |
| Encoded audio measurement | −14.30 LUFS integrated, −1.92 dBTP true peak, 6.6 LU loudness range |
| SHA-256 | `a3bf52eddd02c0e6d86e1f2dc8b8560a83323d023ca82b29f9fa50f163325e85` |

Full audio/video decoding passed. Fifteen decoded content frames and thirty-five seam frames were visually reviewed. Audio levels were measured, without an agent listening claim. The [new v4 export receipt](evidence/demo-video-export-v4.json) records the current file's SHA-256 and media metadata. The poster is taken from the pitch at six seconds.

Historical v2 measured 120.466667 seconds, 3,614 frames and 7,744,454 bytes, with −14.21 LUFS integrated/−1.54 dBTP audio. Its [original receipt](evidence/demo-video-export.json) is retained unchanged; those numbers no longer describe the current MP4 path. Its local backup is `.local/video/revisions/v2-before-v4-export/`.

## Evidence used in the pitch

### Saved x402 HTTP payment

The early proof reviews [the actual saved API result](assets/demo-x402.png), labelled **Saved receipt · recorded after settlement**. It does not recreate browser approval or make another payment. The original run used owner approval and agent-credential execution through the loopback gateway, with the live external testnet API and public RPC. [Public receipt, result and audit](evidence/x402-testnet-payment.json).

| Field | Observed value |
| --- | --- |
| Transaction | [0x8f144b1a9880cc15eb7e0ad1364b4947973c68cf35b2a73dbb1f1ec77e81c86d](https://sepolia.basescan.org/tx/0x8f144b1a9880cc15eb7e0ad1364b4947973c68cf35b2a73dbb1f1ec77e81c86d) |
| Amount / approved ceiling | 0.001 test USDC / one USD cent |
| Network / mined block | Base Sepolia / 54451642 |
| Verification | Mined status 1, exact USDC Transfer and matching AuthorizationUsed nonce |
| Replay | HTTP 409 GRANT_REPLAY |

The gateway holds the dedicated EVM signing key. This USDC payment is transparent: payer, recipient and amount are public. The configured RPC is a trusted receipt source. It is separate from the shielded Zcash checkout and pending Bitrefill delivery.

### Recorded Zcash checkout

The genuine recorded checkout used transaction [5e0179d3ca9ea1be3835a0eadb92ade8244fb4e5f25f8c647c3e74aff0e47929](https://zexplorer.app/testnet/tx/5e0179d3ca9ea1be3835a0eadb92ade8244fb4e5f25f8c647c3e74aff0e47929): **0.001 TAZ, Ironwood, height 4582394**, verified at one confirmation. Access returned once; replay returned **HTTP 409 NOT_REDEEMABLE**. [Original recorded receipt](evidence/recorded-demo-checkout.json).

**The payer step was manual.** Noir was not installed. A disposable local payer sent using the API-created order's amount, address and memo; the same operator controls both demo wallets. A separate watch-only receiver verified the mined note and cannot spend. The original **40.102-second mining wait is condensed and labelled**. The pitch reuses that recording; it does not perform another payment or portray an independent customer.

The shielded amount and memo were checked by the authorized receiver. Public Zcash explorers show existence, height and fees, not those private fields. The operator can associate order, payment and access; the light-wallet service sees synchronization IP and timing. Earlier Zcash receipts remain historical evidence and are not renamed or reused as a newly filmed send.

### Bitrefill and trust limits

Actual authenticated catalog and review footage is shown. No Bitrefill invoice, payment or delivered product is claimed; test-product enablement and delivery verification remain pending. Testnet TAZ and the external API's USDC settle their separate flows, not Bitrefill goods.

The operator, API/facilitator, public RPC, light-wallet service and Cloudflare remain trusted parties. The gateway's EVM signing authority differs from the watch-only Zcash receiver. An external agent's model provider sees tool data sent to it; narration production sends the script to the voice provider.

No keys, seeds, viewing keys, credentials, private payment links, contact information or redemption codes may appear. Voice, music and explanatory animation are production assets, not payment evidence. The demo remains a single-operator prototype and does not establish user research, event submission or production readiness.

## Production assets

The film uses original Pegasus SVG marks, local Host Grotesk/Departure Mono fonts, actual dashboard recordings, GSAP 3.15.0 and HyperFrames 0.9.12. The matching stock voice and ambient music came through HeyGen; no voice cloning or fictional speaker is used. New narration is limited to the opening/closing; body speech is reordered from existing takes at measured sentence boundaries. FFmpeg prepares source media and audio. Historical exports and immutable payment receipts remain separate from the new export verification.
