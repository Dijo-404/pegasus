# Temporary HTTPS testnet deployment

The demo exposes the existing Python application through a Cloudflare Quick Tunnel. The application, independent watch-only receiver, and disposable signing wallet stay on the operator's machine. Only application HTTP traffic enters the tunnel. This is a single-operator demonstration with shared owner/agent roles, not a multi-user hosted service.

Current URL: <https://notified-accountability-requirement-taste.trycloudflare.com>. The URL depends on the running tunnel and changes when a new tunnel is created. It is not a permanent deployment.

## Observed verification

On 4 November 2026 at **18:07 IST**, a fresh public-API order received **0.001 TAZ** in Ironwood at height **4582071**. The watch-only receiver verified one mined confirmation, the API returned the protected resource once, and a repeat redemption returned HTTP 409. [Payment and checkout receipt](evidence/deployed-testnet-checkout.json). The checkout completed without restoring an order or restarting an application process.

After completion, HTTP was deliberately restarted. The existing order remained `REDEEMED`, repeat access still returned HTTP 409, and public health/dashboard/assets returned HTTP 200. The public dashboard also loaded in Playwright Chromium with no JavaScript errors; its Private resource tab worked. Unknown hosts and foreign origins were rejected. All 149 automated tests, Ruff and JavaScript syntax validation passed. [Deployment checks](evidence/deployment-smoke.json).

## Runtime layout

| Component | Address / service |
| --- | --- |
| Public HTTPS | Cloudflare Quick Tunnel; original Host is preserved |
| HTTP application | `127.0.0.1:8787`, `pegasus-demo-http.service` |
| Watch-only receiver | `127.0.0.1:8000/graphql`, existing wallet process |
| Disposable testnet signer | `127.0.0.1:8001/graphql`, existing wallet process |
| Tunnel | `pegasus-demo-tunnel.service` under the operator's user systemd |
| Private runtime files | `.local/deployment/public.env`, `state.json`, `http.log`, `tunnel.log` |
| Persistent application state | `.local/pegasus.db` and the existing `DATA_KEY` in `.env` |

The application uses exactly one worker. Repository startup reconciles interrupted commerce execution, so additional workers must not be started against the same database. Keep the database together with its encryption key; generating a replacement key makes existing encrypted records unreadable. The original database was backed up privately to `.local/backups/pre-deployment.db` before the deployment.

## Start on this Linux machine

Install dependencies with `uv sync --locked`, retain the existing private `.env`, and start the two loopback wallets using [the testnet guide](zcash-testnet.md). Set `ZCASH_ENABLED=true` only with the receiver running. Do not publish the wallet ports, seed accounts, `.env`, or wallet/database files.

The deployment uses the official [cloudflared 2026.10.7 release](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.7), installed privately as `.local/bin/cloudflared`. Its Linux amd64 SHA-256 was checked against the release's published checksum:

```text
1f99fb518b83dec2ba8d870a7cc991d82a77e6196295a3d2754ba17ab9f91872
```

From the repository root, prepare private logs and start a tunnel. Stop any earlier tunnel unit before deliberately creating a replacement.

```sh
umask 077
mkdir -p .local/deployment
touch .local/deployment/tunnel.log .local/deployment/http.log
systemd-run --user --unit=pegasus-demo-tunnel --collect \
  --working-directory="$PWD" --property=UMask=0077 \
  --property="StandardOutput=append:$PWD/.local/deployment/tunnel.log" \
  --property="StandardError=append:$PWD/.local/deployment/tunnel.log" \
  "$PWD/.local/bin/cloudflared" tunnel --no-autoupdate --protocol http2 \
  --url http://127.0.0.1:8787
tail -n 30 .local/deployment/tunnel.log
```

Copy the newly printed public hostname into `.local/deployment/public.env` as an exact host allowlist. This file contains no credentials. Example for the current tunnel:

```dotenv
HTTP_ALLOWED_HOSTS=localhost,127.0.0.1,[::1],notified-accountability-requirement-taste.trycloudflare.com
```

