# Test results — SOLVENT Localization MCP

Run: 2026-11-02 (Asia/Shanghai), `python3 test_client.py`, Python 3.12,
server commit state = pilot build. **17/17 checks passed.**

The translation backend (ask.py free-LLM pool) was live during the run; the
x402 checks ran against the **real PayAI facilitator** (public endpoints, no
account). No real payment was made — see the note at the bottom.

## stdio transport

| Check | Result | Evidence |
|---|---|---|
| initialize | PASS | serverInfo `{name: solvent-localization, version: 0.1.0}` |
| tools/list | PASS | `[localize_text, glossary_lookup, localization_review]` |
| glossary_lookup('staking') | PASS | → 质押； avoid: "抵押 means collateral, a different concept"; usage note returned |

## HTTP transport, PAYMENTS_ENABLED=0 (free beta)

| Check | Result | Evidence |
|---|---|---|
| GET /health | PASS | status ok, payments_enabled=false, glossary_entries=238 |
| tools/list over /mcp | PASS | 3 tools |
| glossary_lookup ZH→EN （空投） | PASS | → `airdrop`, with avoid note "空中投放 is a literal error" |
| localize_text EN→ZH | PASS | Input: "Staking rewards are live on mainnet. Connect your wallet and claim your airdrop before the epoch ends." → "质押奖励已在主网上线。请连接您的钱包并在 Epoch 结束前领取您的空投。" |
| glossary enforcement | PASS | applied = [mainnet, staking, airdrop, wallet, epoch], warnings = [] |
| localize_text ZH→EN | PASS | "质押奖励已经在主网上线，连接钱包即可领取空投。" → "Staking rewards have launched on mainnet, connect wallet to claim airdrop." |
| localization_review | PASS | Draft "请确认这笔事务，我们保证稳赚不赔。" → 4 issues incl. terminology 事务 (avoided rendering for "transaction") + risk_wording 稳赚/稳赚不赔； LLM pass returned findings, no error |
| REST /glossary | PASS | wallet → 钱包 |

## HTTP transport, PAYMENTS_ENABLED=1 (x402 paywall)

| Check | Result | Evidence |
|---|---|---|
| GET /health | PASS | payments_enabled=true, pay_to = `ApC24q9FAsRV1ByKccGjySzchzXPwFx6AZL4Tir7NPbV` |
| GET /.well-known/x402 | PASS | accepts[0]: scheme=exact, network=solana, asset=USDC mint `EPjFWdd5…TDt1v`, maxAmountRequired=`100000` (0.10 USDC), payTo=agent wallet, extra.feePayer present (live from facilitator /supported) |
| POST /localize without payment | PASS | HTTP 402, body `{x402Version: 1, error: "X-PAYMENT header is required", accepts: [...]}` |
| POST /localize with bogus X-PAYMENT | PASS | HTTP 402 — the **live PayAI /verify** rejected it: `invalid_exact_svm_payload_transaction_could_not_be_decoded` |
| MCP tools/call localize_text without payment | PASS | HTTP 402 (paywall applies to /mcp too) |
| MCP glossary_lookup under paywall | PASS | HTTP 200 — free tool stays free |

## Not tested (by design — boundary of this pilot)

- **A successful settle.** Requires a client wallet to sign a real Solana
  mainnet transaction paying 0.10 USDC (mainnet funds + a spending decision).
  Everything server-side up to that point is implemented and exercised:
  challenge issuance, requirement quoting (incl. live feePayer discovery),
  facilitator /verify, settle call + `X-PAYMENT-RESPONSE` receipt, and
  single-use replay protection. The first live paid call is step 4 of the
  flip-on checklist in LISTING.md.
- Directory submissions themselves (build-only scope).

---

## Follow-up run — x402 v2 discovery manifest (2026-11-02)

Change: `/.well-known/x402` now emits **v2-shaped** resources (the shape the
live PayAI discovery index actually carries — field-by-field evidence in
`X402-V2-NOTES.md`), with the legacy v1 entries kept under `resourcesV1`.
The 402 challenge / verify / settle flow is unchanged (still v1).
`python3 test_client.py` — **18/18 checks passed** (the old manifest check
became two: v2 shape + retained v1 shape).

| Check | Result | Evidence |
|---|---|---|
| x402 manifest v2 shape | PASS | `resources[0]`: type=http, x402Version=2, description set, extensions.bazaar present; accepts[0]: scheme=exact, network=`solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp`, asset=USDC mint, **amount=`100000`**, no `maxAmountRequired`, payTo=agent wallet, extra.feePayer live |
| x402 manifest legacy v1 kept | PASS | `resourcesV1[0].accepts[0]`: network=`solana`, maxAmountRequired=`100000`, payTo=agent wallet |
| All other suite checks (stdio, free mode, paywall, live /verify rejection) | PASS | Same as the run above; unpaid `/localize` still returns the v1 402 challenge verbatim |

Manifest snapshot check — server started with `PAYMENTS_ENABLED=1` and
`PUBLIC_BASE_URL=https://mcp.solvent.example` (neutral placeholder; the real
public host is **TBD — not the China server**), manifest saved to
`manifest-snapshot.json`. **10/10 assertions passed**: no `127.0.0.1` and no
`localhost` anywhere in the body; both v2 and v1 resource URLs sit under the
configured public base URL; envelope `x402Version=2` + `supportedVersions:
[1, 2]`; bazaar `info.input/output` and `schema` present for both paid tools,
with example request bodies.
