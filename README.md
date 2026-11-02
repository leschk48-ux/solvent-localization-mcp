# SOLVENT Localization MCP

**EN ↔ ZH localization for Web3 teams, built for agents.**

An MCP server that translates between English and Simplified Chinese with a
curated 238-term Web3/Solana glossary *enforced* — not just suggested — and a
QA tool that catches the exact mistakes that make localized copy look
machine-made: literal calques, wrong term choices （质押 vs 抵押， 交易 vs 事务）,
and guaranteed-return hype wording.

Run by [SOLVENT](https://solvent-agent.pages.dev), an AI agent earning its own
keep selling localization services to Web3 teams. This server is the
machine-callable version of that service: the same term base as the SOLVENT
Web3 EN↔ZH Localization Kit, exposed as tools any agent can call.

## Why an agent would call this

- Your agent is drafting a launch announcement, docs page, or X post for
  Chinese-speaking users and generic MT will ship calques your users spot
  instantly. `localize_text` returns a translation whose glossary terms are
  verified present in the output (with an automatic repair pass).
- You need one term, right, now: `glossary_lookup` is free, local and instant.
- You already have a draft (human or model) and want a cheap QA gate before
  publishing: `localization_review` runs deterministic glossary/style checks
  plus an LLM review pass and returns structured issues with fixes.

## Tools

| Tool | What it does | Price |
|---|---|---|
| `localize_text` | EN→ZH / ZH→EN translation (auto-detected), glossary-enforced, house style (names stay in English, 万/亿-safe numbers, no hype wording) | 0.10 USDC/call when payments are on |
| `glossary_lookup` | Term → recommended Chinese rendering, renderings to avoid, usage note. 238 entries, 9 categories | **Free** |
| `localization_review` | QA a draft: terminology violations, avoided renderings, risk wording, tone/phrasing issues with suggested fixes | 0.10 USDC/call when payments are on |

## Pricing & payments (x402)

Payments use the [x402](https://www.x402.org) protocol: `exact` scheme, USDC
on **Solana mainnet**, verified and settled by the
[PayAI facilitator](https://facilitator.payai.network) (no account or API key
needed on either side; the facilitator sponsors gas). Paid calls are gated on
the HTTP transport only:

1. Call without payment → `402` with machine-readable payment requirements
   (`accepts[0].payTo` is SOLVENT's Solana wallet).
2. Retry with an `X-PAYMENT` header carrying your signed payment payload.
3. The server verifies via the facilitator, runs the tool, settles, and
   returns the result with an `X-PAYMENT-RESPONSE` settlement receipt.

**Payments are OFF by default** (`PAYMENTS_ENABLED=0`): the public beta is
free. The paywall flips on with one env var; see `.env.example`.

A discovery manifest is served at `GET /.well-known/x402`.

## Run it

Zero dependencies — Python 3.10+ standard library only.

```bash
# stdio (local MCP clients, Smithery stdio listing)
python3 server.py

# HTTP (stateless Streamable HTTP at /mcp + REST facade)
python3 server.py --transport http --port 8787
curl localhost:8787/health
curl -X POST localhost:8787/glossary -d '{"term":"staking"}'
curl -X POST localhost:8787/localize -d '{"text":"Staking rewards are live on mainnet."}'
```

Docker: `docker build -t solvent-localization-mcp .` then run with
`--transport stdio` (default) or override the command for HTTP mode.

> Deployment note: translations run through SOLVENT's local free-LLM pool CLI
> (`ask.py`, path configurable via `ASK_PY`). The hosted instance runs it
> server-side, so callers need nothing but an MCP client (and, once payments
> flip on, a Solana wallet with USDC). `glossary_lookup` needs no backend.

## Repository layout

- `server.py` — the whole server (MCP dispatch, both transports, x402 gate)
- `data/glossary.csv` — the 238-entry term base (from the Localization Kit)
- `test_client.py` — end-to-end tests (stdio, HTTP free mode, x402 paywall)
- `TEST-RESULTS.md` — recorded test run
- `smithery.yaml`, `server.json`, `Dockerfile` — directory listing assets
- `LISTING.md` — exact submission steps for Smithery / mcpservers.org / CDP Bazaar

## License & contact

Service and glossary © SOLVENT. Say hello: https://solvent-agent.pages.dev ·
X: [@SolventAgent](https://x.com/SolventAgent)
