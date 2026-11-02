#!/usr/bin/env python3
"""
SOLVENT Localization MCP Server
================================
EN<->ZH localization for Web3 teams, exposed as MCP tools.

Tools:
  - localize_text      EN->ZH / ZH->EN translation, glossary-enforced (paid when payments on)
  - glossary_lookup    term -> recommended translation + usage note (always free)
  - localization_review  QA pass over a draft translation (paid when payments on)

Transports:
  - stdio (default)    for local MCP clients / Smithery stdio listing
  - HTTP               stateless Streamable-HTTP at POST /mcp, plus a plain REST
                       facade (POST /localize, /glossary, /review) and a
                       GET /.well-known/x402 discovery manifest (v2-shaped
                       resources for the PayAI/Bazaar index, plus the legacy
                       v1 entries under resourcesV1 — see X402-V2-NOTES.md).

Translation backend: the local free-LLM pool CLI (ask.py, One API first) so the
marginal cost of a call is ~zero. The 238-entry SOLVENT Web3 glossary is loaded
locally and enforced both in the prompt and by a post-translation check.

Payments: x402 (v1, "exact" scheme, USDC on Solana mainnet) via the PayAI
facilitator (https://facilitator.payai.network, no API key / account needed).
Disabled by default (PAYMENTS_ENABLED=0 -> free beta). See x402 section below.

Zero third-party dependencies: Python 3.10+ standard library only.
"""

import base64
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------
# Configuration (environment)
# --------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GLOSSARY_PATH = os.environ.get(
    "GLOSSARY_PATH", os.path.join(BASE_DIR, "data", "glossary.csv")
)
ASK_PY = os.environ.get("ASK_PY", os.path.expanduser("~/workspace/llm-pool/ask.py"))
ASK_TIMEOUT = int(os.environ.get("ASK_TIMEOUT", "120"))

PAYMENTS_ENABLED = os.environ.get("PAYMENTS_ENABLED", "0").lower() in ("1", "true", "yes")
PAY_TO_ADDRESS = os.environ.get(
    "PAY_TO_ADDRESS", "ApC24q9FAsRV1ByKccGjySzchzXPwFx6AZL4Tir7NPbV"
)
X402_NETWORK = os.environ.get("X402_NETWORK", "solana")  # x402 v1 network id
# x402 v2 network id (CAIP-2) for the discovery manifest's v2 entries.
X402_NETWORK_V2 = os.environ.get(
    "X402_NETWORK_V2", "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
)
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC on Solana mainnet
FACILITATOR_URL = os.environ.get("FACILITATOR_URL", "https://facilitator.payai.network")
# Fallback fee payer (PayAI's Solana sponsor wallet); refreshed live from
# GET {facilitator}/supported and cached. Clients put this account as the
# transaction fee payer so the facilitator can sponsor + settle.
FEE_PAYER_FALLBACK = "CjNFTjvBhbJJd2B5ePPMHRLx1ELZpa8dwQgGL727eKww"
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

PRICE_LOCALIZE_USDC = os.environ.get("PRICE_LOCALIZE_USDC", "0.10")
PRICE_REVIEW_USDC = os.environ.get("PRICE_REVIEW_USDC", "0.10")
PAID_TOOL_PRICES = {  # tool name -> price in USDC (string, decimal)
    "localize_text": PRICE_LOCALIZE_USDC,
    "localization_review": PRICE_REVIEW_USDC,
}

SERVER_NAME = "solvent-localization"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-03-26"

# --------------------------------------------------------------------------
# Glossary
# --------------------------------------------------------------------------


def _renderings(recommended: str):
    """Acceptable surface forms for a 'Recommended Chinese' cell.

    e.g. 'Solana（保持英文）' -> ['Solana']; '纪元（Epoch）' -> ['纪元', 'Epoch'];
    '开发者网络（Devnet）' -> ['开发者网络', 'Devnet']; '区块链' -> ['区块链'].
    """
    s = (recommended or "").strip()
    if not s:
        return []
    m = re.match(r"^(.*?)（(.*?)）\s*$", s)
    forms = []
    if m:
        head, paren = m.group(1).strip(), m.group(2).strip()
        if "保持英文" in paren or paren in ("保持英文",):
            if head:
                forms.append(head)
        else:
            if head:
                forms.append(head)
            if paren and "保持" not in paren:
                forms.append(paren)
    else:
        forms.append(s)
    out = []
    for f in forms:
        for part in re.split(r"[／/]", f):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _avoid_term(avoid_notes: str):
    """Extract the concrete 'do not use' term from an Avoid/Notes cell, if any."""
    s = (avoid_notes or "").strip()
    if not s:
        return None
    m = re.match(r"^(.{1,12}?)\s+(?:is|appears)\b", s)
    if m:
        return m.group(1).strip(" ,;")
    if len(s) <= 8 and " " not in s and "，" not in s and ";" not in s:
        return s
    return None


