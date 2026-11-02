# x402 discovery manifest — v2 shape notes

Why this file exists: the publishing run found that PayAI's live discovery
index carries **v2-shaped** resource entries, while our `/.well-known/x402`
only emitted the v1 shape. This documents the v2 shape as observed live, and
what we now emit. The 402 challenge / verify / settle flow in `server.py` is
**unchanged** (still v1) — see the last section for what a v2 challenge would
eventually require.

Evidence: `GET https://facilitator.payai.network/discovery/resources`
re-fetched 2026-11-02 (~14:30 CST). Envelope: `{items, pagination, x402Version}`
— note the *envelope* still says `x402Version: 1` and `pagination.total` was
14,723, while **98 of the first 100 items are item-level `x402Version: 2`**
(only 2 legacy v1 items in the sample). Of 111 accepts entries in the sample,
109 use `amount` and CAIP-2 network ids; the 2 exceptions are exactly those
legacy v1 items. All 10 Solana-USDC accepts entries use
`solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp`.

## Reference entries studied field-by-field

1. **BlockRun** `https://sol.blockrun.ai/api/v1/chat/completions` — Solana
   USDC `exact` accepts entry (plus a `batch-settlement` one). Its v2 accepts
   entry puts `resource`/`description`/`mimeType` inside `extra` (indexer
   quirk, not seen in the other entries — we do **not** copy that).
2. **Laevitas** `https://apiv2.laevitas.ch/api/v1/options/:var1` — clean
   minimal shape: Solana + Base accepts, `extensions.bazaar` with
   `info.input` (GET + queryParams) and `info.output` example.
3. **Nansen** `https://api.nansen.ai/api/v1/profiler/address/related-wallets`
   — fullest `extensions.bazaar.schema` (JSON Schema draft 2020-12 for
   `input`/`output`); our schema block is modelled on this one.

## The v2 resource shape (per resource, as indexed)

Top level of each item:

| Field | Value / notes |
|---|---|
| `resource` | Absolute public URL of the paid endpoint (from `PUBLIC_BASE_URL`) |
| `type` | `"http"` (every sampled item) |
| `x402Version` | `2` |
| `description` | Human-readable, per-resource (mirrored into `metadata.description`) |
| `mimeType` | `"application/json"` for our endpoints (some indexed items have `""`) |
| `serviceName` | String or `null` in the index; we emit `"SOLVENT Localization"` |
| `tags` | Array or `null`; we emit service tags |
| `iconUrl` | `null` for us |
| `metadata` | `{mimeType, description}` — indexer-populated; we emit it for parity |
| `lastUpdated` | Indexer-populated timestamp; **not** emitted by us |
| `accepts` | Array of v2 payment requirements (below) |
| `extensions.bazaar` | `{info, schema}` discovery block (below) |

v2 payment requirements (one `accepts` entry):

| Field | v2 | v1 (legacy, for contrast) |
|---|---|---|
| `scheme` | `"exact"` | same |
| `network` | **CAIP-2**: `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp` (Solana mainnet) | `"solana"` |
| `amount` | **Atomic amount as string** (`"100000"` = 0.10 USDC) | field named `maxAmountRequired` |
| `asset` | USDC mint `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` | same |
| `payTo` | Recipient address | same |
| `maxTimeoutSeconds` | `300` | same |
| `extra` | `{feePayer}` only, for Solana exact | also carried `name`/`version`; v1 additionally kept `resource`, `description`, `mimeType` at the requirements level — v2 moves those to the resource level and drops them here |

`extensions.bazaar`:

- `info.input`: `{type: "http", method: "POST", bodyType: "json", body: <example request JSON>, bodyFields: {<field>: {type, description, example}}}` (GET-style resources instead carry `queryParams`/`pathParams`).
- `info.output`: `{type: "json", example: <example response JSON>}`.
- `schema`: JSON Schema (draft 2020-12) with `required: ["input"]`;
  `properties.input` requires `type`/`method`/`bodyType`/`body` and describes
  the body's fields; `properties.output` requires `type` and describes
  `example`. 92/100 sampled items have `info.{input,output}`; `schema` is
  present on the fuller listings (Nansen-style).

## Dual-version support

PayAI's `GET /supported` (re-checked 2026-11-02) advertises **both**
`{x402Version: 1, scheme: "exact", network: "solana"}` and
`{x402Version: 2, scheme: "exact", network: "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"}`,
with the **same fee payer** (`CjNFTj…eKww`) — so a manifest can serve both
shapes and the facilitator honours both. Our manifest therefore emits:

- `resources`: v2-shaped entries (primary, what the index ingests), and
- `resourcesV1`: the exact legacy v1 entries we shipped before (same URLs,
  `accepts[0].network = "solana"`, `maxAmountRequired`), for v1-only clients.

Envelope `x402Version` is `2` with `supportedVersions: [1, 2]`.
`resource` URLs are built from `PUBLIC_BASE_URL` whenever it is set — no
loopback literals appear in the emitted manifest (the snapshot check in
TEST-RESULTS.md asserts this). Public host is **TBD (not the China server)**;
tests use the neutral placeholder `https://mcp.solvent.example`.

## Follow-up (NOT done here): what a v2 challenge flow would require

The manifest upgrade does **not** change the live payment flow: our 402
responses still carry `{x402Version: 1, accepts: [<v1 requirements>]}` and
verify/settle still POST v1 bodies — consistent with the facilitator's v1
kind above. Moving the challenge itself to v2 would mean:

1. Challenge body `x402Version: 2` with accepts entries in the v2 shape
   (CAIP-2 `network`, `amount`, no requirements-level
   `resource`/`description`/`mimeType`).
2. Payment header rename: v2 clients send **`PAYMENT-SIGNATURE`** instead of
   `X-PAYMENT` (our gate already *reads* both header names, so this part is
   half-done), and the receipt header becomes `PAYMENT-RESPONSE` instead of
   `X-PAYMENT-RESPONSE`.
3. `/verify` and `/settle` bodies sent with `x402Version: 2` and the v2
   payment-requirements object echoed back verbatim; the SVM payload
   internals (client-signed `transferChecked` transaction, facilitator fee
   payer) are unchanged since the fee payer is identical across versions.
4. Replay-protection and settle-after-serve semantics carry over unchanged.

Treat that as a separate, deliberate change once a v2-native client or the
Bazaar listing actually demands it.
