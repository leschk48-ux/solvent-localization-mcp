# Ritual Chain 快速入门（中文样章）

> Free sample by SOLVENT — the first section of Ritual Chain's official Quick Start (docs.ritualfoundation.org), translated EN→ZH with glossary-checked terminology. Source retrieved 2026-11-03. The full launch pack (announcement + tokenomics summary + developer quickstart) is available as a fixed-price pack, paid in USDC.

---

## 快速入门 — Ritual Chain

| 参数 | 值 |
|---|---|
| 链 ID（Chain ID） | 784 |
| 原生代币 | RITUAL（18 位小数） |
| 出块时间 | 约 350 毫秒 |
| 交易类型 | EIP-1559 + 0x10、0x11、0x12、0x13、0x77 |
| RPC（HTTP） | rpc.ritualfoundation.org |
| RPC（WebSocket） | rpc.ritualfoundation.org/ws |
| 区块链浏览器 | explorer.ritualfoundation.org |

四种 0x1x 交易类型均由协议生成，永远不会由用户提交：

- **0x10 TxScheduled**：执行一笔到期的 Scheduler 调用；
- **0x11 TxAsyncCommitment**：记录一项异步任务，并为其预留托管资金（escrow）；
- **0x12 TxAsyncSettlement**：支付托管资金，或交付两阶段计算的结果；
- **0x13 TxStakeHubReward**：每个区块强制包含的最后一笔交易，通过 StakeHub 分发区块奖励。

**0x77 TxPasskey** 由用户提交，使用 P-256/WebAuthn 或 secp256k1 签名。

`block.timestamp` 与 JSON-RPC 返回的时间戳均为 Unix 秒。

---

*Sample ends. Terminology follows SOLVENT's 238-term Web3 EN↔ZH glossary (Scheduler 调度器、escrow 托管、区块奖励等译法全篇统一）。*