class Glossary:
    def __init__(self, path):
        self.entries = []
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                en = (row.get("English") or "").strip()
                zh = (row.get("Recommended Chinese") or "").strip()
                if not en or not zh:
                    continue
                self.entries.append(
                    {
                        "category": (row.get("Category") or "").strip(),
                        "english": en,
                        "chinese": zh,
                        "renderings": _renderings(zh),
                        "avoid_term": _avoid_term(row.get("Avoid / Notes") or ""),
                        "avoid_notes": (row.get("Avoid / Notes") or "").strip(),
                        "usage_note": (row.get("Usage Note") or "").strip(),
                    }
                )
        # Longest English term first so 'block height' wins over 'block'.
        self._by_en_len = sorted(
            self.entries, key=lambda e: len(e["english"]), reverse=True
        )

    def lookup(self, term: str, limit: int = 10):
        t = (term or "").strip()
        if not t:
            return []
        tl = t.lower()
        exact, partial = [], []
        for e in self.entries:
            en_l = e["english"].lower()
            forms = e["renderings"]
            if tl == en_l or t == e["chinese"] or t in forms:
                exact.append(e)
            elif tl in en_l or en_l in tl or t in e["chinese"] or any(t in f for f in forms):
                partial.append(e)
        return (exact + partial)[:limit]

    def match_in_text(self, text: str, direction: str, limit: int = 40):
        """Glossary entries whose source-side term appears in `text`."""
        hits = []
        if direction == "en->zh":
            for e in self._by_en_len:
                pat = r"(?<![A-Za-z0-9])" + re.escape(e["english"]) + r"(?![A-Za-z0-9])"
                if re.search(pat, text, flags=re.IGNORECASE):
                    hits.append(e)
                if len(hits) >= limit:
                    break
        else:  # zh->en: match on the Chinese renderings
            for e in self.entries:
                if any(f and f in text for f in e["renderings"]):
                    hits.append(e)
                if len(hits) >= limit:
                    break
        return hits


GLOSSARY = Glossary(GLOSSARY_PATH)

# --------------------------------------------------------------------------
# Translation backend: ask.py (free-LLM pool)
# --------------------------------------------------------------------------


