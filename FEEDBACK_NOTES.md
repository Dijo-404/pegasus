# Builder integration notes — 4 November 2026

These are observed engineering notes. No partner feedback or user research is invented.

- The two Stadium llms.txt links were inaccessible through the web reader; direct HTTPS curl succeeded. Both raw briefs are preserved in `docs/briefs/` and combined in `AGENTS.md`.
- There was no repository or integration configuration initially; `project.md` contained the VeilAgent proposal.
- Bitrefill's public CLI catalog read works without a configured developer key. The authenticated MCP backend still needs a key for this application.
- Bitrefill tool output may be TOON rather than JSON. The adapter explicitly decodes both and treats provider prose as data.
- The MCP dependency must stay below 2 for the ordinary httpx transport used here; the lockfile records the installed versions.
- MCP checkout does not carry the price. The gateway re-reads the denomination price before consuming a grant and checks authoritative invoice terms before offering a payment link. Missing invoice fields deliberately leave an order blocked.
- An initial FastAPI startup check caught `Field` being used for a query parameter; it was changed to `Query` before browser testing.
- Running the pytest executable initially omitted the repository from Python's module path. The test configuration now declares it explicitly.
- A prebuilt zkool_graphql release avoided a Rust build. Wallet services must stay on loopback because unauthenticated GraphQL includes sensitive account fields. This app uses a separate watch-only database.
- Two shielded testnet transfers were independently confirmed. The API-order test process was interrupted after broadcast; its temporary random encryption key was lost. The retained authoritative order fields were restored into the app's persistent-key store. The existing payment was then confirmed through HTTP, the resource was redeemed once, and replay was rejected. No payment was resent during recovery. See `docs/evidence/private-merchant-e2e.json` for the precise disclosure.
- The installed Starlette test client emits a deprecation warning about future httpx2 support. Current tests pass with the pinned httpx/MCP transport.