Gracefully stop any earlier application process on port 8787 before starting its replacement. Keep wallet processes running. Then:

```sh
systemd-run --user --unit=pegasus-demo-http --collect \
  --working-directory="$PWD" --property=UMask=0077 \
  --property=Restart=on-failure --property=RestartSec=3 \
  --property="EnvironmentFile=$PWD/.local/deployment/public.env" \
  --property="StandardOutput=append:$PWD/.local/deployment/http.log" \
  --property="StandardError=append:$PWD/.local/deployment/http.log" \
  "$PWD/.venv/bin/python" -m uvicorn pegasus.bootstrap:create_app --factory \
  --host 127.0.0.1 --port 8787 --workers 1 --proxy-headers \
  --forwarded-allow-ips 127.0.0.1 --no-access-log --limit-concurrency 32
```

`HTTP_ALLOWED_HOSTS` accepts explicit lowercase hostnames/IPs; wildcard, scheme and port entries fail startup validation. Uvicorn trusts forwarded headers only from the loopback tunnel connector. HTTPS origin checking requires both the preserved public Host and forwarded HTTPS scheme. Access logging is disabled, and tunnel debug logging is not enabled.

Open the public URL and use **Sign in** to paste the existing private `OWNER_TOKEN` from `.env` locally. Credentials remain required for protected APIs. Keep owner and agent credentials separate and share them only with the operator and trusted agent respectively. Public visitors can load the dashboard without receiving either credential.

## Verify one real checkout

This command explicitly sends **0.001 TAZ** from the existing disposable testnet payer. It is not part of the automated test suite. It creates an API order, checks unpaid access is denied, reserves and sends once, waits for the application's own receiver to verify a mined note, redeems once, and checks replay is rejected.

```sh
uv run python scripts/verify_testnet_deployment.py \
  --base-url https://notified-accountability-requirement-taste.trycloudflare.com
```

The script reads local credentials without printing or persisting them. Its private state is `.local/zcash/deployment-verification.json`; its new public receipt is `docs/evidence/deployed-testnet-checkout.json`. Resume with the same arguments after an interrupted wait. A reserved send is never automatically resent. An ambiguous order creation or redemption requires inspection; do not claim success from an absent response. Existing receipts are never overwritten. The signing wallet computes its own transaction fee.

## Operate and stop

```sh
systemctl --user is-active pegasus-demo-http.service pegasus-demo-tunnel.service
systemctl --user restart pegasus-demo-http.service
ss -ltnp
```

Restarting HTTP preserves the existing encrypted database and key. Restarting the tunnel can change its hostname: update `public.env`, restart HTTP, and record the replacement URL. The user services survive the invoking shell but are transient; they do not recreate this deployment after a reboot. The machine and wallets must stay awake and connected for live verification.

To stop public access and the HTTP application:

```sh
systemctl --user stop pegasus-demo-tunnel.service pegasus-demo-http.service
```

This leaves the independent local wallet processes and all persistent data intact.

## Privacy and limits

Cloudflare terminates public HTTPS and can see visitor IPs, bearer-authenticated requests, order memos and API responses. The operator and receiving viewing key can associate order memos, txids and resource access. `testnet.zec.rocks` sees wallet synchronization IP and timing. The app does not send wallet records to an LLM or hosted payment processor. The disposable payer and watch-only receiver remain separate local wallet databases; the same development operator controls both.

The public receipt deliberately discloses one demo's amount, memo, address and txid. The explorer alone cannot verify shielded amount or memo. TAZ does not settle Bitrefill invoices, and this deployment does not perform a Bitrefill purchase.

[Cloudflare's Quick Tunnel documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) describes temporary URLs, changing hostnames and the lack of an uptime guarantee. Trusted proxy behavior is documented in [Uvicorn settings](https://uvicorn.dev/settings/). A persistent deployment needs a stable host, durable storage, user authentication/ownership and a separately operated watch-only wallet.
