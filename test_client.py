#!/usr/bin/env python3
"""End-to-end tests for the SOLVENT Localization MCP server.

Covers: stdio transport, HTTP transport (free beta mode), all three tools,
and the x402 paywall (challenge shape + facilitator rejection of a bogus
payment) with PAYMENTS_ENABLED=1. No real payment is made: a genuine settle
needs a client wallet signing a mainnet USDC transaction.

Usage: python3 test_client.py
Exit code 0 = all checks passed.
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "server.py")
RESULTS = []

PAY_TO = "ApC24q9FAsRV1ByKccGjySzchzXPwFx6AZL4Tir7NPbV"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" -- " + str(detail)[:220]) if detail else ""))


def http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, dict(e.headers), json.loads(raw or "{}")
        except Exception:
            return e.code, dict(e.headers), {"raw": raw}


def wait_health(port, proc, tries=40):
    for _ in range(tries):
        if proc.poll() is not None:
            raise RuntimeError("server exited early rc=%s" % proc.returncode)
        try:
            st, _, body = http("GET", "http://127.0.0.1:%d/health" % port)
            if st == 200:
                return body
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("server did not become healthy on port %d" % port)


def start_http(port, payments):
    env = dict(os.environ)
    env["PAYMENTS_ENABLED"] = "1" if payments else "0"
    proc = subprocess.Popen(
        ["python3", SERVER, "--transport", "http", "--host", "127.0.0.1",
         "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    health = wait_health(port, proc)
    return proc, health


# ---------------------------------------------------------------- stdio ---
def test_stdio():
    print("\n== stdio transport ==")
    proc = subprocess.Popen(["python3", SERVER, "--transport", "stdio"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            text=True)
    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                     "clientInfo": {"name": "test-client", "version": "0"}}})
    init = json.loads(proc.stdout.readline())
    check("stdio initialize",
          init["result"]["serverInfo"]["name"] == "solvent-localization",
          init["result"]["serverInfo"])
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = json.loads(proc.stdout.readline())
    names = [t["name"] for t in tools["result"]["tools"]]
    check("stdio tools/list", names == ["localize_text", "glossary_lookup",
                                        "localization_review"], names)
    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "glossary_lookup", "arguments": {"term": "staking"}}})
    call = json.loads(proc.stdout.readline())
    sc = call["result"]["structuredContent"]
    check("stdio glossary_lookup('staking')",
          sc["count"] >= 1 and sc["entries"][0]["recommended_chinese"].startswith("质押"),
          sc["entries"][0] if sc["entries"] else sc)
    proc.stdin.close()
    proc.terminate()


# ------------------------------------------------------- HTTP, free mode ---
def test_http_free():
    print("\n== HTTP transport, PAYMENTS_ENABLED=0 (free beta) ==")
    port = 8931
    proc, health = start_http(port, payments=False)
    base = "http://127.0.0.1:%d" % port
    try:
        check("health", health["status"] == "ok" and health["payments_enabled"] is False
              and health["glossary_entries"] == 238, health)

        st, _, r = http("POST", base + "/mcp",
                        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        check("http tools/list", st == 200 and len(r["result"]["tools"]) == 3)

        # glossary_lookup via MCP
        st, _, r = http("POST", base + "/mcp",
                        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                         "params": {"name": "glossary_lookup",
                                    "arguments": {"term": "空投"}}})
        sc = r["result"]["structuredContent"]
        check("glossary_lookup ZH->EN ('空投' = airdrop)",
              sc["count"] >= 1 and any(e["english"] == "airdrop" for e in sc["entries"]),
              sc["entries"][:1])

        # localize EN->ZH with glossary terms
        st, _, r = http("POST", base + "/mcp",
                        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                         "params": {"name": "localize_text",
                                    "arguments": {"text": "Staking rewards are live on mainnet. "
                                                          "Connect your wallet and claim your airdrop before the epoch ends."}}})
        sc = r["result"]["structuredContent"]
        check("localize_text EN->ZH runs", st == 200 and bool(sc["translation"]),
              sc["translation"])
        check("localize_text glossary enforced (质押/主网 present)",
              "质押" in sc["translation"] and "主网" in sc["translation"],
              {"applied": sc["glossary_terms_applied"], "warnings": sc["warnings"]})

        # localize ZH->EN
        st, _, r = http("POST", base + "/mcp",
                        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                         "params": {"name": "localize_text",
                                    "arguments": {"text": "质押奖励已经在主网上线，连接钱包即可领取空投。"}}})
        sc = r["result"]["structuredContent"]
        check("localize_text ZH->EN runs",
              st == 200 and "staking" in sc["translation"].lower(),
              sc["translation"])

        # review a draft containing an avoided rendering （事务 for transaction)
        st, _, r = http("POST", base + "/mcp",
                        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                         "params": {"name": "localization_review",
                                    "arguments": {"text": "请确认这笔事务，我们保证稳赚不赔。"}}})
        sc = r["result"]["structuredContent"]
        kinds = {(i.get("type"), i.get("excerpt")) for i in sc["issues"]}
        check("localization_review flags 事务 (avoided) + 稳赚不赔 (risk wording)",
              ("terminology", "事务") in kinds and any(i.get("type") == "risk_wording" for i in sc["issues"]),
              {"issue_count": sc["issue_count"], "kinds": sorted(str(k) for k in kinds),
               "llm_error": sc["llm_review_error"]})

        # REST facade
        st, _, r = http("POST", base + "/glossary", {"term": "wallet"})
        check("REST /glossary", st == 200 and r["count"] >= 1, r["entries"][:1])
    finally:
        proc.terminate()


# ------------------------------------------------------- HTTP, paid mode ---
def test_http_paid():
    print("\n== HTTP transport, PAYMENTS_ENABLED=1 (x402 paywall) ==")
    port = 8932
    proc, health = start_http(port, payments=True)
    base = "http://127.0.0.1:%d" % port
    try:
        check("health shows payments on", health["payments_enabled"] is True
              and health["pay_to"] == PAY_TO, health)

        st, _, man = http("GET", base + "/.well-known/x402")
        res0 = man["resources"][0]
        reqs = res0["accepts"][0]
        check("x402 manifest v2: CAIP-2 solana/exact/USDC/amount=0.10 -> agent wallet",
              st == 200 and man.get("x402Version") == 2 and res0.get("type") == "http"
              and res0.get("x402Version") == 2 and bool(res0.get("description"))
              and "bazaar" in (res0.get("extensions") or {})
              and reqs["scheme"] == "exact"
              and reqs["network"] == "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
              and reqs["asset"] == USDC_MINT and reqs["amount"] == "100000"
              and "maxAmountRequired" not in reqs
              and reqs["payTo"] == PAY_TO and bool(reqs["extra"]["feePayer"]),
              {k: reqs[k] for k in ("scheme", "network", "amount", "payTo")})
        v1reqs = man["resourcesV1"][0]["accepts"][0]
        check("x402 manifest keeps legacy v1 entries (resourcesV1)",
              v1reqs["scheme"] == "exact" and v1reqs["network"] == "solana"
              and v1reqs["asset"] == USDC_MINT
              and v1reqs["maxAmountRequired"] == "100000"
              and v1reqs["payTo"] == PAY_TO and bool(v1reqs["extra"]["feePayer"]),
              {k: v1reqs[k] for k in ("scheme", "network", "maxAmountRequired", "payTo")})

        st, _, r = http("POST", base + "/localize",
                        {"text": "Staking is live on mainnet."})
        acc = (r.get("accepts") or [{}])[0]
        check("unpaid /localize -> HTTP 402 challenge",
              st == 402 and r.get("x402Version") == 1 and acc.get("payTo") == PAY_TO,
              {"status": st, "error": r.get("error")})

        bogus = base64.b64encode(json.dumps({
            "x402Version": 1, "scheme": "exact", "network": "solana",
            "payload": {"transaction": "AAAA"}}).encode()).decode()
        st, _, r = http("POST", base + "/localize",
                        {"text": "Staking is live on mainnet."},
                        headers={"X-PAYMENT": bogus})
        check("bogus X-PAYMENT -> 402 (live facilitator /verify rejects it)",
              st == 402 and "error" in r, {"status": st, "error": r.get("error")})

        st, _, r = http("POST", base + "/mcp",
                        {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                         "params": {"name": "localize_text",
                                    "arguments": {"text": "hello"}}})
        check("unpaid MCP localize_text -> HTTP 402", st == 402, {"status": st})

        st, _, r = http("POST", base + "/mcp",
                        {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                         "params": {"name": "glossary_lookup",
                                    "arguments": {"term": "validator"}}})
        check("MCP glossary_lookup stays free under paywall",
              st == 200 and r["result"]["structuredContent"]["count"] >= 1,
              {"status": st})
    finally:
        proc.terminate()


def main():
    test_stdio()
    test_http_free()
    test_http_paid()
    failed = [r for r in RESULTS if not r[1]]
    print("\n==== %d/%d checks passed ====" % (len(RESULTS) - len(failed), len(RESULTS)))
    if failed:
        for name, _, detail in failed:
            print("FAILED: %s -- %s" % (name, detail))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
