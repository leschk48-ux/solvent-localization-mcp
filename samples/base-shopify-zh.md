# Shopify 如何把稳定币支付带进 Base 上的结账流程（中文样章）

> Free sample by SOLVENT — the core of Base's official Shopify case study ("How Shopify brought stablecoin payments to checkout on Base", Base, 2026-10-29; https://www.base.org/customers/shopify), translated EN→ZH. Source retrieved 2026-11-03. Figures are as reported by Shopify and third-party dashboards as of October 2026 and may change. The full zh announcement pack is available as a fixed-price pack, paid in USDC.

---

## Shopify 如何把稳定币支付带进 Base 上的结账流程

Shopify 与 Coinbase 在 Base 上共同打造了 Commerce Payments Protocol（商业支付协议），让符合条件的商家能通过 Shopify Payments 接受 USDC 付款，并把一种新的支付方式接入商家已有的订单流程。

**协议规模：** 整个 Commerce Payments Protocol 的净结算支付量已超过 **4,200 万美元**，支付笔数超过 **44.8 万笔**。

**对买卖双方意味着什么：** 顾客可以用受支持的加密钱包付款，而商家仍按原有结算周期收到本地货币。对符合条件的商家来说，这意味着无需自己管理加密资产余额，就能服务稳定币买家。

**为什么是 Base：** Base 为协议的支付步骤提供快速、低成本的基础设施。Coinbase Payments 负责执行交易并补贴 Gas 费——买家用 USDC 付款时，无需另外持有 ETH 来支付网络费用。

**结账不是交易的终点：** 库存可能售罄、税费可能在结算前变动、订单可能被取消或退款。协议的智能合约会把买家授权的资金托管起来，直到商家请款（capture）才释放给商家：授权（authorization）是把资金为这笔订单预留，请款是把资金释放给商家。授权前可以取消订单，请款后可以退款。买家先批准支付条款，再由运营方提交交易；合约会阻止运营方修改这些条款；如果授权过期仍未请款，买家可以取回未请款的资金。

> "Shopify 与 Coinbase 并肩合作，打造能把稳定币带入日常商业的支付基础设施。Base 团队带来了深厚的专业能力，让支付能够在链上规模化运行，同时怀着合作的动力，去打造商家可以信赖的东西。"
> —— Nick Chen，Shopify 产品总监

该协议是开源的，因此其他电商平台和支付服务商也可以在同一基础上构建。

*注：USDC 结账由 Shopify 通过 Shopify Payments 提供，仅面向符合条件的商家和受支持的国家/地区。*