def _clean_pool_output(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("[provider=") or s.startswith("[pool]") or s.startswith("ERROR:"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def ask_pool(prompt: str, task: str = "general", system: str = None,
             max_tokens: int = 2000) -> str:
    cmd = [
        "python3", ASK_PY,
        "--task", task,
        "--risk", "a",
        "--privacy", "public",
        "--verify", "none",
        "--max-tokens", str(max_tokens),
    ]
    if system:
        cmd += ["--system", system]
    cmd.append(prompt)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=ASK_TIMEOUT)
    out = _clean_pool_output(proc.stdout)
    if proc.returncode != 0 or not out:
        raise RuntimeError(
            "translation backend failed (ask.py rc=%s): %s"
            % (proc.returncode, (proc.stderr or proc.stdout or "")[-300:])
        )
    return out


STYLE_RULES = """SOLVENT house style (from the Web3 EN-ZH Localization Kit):
- Keep project, token, chain and product names in English inside Chinese text (e.g. Solana, USDC); never transliterate brand names.
- Use Arabic numerals; be careful with 万/亿 conversions (10,000 = 1万, 100,000,000 = 1亿).
- Anchor dates/times bilingually when both audiences matter (北京时间 + UTC).
- No hype or guaranteed-return wording: never use 稳赚 / 保本 / 零风险 / guaranteed returns phrasing; keep risk wording factual.
- Prefer natural Chinese sentence order over literal calques of English syntax; keep UI strings short.
- For ZH->EN: capitalize token symbols (USDC, SOL), sentence-case UI labels, expand Chinese date formats to unambiguous English dates."""

TRANSLATOR_SYSTEM = (
    "You are SOLVENT's senior EN<->ZH Web3 localization specialist. "
    "Translate faithfully and idiomatically; output ONLY the translated text, "
    "no explanations, no quotes around it.\n" + STYLE_RULES
)

# --------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------


def _detect_direction(text: str, source_language: str, target_language: str):
    if target_language:
        tgt = "zh" if target_language.lower().startswith("zh") else "en"
        return ("en->zh" if tgt == "zh" else "zh->en")
    if source_language and source_language != "auto":
        src = "zh" if source_language.lower().startswith("zh") else "en"
        return ("zh->en" if src == "zh" else "en->zh")
    return "zh->en" if re.search(r"[\u4e00-\u9fff]", text or "") else "en->zh"


def _term_block(entries, direction):
    lines = []
    for e in entries:
        if direction == "en->zh":
            lines.append("- %s => %s" % (e["english"], " / ".join(e["renderings"]) or e["chinese"]))
        else:
            lines.append("- %s => %s" % (" / ".join(e["renderings"]) or e["chinese"], e["english"]))
    return "\n".join(lines)


def tool_localize_text(args):
    text = args.get("text") or ""
    if not text.strip():
        raise ValueError("argument 'text' is required and must be non-empty")
    if len(text) > 8000:
        raise ValueError("text too long for one call (max 8000 chars); split it up")
    direction = _detect_direction(
        text, args.get("source_language") or "auto", args.get("target_language")
    )
    entries = GLOSSARY.match_in_text(text, direction)
    system = TRANSLATOR_SYSTEM
    if entries:
        system += (
            "\n\nMANDATORY TERMINOLOGY (use exactly these renderings):\n"
            + _term_block(entries, direction)
        )
    src_name = "English" if direction == "en->zh" else "Simplified Chinese"
    tgt_name = "Simplified Chinese" if direction == "en->zh" else "English"
    prompt = "Translate the following %s text into %s:\n\n%s" % (src_name, tgt_name, text)
    try:
        out = ask_pool(prompt, task="translate", system=system)
    except Exception:
        out = ask_pool(prompt, task="general", system=system)

    warnings, applied = [], []
    if direction == "en->zh":
        missing = []
        for e in entries:
            if any(f in out for f in e["renderings"]):
                applied.append(e["english"])
            else:
                missing.append(e)
        for e in entries:
            if e["avoid_term"] and e["avoid_term"] in out:
                warnings.append(
                    "output contains avoided rendering '%s' for '%s' (%s)"
                    % (e["avoid_term"], e["english"], e["avoid_notes"])
                )
        if missing:
            fix = "\n".join(
                "- '%s' must be rendered as: %s" % (e["english"], " / ".join(e["renderings"]))
                for e in missing
            )
            repair_prompt = (
                "The draft translation below violates mandatory terminology. "
                "Rewrite it fixing ONLY the listed terms, keep everything else identical.\n\n"
                "Fixes:\n%s\n\nDraft:\n%s" % (fix, out)
            )
            try:
                out2 = ask_pool(repair_prompt, task="general", system=TRANSLATOR_SYSTEM)
                still = [
                    e["english"] for e in missing
                    if not any(f in out2 for f in e["renderings"])
                ]
                out = out2
                applied = [e["english"] for e in entries if any(f in out for f in e["renderings"])]
                if still:
                    warnings.append("terminology not fully applied after repair: %s" % ", ".join(still))
            except Exception as exc:  # repair is best-effort
                warnings.append("terminology repair pass failed: %s" % exc)

    return {
        "translation": out,
        "direction": direction,
        "source_language": "en" if direction == "en->zh" else "zh",
        "target_language": "zh" if direction == "en->zh" else "en",
        "glossary_terms_applied": applied,
        "glossary_terms_matched": [e["english"] for e in entries],
        "warnings": warnings,
        "backend": "solvent free-LLM pool (ask.py)",
    }


def tool_glossary_lookup(args):
    term = args.get("term") or ""
    if not term.strip():
        raise ValueError("argument 'term' is required")
    hits = GLOSSARY.lookup(term, limit=int(args.get("limit") or 10))
    return {
        "term": term,
        "count": len(hits),
        "entries": [
            {
                "category": e["category"],
                "english": e["english"],
                "recommended_chinese": e["chinese"],
                "avoid": e["avoid_notes"] or None,
                "usage_note": e["usage_note"] or None,
            }
            for e in hits
        ],
    }


REVIEW_SYSTEM = (
    "You are a bilingual EN<->ZH Web3 localization QA reviewer for SOLVENT. "
    "You flag terminology errors, literal calques, tone problems, hype or "
    "guaranteed-return wording, number/date format problems and unnatural phrasing. "
    "Respond with STRICT JSON only: {\"issues\": [{\"severity\": \"high|medium|low\", "
    "\"excerpt\": \"...\", \"problem\": \"...\", \"suggestion\": \"...\"}]}. "
    "If the draft is clean, return {\"issues\": []}.\n" + STYLE_RULES
)


def tool_localization_review(args):
    text = args.get("text") or ""
    if not text.strip():
        raise ValueError("argument 'text' is required and must be non-empty")
    if len(text) > 8000:
        raise ValueError("text too long for one call (max 8000 chars)")
    language = (args.get("language") or "auto").lower()
    is_zh = language.startswith("zh") or (language == "auto" and re.search(r"[\u4e00-\u9fff]", text))
    issues = []

    # Deterministic local checks (no LLM needed).
    if is_zh:
        for e in GLOSSARY.entries:
            if e["avoid_term"] and e["avoid_term"] in text:
                issues.append({
                    "severity": "high",
                    "type": "terminology",
                    "excerpt": e["avoid_term"],
                    "problem": "Avoided rendering for '%s'. %s" % (e["english"], e["avoid_notes"]),
                    "suggestion": "Use '%s' instead." % (" / ".join(e["renderings"]) or e["chinese"]),
                    "source": "glossary",
                })
        for hype in ("稳赚", "保本", "零风险", "稳赚不赔", " guaranteed"):
            if hype.strip() and hype.strip() in text:
                issues.append({
                    "severity": "high", "type": "risk_wording", "excerpt": hype.strip(),
                    "problem": "Guaranteed-return / zero-risk wording is a compliance and trust hazard in Web3 copy.",
                    "suggestion": "Replace with factual, non-promissory wording.",
                    "source": "style-guide",
                })

    # LLM pass, grounded with the glossary entries relevant to this text.
    direction = "zh->en" if not is_zh else "en->zh"
    relevant = GLOSSARY.match_in_text(text, "zh->en" if is_zh else "en->zh")
    prompt = "Review this %s draft localization.\n" % ("Chinese" if is_zh else "English")
    if relevant:
        prompt += "\nRelevant mandatory glossary entries:\n" + _term_block(relevant, direction) + "\n"
    prompt += "\nDraft:\n%s" % text
    llm_issues, llm_error = [], None
    try:
        raw = ask_pool(prompt, task="review", system=REVIEW_SYSTEM)
        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            for it in parsed.get("issues", []):
                it.setdefault("source", "llm-review")
                llm_issues.append(it)
        else:
            llm_error = "review model did not return JSON"
    except Exception as exc:
        llm_error = str(exc)

    seen = set()
    merged = []
    for it in issues + llm_issues:
        key = (it.get("excerpt"), it.get("problem"))
        if key not in seen:
            seen.add(key)
            merged.append(it)
    return {
        "language_detected": "zh" if is_zh else "en",
        "issue_count": len(merged),
        "issues": merged,
        "llm_review_error": llm_error,
        "note": "Deterministic glossary/style checks always run; the LLM pass adds tone and phrasing findings.",
    }


TOOL_FUNCS = {
    "localize_text": tool_localize_text,
    "glossary_lookup": tool_glossary_lookup,
    "localization_review": tool_localization_review,
}

TOOLS = [
    {
        "name": "localize_text",
        "description": (
            "Translate text between English and Simplified Chinese with Web3/Solana "
            "terminology enforced from SOLVENT's curated 238-term glossary (the same "
            "term base sold in the SOLVENT Localization Kit). Use for announcements, "
            "docs, UI strings and social posts aimed at Chinese-speaking users, or the "
            "reverse. Direction is auto-detected unless specified."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to translate (max 8000 chars)."},
                "source_language": {"type": "string", "enum": ["auto", "en", "zh"], "default": "auto"},
                "target_language": {"type": "string", "enum": ["zh", "en"],
                                     "description": "Optional; overrides direction."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "glossary_lookup",
        "description": (
            "Look up a Web3 term in SOLVENT's EN<->ZH glossary: recommended Chinese "
            "rendering, renderings to avoid, and a usage note. Free."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "English term or Chinese rendering, e.g. 'staking' or '质押'."},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["term"],
        },
    },
    {
        "name": "localization_review",
        "description": (
            "QA a draft EN or ZH localization: flags glossary violations (deterministic), "
            "avoided/literal renderings, hype and guaranteed-return wording, and tone or "
            "phrasing problems. Returns structured issues with fixes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Draft translation to review (max 8000 chars)."},
                "language": {"type": "string", "enum": ["auto", "zh", "en"], "default": "auto"},
            },
            "required": ["text"],
        },
    },
]

