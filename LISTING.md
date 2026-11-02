# Directory listing playbook — SOLVENT Localization MCP

Status of this pilot: **built and tested locally, not yet submitted anywhere.**
Everything below is ready to execute; the steps marked 🧑 need a human/account
action (they are the only blockers), everything else is free and mechanical.

## 0. Prerequisites (all listings)

| Prereq | State | Who |
|---|---|---|
| Public GitHub repo for this code (README, smithery.yaml, server.json, Dockerfile) | ❌ not created yet | 🧑 Approve + create/push under `leschk48-ux` (repo name in `server.json` assumes `leschk48-ux/solvent-localization-mcp`) |
| Public HTTPS host for the HTTP transport (`/mcp` + `/.well-known/x402` reachable) | ❌ not deployed | 🧑 Infra choice: public host TBD (not the China server — no public services may be hosted there), e.g. a tunnel/PaaS. Needed for Smithery **remote** listing and for CDP Bazaar; **not** needed for stdio listings |
| Translation backend reachable from the host (`ASK_PY`) | ✅ works on this VM | If hosting elsewhere, the ask.py pool must be deployed alongside, or localize/review calls fail (glossary still works) |
| x402 end-to-end paid call test (client wallet signs a real 0.10 USDC Solana tx; server verifies + settles via PayAI) | ⚠️ implemented, verified up to facilitator `/verify` rejection of invalid payloads; a successful settle is untested because it spends real mainnet USDC | 🧑 Any funded Solana wallet (e.g. the agent wallet itself as payer in a self-test) + explicit go-ahead to spend 0.10 USDC |

---

## 1. Smithery (smithery.ai)

Two listing shapes; stdio is the fast one.

**Stdio listing (free, no hosting needed)**
1. 🧑 Sign in at smithery.ai with the GitHub account that owns the repo.
2. New server → "GitHub repository" → select the repo. Smithery reads
   `smithery.yaml` (present) for the start command and config schema; the
   Dockerfile (present) is used to build the stdio image.
3. Fill the listing form: name `solvent-localization`, description and tool
   list from README.md (Smithery also introspects `tools/list` from the
   built server).
4. Publish. Free; review is automated + light manual QA.

**Remote (URL) listing (free, needs the HTTPS host from §0)**
1. Deploy the HTTP transport at a public URL, set `PUBLIC_BASE_URL`.
2. Smithery → New server → "Remote / URL" → enter `https://<host>/mcp`.
3. Smithery probes the endpoint (initialize + tools/list must answer).
   Our stateless HTTP transport answers both without a session.
4. Publish. Free.

## 2. mcpservers.org

1. 🧑 Be signed in to GitHub (submission is a GitHub flow).
2. Either submit via the site's "Submit" form (it opens a PR against the
   mcpservers.org list repo), or fork `punkpeye/awesome-mcp-servers` and add
   one line under the appropriate category (e.g. "Knowledge & Localization"):
   `- [SOLVENT Localization](https://github.com/leschk48-ux/solvent-localization-mcp) - EN<->ZH Web3 localization MCP: glossary-enforced translation, 238-term glossary lookup, draft QA. x402 USDC pricing on Solana.`
3. Open the PR. Free; merge depends on maintainer review (days–weeks).
   `server.json` in the repo root also makes the server eligible for the
   official MCP registry (registry.modelcontextprotocol.io) once the repo is
   public — publishing there is a separate `mcp-publisher` CLI run with
   GitHub auth (🧑 credentials), free.

## 3. CDP Bazaar (x402 discovery, bazaar / x402scan ecosystem)

There are two routes in; they are not the same database, so do both when live.

**Route A — via PayAI facilitator traffic (free, automatic)**
- PayAI states that merchants settling through its facilitator are listed in
  its discovery index (`GET https://facilitator.payai.network/discovery/resources`)
  and the x402 Bazaar. No signup: listing follows real settled traffic.
- Therefore Route A unblocks itself the first time a paid call settles
  (see the §0 paid-call test). Until then the resource is invisible there.
- Also expose `GET /.well-known/x402` (implemented) — third-party indexes
  (x402scan, agentic.market) crawl this manifest format; submission to
  x402scan is a free web form (🧑 none beyond filling it) once hosted.

**Route B — Coinbase CDP Bazaar (official)**
1. 🧑 Create a Coinbase Developer Platform (CDP) account and project
   (cdp.coinbase.com) — account step, may involve identity details; this is
   a human-only step.
2. Bazaar discovery for CDP is driven by settling through the **CDP
   facilitator** with `discovery: true` extensions on the payment response,
   or by registering resources in the CDP dashboard if offered at the time.
   Our server currently settles via PayAI; adding CDP as a second
   facilitator is a config-level change (FACILITATOR_URL is env-driven) but
   CDP facilitator calls require CDP API keys (🧑, from step 1) and the
   Bazaar extension fields in the 402 response — a small follow-up build,
   deliberately not in this pilot.
3. Free to list; CDP facilitator charges no fee on Solana settlement per
   current CDP docs (re-verify at execution time).

**Decision needed from the user:** Route A only (zero accounts, ships with
the first real payment) vs. also Route B (needs a CDP account in the user's
name + a small follow-up build).

---

## 4. Flip-on checklist (when the user approves going live)

1. Create/push the public repo (🧑 approval) → run Smithery stdio listing.
2. Deploy HTTP transport on a public HTTPS host; set `PUBLIC_BASE_URL`,
   keep `PAYMENTS_ENABLED=0` for a free-beta window.
3. Submit to mcpservers.org (PR) and x402scan (form).
4. Run one real 0.10 USDC paid self-test call; confirm settle receipt +
   PayAI discovery listing appears.
5. Set `PAYMENTS_ENABLED=1`; announce (this also triggers Bazaar Route A).
6. Optional: CDP account + Route B follow-up build.