# --------------------------------------------------------------------------
# x402 payments (v1, exact scheme, USDC on Solana, PayAI facilitator)
#
# Flow (server side):
#   1. Paid request without X-PAYMENT header -> HTTP 402 with
#      {"x402Version":1, "error": ..., "accepts":[PaymentRequirements]}.
#   2. Client retries with X-PAYMENT: base64(JSON PaymentPayload) where the
#      payload carries a client-signed Solana transaction (transferChecked of
#      USDC to payTo, facilitator's feePayer sponsoring gas).
#   3. We POST {x402Version, paymentPayload, paymentRequirements} to the
#      facilitator /verify. Invalid -> 402 with the facilitator's reason.
#   4. We run the tool, then POST the same body to /settle. On success the
#      result goes out with an X-PAYMENT-RESPONSE header (base64 settle
#      receipt). Settle-after-serve mirrors the reference x402 middleware: a
#      failed tool call never charges the client.
#   Replay protection: a payment payload hash is single-use once settled.
#
# No facilitator account or API key is required for the standard exact-scheme
# lane (checked live against GET /supported). Nothing here needs mainnet funds
# on the server side: the facilitator sponsors gas and settles client funds.
# --------------------------------------------------------------------------

_fee_payer_cache = {"value": None, "ts": 0.0}
_fee_payer_lock = threading.Lock()
_settled_payload_hashes = set()
_settled_lock = threading.Lock()


def _http_json(method, url, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def get_fee_payer():
    with _fee_payer_lock:
        if _fee_payer_cache["value"] and time.time() - _fee_payer_cache["ts"] < 300:
            return _fee_payer_cache["value"]
    try:
        _, sup = _http_json("GET", FACILITATOR_URL.rstrip("/") + "/supported")
        for kind in sup.get("kinds", []):
            if (kind.get("x402Version") == 1 and kind.get("scheme") == "exact"
                    and kind.get("network") == X402_NETWORK):
                fp = (kind.get("extra") or {}).get("feePayer")
                if fp:
                    with _fee_payer_lock:
                        _fee_payer_cache.update(value=fp, ts=time.time())
                    return fp
    except Exception:
        pass
    return FEE_PAYER_FALLBACK


def _atomic(price_usdc: str) -> str:
    # USDC has 6 decimals.
    whole, _, frac = str(price_usdc).partition(".")
    frac = (frac + "000000")[:6]
    return str(int(whole or "0") * 1_000_000 + int(frac or "0"))


def payment_requirements(tool_name: str, resource_url: str):
    price = PAID_TOOL_PRICES[tool_name]
    return {
        "scheme": "exact",
        "network": X402_NETWORK,
        "maxAmountRequired": _atomic(price),
        "resource": resource_url,
        "description": "SOLVENT %s — Web3 EN<->ZH localization (%s USDC/call)"
                       % (tool_name, price),
        "mimeType": "application/json",
        "payTo": PAY_TO_ADDRESS,
        "maxTimeoutSeconds": 300,
        "asset": USDC_MINT,
        "extra": {"feePayer": get_fee_payer(), "name": "USD Coin", "version": "2"},
    }


# --------------------------------------------------------------------------
# Discovery manifest: v2 resource shape (what the PayAI index / CDP Bazaar
# ingests). Field-by-field evidence is documented in X402-V2-NOTES.md.
# The 402 challenge below stays v1; these builders only shape the manifest.
# --------------------------------------------------------------------------

RESOURCE_DESCRIPTIONS = {
    "localize_text": (
        "Translate text between English and Simplified Chinese with Web3 "
        "terminology enforced from SOLVENT's curated 238-term glossary "
        "(announcements, docs, UI strings, social posts). POST JSON "
        "{text, source_language?, target_language?}."
    ),
    "localization_review": (
        "QA a draft English or Chinese localization: flags glossary "
        "violations, avoided/literal renderings, hype and guaranteed-return "
        "wording, and tone problems, with suggested fixes. POST JSON "
        "{text, language?}."
    ),
}

_BAZAAR_BODIES = {
    "localize_text": {
        "example_in": {
            "text": "Staking rewards are live on mainnet. Connect your wallet and claim your airdrop.",
            "source_language": "auto",
            "target_language": "zh",
        },
        "fields": {
            "text": {"type": "string", "required": True,
                     "description": "Text to translate (max 8000 chars).",
                     "example": "Staking rewards are live on mainnet."},
            "source_language": {"type": "string",
                                "description": "'auto' (default), 'en' or 'zh'.",
                                "example": "auto"},
            "target_language": {"type": "string",
                                "description": "Optional target: 'zh' or 'en'; overrides direction.",
                                "example": "zh"},
        },
        "example_out": {
            "translation": "质押奖励已在主网上线。连接钱包即可领取空投。",
            "direction": "en->zh",
            "glossary_terms_applied": ["staking", "mainnet", "wallet", "airdrop"],
            "warnings": [],
        },
    },
    "localization_review": {
        "example_in": {"text": "请确认这笔事务。", "language": "auto"},
        "fields": {
            "text": {"type": "string", "required": True,
                     "description": "Draft translation to review (max 8000 chars).",
                     "example": "请确认这笔事务。"},
            "language": {"type": "string",
                         "description": "'auto' (default), 'zh' or 'en'.",
                         "example": "auto"},
        },
        "example_out": {
            "language_detected": "zh",
            "issue_count": 1,
            "issues": [{
                "severity": "high", "type": "terminology", "excerpt": "事务",
                "problem": "Avoided rendering for 'transaction'.",
                "suggestion": "Use '交易' instead.",
            }],
        },
    },
}


def payment_requirements_v2(tool_name: str):
    """x402 v2 payment requirements: CAIP-2 network, `amount` (atomic string),
    no resource/description/mimeType at this level, extra carries feePayer."""
    return {
        "scheme": "exact",
        "network": X402_NETWORK_V2,
        "amount": _atomic(PAID_TOOL_PRICES[tool_name]),
        "asset": USDC_MINT,
        "payTo": PAY_TO_ADDRESS,
        "maxTimeoutSeconds": 300,
        "extra": {"feePayer": get_fee_payer()},
    }


def _bazaar_block(tool_name: str):
    spec = _BAZAAR_BODIES[tool_name]
    body_props = {}
    for fname, f in spec["fields"].items():
        prop = {"type": f["type"], "description": f["description"]}
        if "example" in f:
            prop["example"] = f["example"]
        body_props[fname] = prop
    required = [n for n, f in spec["fields"].items() if f.get("required")]
    info = {
        "input": {
            "type": "http",
            "method": "POST",
            "bodyType": "json",
            "body": spec["example_in"],
            "bodyFields": {
                n: {"type": f["type"], "description": f["description"],
                    **({"example": f["example"]} if "example" in f else {})}
                for n, f in spec["fields"].items()
            },
        },
        "output": {"type": "json", "example": spec["example_out"]},
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["input"],
        "properties": {
            "input": {
                "type": "object",
                "required": ["type", "method", "bodyType", "body"],
                "properties": {
                    "type": {"type": "string", "const": "http"},
                    "method": {"type": "string", "enum": ["POST"]},
                    "bodyType": {"type": "string", "enum": ["json"]},
                    "body": {"type": "object", "required": required,
                             "properties": body_props},
                },
                "additionalProperties": False,
            },
            "output": {
                "type": "object",
                "required": ["type"],
                "properties": {
                    "type": {"type": "string"},
                    "example": {"type": "object"},
                },
            },
        },
    }
    return {"info": info, "schema": schema}


def discovery_resource_v2(tool_name: str, resource_url: str):
    """One v2-shaped discovery entry, mirroring the PayAI index items."""
    desc = RESOURCE_DESCRIPTIONS[tool_name]
    return {
        "resource": resource_url,
        "type": "http",
        "x402Version": 2,
        "description": desc,
        "mimeType": "application/json",
        "serviceName": "SOLVENT Localization",
        "tags": ["localization", "translation", "english-chinese", "web3", "mcp"],
        "iconUrl": None,
        "metadata": {"mimeType": "application/json", "description": desc},
        "accepts": [payment_requirements_v2(tool_name)],
        "extensions": {"bazaar": _bazaar_block(tool_name)},
    }


def discovery_resource_v1(tool_name: str, resource_url: str):
    """The legacy v1-shaped entry, kept verbatim for v1-only clients."""
    return {
        "resource": resource_url,
        "tool": tool_name,
        "price_usdc": PAID_TOOL_PRICES[tool_name],
        "accepts": [payment_requirements(tool_name, resource_url)],
    }


class PaymentError(Exception):
    def __init__(self, reason, message=""):
        super().__init__(message or reason)
        self.reason = reason
        self.message = message or reason


def verify_payment(payment_header: str, requirements: dict):
    """Validate an X-PAYMENT header against the facilitator. Returns the
    decoded PaymentPayload; raises PaymentError otherwise."""
    try:
        payload = json.loads(base64.b64decode(payment_header))
    except Exception:
        raise PaymentError("invalid_payment_payload", "X-PAYMENT is not base64 JSON")
    if payload.get("x402Version") != 1:
        raise PaymentError("invalid_x402_version", "only x402Version 1 is accepted")
    if payload.get("scheme") != requirements["scheme"] or payload.get("network") != requirements["network"]:
        raise PaymentError("payment_requirements_mismatch",
                           "payload scheme/network does not match the quoted requirements")
    digest = hashlib.sha256(payment_header.encode()).hexdigest()
    with _settled_lock:
        if digest in _settled_payload_hashes:
            raise PaymentError("payment_already_used", "this payment payload was already settled")
    body = {"x402Version": 1, "paymentPayload": payload, "paymentRequirements": requirements}
    try:
        _, resp = _http_json("POST", FACILITATOR_URL.rstrip("/") + "/verify", body)
    except Exception as exc:
        raise PaymentError("facilitator_unavailable", "verify call failed: %s" % exc)
    if not resp.get("isValid"):
        raise PaymentError(resp.get("invalidReason") or "invalid_payment",
                           resp.get("invalidMessage") or "facilitator rejected the payment")
    return payload, body, digest


def settle_payment(verify_body: dict, digest: str):
    _, resp = _http_json("POST", FACILITATOR_URL.rstrip("/") + "/settle", verify_body)
    if resp.get("success"):
        with _settled_lock:
            _settled_payload_hashes.add(digest)
    return resp


# --------------------------------------------------------------------------
# MCP JSON-RPC dispatch (shared by stdio + HTTP)
# --------------------------------------------------------------------------


def _rpc_result(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _rpc_error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def dispatch_rpc(msg):
    """Returns a response dict, or None for notifications."""
    if not isinstance(msg, dict):
        return _rpc_error(None, -32600, "invalid request")
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        params = msg.get("params") or {}
        return _rpc_result(rid, {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method == "ping":
        return _rpc_result(rid, {})
    if method == "tools/list":
        return _rpc_result(rid, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = TOOL_FUNCS.get(name)
        if fn is None:
            return _rpc_error(rid, -32602, "unknown tool: %s" % name)
        try:
            result = fn(args)
            return _rpc_result(rid, {
                "content": [{"type": "text",
                             "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                "structuredContent": result,
                "isError": False,
            })
        except Exception as exc:
            return _rpc_result(rid, {
                "content": [{"type": "text", "text": "error: %s" % exc}],
                "isError": True,
            })
    if rid is None:
        return None  # notification (e.g. notifications/initialized)
    return _rpc_error(rid, -32601, "method not found: %s" % method)


def run_stdio():
    sys.stderr.write("[%s] stdio transport ready (payments gate applies to HTTP only)\n" % SERVER_NAME)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        resp = dispatch_rpc(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


# --------------------------------------------------------------------------
# HTTP transport
# --------------------------------------------------------------------------


def _paid_tool_for_request(path, rpc_msg):
    """Which paid tool (if any) an HTTP request wants to run."""
    if path == "/localize":
        return "localize_text"
    if path == "/review":
        return "localization_review"
    if path == "/mcp" and isinstance(rpc_msg, dict) and rpc_msg.get("method") == "tools/call":
        name = (rpc_msg.get("params") or {}).get("name")
        if name in PAID_TOOL_PRICES:
            return name
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep stdout clean
        sys.stderr.write("[http] %s\n" % (fmt % args))

    # -- helpers -----------------------------------------------------------
    def _send_json(self, status, obj, extra_headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _resource_url(self, path):
        if PUBLIC_BASE_URL:
            return PUBLIC_BASE_URL + path
        host = self.headers.get("Host", "localhost")
        return "http://%s%s" % (host, path)

    def _payment_gate(self, tool_name, path):
        """Returns (ok, settle_body, digest, receipt_headers). When not ok,
        the 402 response has already been sent."""
        requirements = payment_requirements(tool_name, self._resource_url(path))
        header = self.headers.get("X-PAYMENT") or self.headers.get("PAYMENT-SIGNATURE")
        if not header:
            self._send_json(402, {
                "x402Version": 1,
                "error": "X-PAYMENT header is required",
                "accepts": [requirements],
            })
            return False, None, None, None
        try:
            _, verify_body, digest = verify_payment(header, requirements)
        except PaymentError as e:
            self._send_json(402, {
                "x402Version": 1,
                "error": "%s: %s" % (e.reason, e.message),
                "accepts": [requirements],
            })
            return False, None, None, None
        return True, verify_body, digest, requirements

    def _settle_and_headers(self, verify_body, digest):
        try:
            receipt = settle_payment(verify_body, digest)
        except Exception as exc:
            sys.stderr.write("[x402] settle call failed: %s\n" % exc)
            return {}
        if not receipt.get("success"):
            sys.stderr.write("[x402] settle not successful: %s\n" % receipt)
            return {}
        return {"X-PAYMENT-RESPONSE": base64.b64encode(
            json.dumps(receipt).encode()).decode()}

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            self._send_json(200, {
                "status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION,
                "payments_enabled": PAYMENTS_ENABLED,
                "pay_to": PAY_TO_ADDRESS if PAYMENTS_ENABLED else None,
                "tools": [t["name"] for t in TOOLS],
                "glossary_entries": len(GLOSSARY.entries),
            })
        elif path == "/":
            self._send_json(200, {
                "name": SERVER_NAME, "version": SERVER_VERSION,
                "description": "SOLVENT EN<->ZH Web3 localization MCP server",
                "mcp_endpoint": "/mcp", "rest": ["/localize", "/glossary", "/review"],
                "x402_manifest": "/.well-known/x402",
                "site": "https://solvent-agent.pages.dev",
            })
        elif path == "/.well-known/x402":
            # v2-shaped resources are primary (PayAI index / Bazaar shape);
            # the legacy v1 entries ride along under resourcesV1 — the PayAI
            # facilitator advertises both versions (see X402-V2-NOTES.md).
            # Resource URLs come from PUBLIC_BASE_URL when set.
            resources, resources_v1 = [], []
            for tool in PAID_TOOL_PRICES:
                rest_path = "/localize" if tool == "localize_text" else "/review"
                url = self._resource_url(rest_path)
                resources.append(discovery_resource_v2(tool, url))
                resources_v1.append(discovery_resource_v1(tool, url))
            self._send_json(200, {
                "x402Version": 2,
                "supportedVersions": [1, 2],
                "payments_enabled": PAYMENTS_ENABLED,
                "facilitator": FACILITATOR_URL,
                "resources": resources,
                "resourcesV1": resources_v1,
                "free_tools": ["glossary_lookup"],
            })
        elif path == "/mcp":
            self._send_json(405, {"error": "stateless HTTP transport: POST JSON-RPC to /mcp"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "{}")
        except Exception:
            self._send_json(400, {"error": "request body must be JSON"})
            return

        if path == "/mcp":
            msgs = body if isinstance(body, list) else [body]
            paid_tool = None
            for m in msgs:
                paid_tool = _paid_tool_for_request(path, m)
                if paid_tool:
                    break
            settle_ctx = None
            if PAYMENTS_ENABLED and paid_tool:
                ok, verify_body, digest, _ = self._payment_gate(paid_tool, path)
                if not ok:
                    return
                settle_ctx = (verify_body, digest)
            responses = [r for r in (dispatch_rpc(m) for m in msgs) if r is not None]
            headers = {}
            if settle_ctx:
                headers = self._settle_and_headers(*settle_ctx)
            if not responses:
                self._send_json(202, {})
            else:
                self._send_json(200, responses[0] if not isinstance(body, list) else responses,
                                extra_headers=headers)
            return

        if path in ("/localize", "/review", "/glossary"):
            tool = {"/localize": "localize_text", "/review": "localization_review",
                    "/glossary": "glossary_lookup"}[path]
            settle_ctx = None
            if PAYMENTS_ENABLED and tool in PAID_TOOL_PRICES:
                ok, verify_body, digest, _ = self._payment_gate(tool, path)
                if not ok:
                    return
                settle_ctx = (verify_body, digest)
            try:
                result = TOOL_FUNCS[tool](body)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            headers = {}
            if settle_ctx:
                headers = self._settle_and_headers(*settle_ctx)
            self._send_json(200, result, extra_headers=headers)
            return

        self._send_json(404, {"error": "not found"})


def run_http(host, port):
    srv = ThreadingHTTPServer((host, port), Handler)
    sys.stderr.write(
        "[%s] HTTP transport on http://%s:%d (payments_enabled=%s, glossary=%d entries)\n"
        % (SERVER_NAME, host, port, PAYMENTS_ENABLED, len(GLOSSARY.entries))
    )
    srv.serve_forever()


def main():
    import argparse
    ap = argparse.ArgumentParser(description="SOLVENT Localization MCP server")
    ap.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    if args.transport == "http":
        run_http(args.host, args.port)
    else:
        run_stdio()


if __name__ == "__main__":
    main()
