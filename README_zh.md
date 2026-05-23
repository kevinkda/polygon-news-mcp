# polygon-news-mcp

[English](./README.md) | [简体中文](./README_zh.md)

只读 **Model Context Protocol (MCP)** 服务器，将
[Polygon.io](https://polygon.io/) 公开 API 包装为 **6 个工具**
（5 业务 + 2 meta），可在 Cursor、Claude Code 以及任意 MCP 客户端中使用。

> **只读** —— 每个工具只对 `https://api.polygon.io/` 发起 HTTPS GET，不会回写。

---

## 为什么独立成仓

`polygon-news-mcp` 是
[`schwab-marketdata-mcp`](https://github.com/kevinkda/schwab-marketdata-mcp) 和
[`sec-edgar-mcp`](https://github.com/kevinkda/sec-edgar-mcp) 的姐妹仓，专门补
Schwab 行情接口缺失的能力：**新闻 / 标的元数据 / 带情绪的 SEC filings 索引**。

| 能力 | Schwab MD | SEC EDGAR | **Polygon（本仓）** |
| --- | --- | --- | --- |
| 行情、K 线、期权链 | ✅ | ❌ | ❌ |
| 财报正文（10-K/10-Q/8-K） | ❌ | ✅ | 仅索引 |
| 新闻 + 情绪打分 | ❌ | ❌ | ✅ |
| 标的元数据 | 部分 | 部分 | ✅ |

三个仓库共享同一套硬化纪律：

- DuckDB 本地缓存（news 1 h；ticker_details 24 h；filings_index 6 h）。
- httpx 异步客户端 + 令牌桶限速（免费档：5 req/min）。
- Pydantic v2 入参校验（ticker 正则锚定）。
- stdio 加固，日志永远不会污染 JSON-RPC 流。
- 结构化错误体系（`PolygonAuthError` / `PolygonNotFoundError` /
  `PolygonRateLimitError` / `PolygonValidationError` / `PolygonTransientError`）。

---

## 成本与认证

- **成本：** 免费档（$0/月）每分钟 5 次请求；付费起步 $29/月（Starter，5x 限速），
  $79/月（Developer）。
- **认证：** 必须有 API key。免费注册：<https://polygon.io/dashboard/api-keys>，
  在 `.env` 中设置 `POLYGON_API_KEY=...`。

API key 通过 `Authorization: Bearer ...` 头发送，**不会**出现在请求 URL 里，
因此服务器日志永远无法回显 key。

---

## 快速开始

```bash
git clone https://github.com/kevinkda/polygon-news-mcp.git
cd polygon-news-mcp

uv sync --extra dev
uv run pre-commit install

cp .env.example .env
# 编辑 .env —— 把 POLYGON_API_KEY 改成你的 key

uv run polygon-news-mcp        # 在 stdio 上启动 MCP 服务器
```

在 Cursor / Claude Desktop 中注册 —— 见 [`docs/REGISTER.md`](./docs/REGISTER.md)。

---

## 工具清单

服务器对外暴露 **6 个工具**：4 业务 + 2 meta。

| Tool | 何时用 | 入参 | 缓存 TTL |
| --- | --- | --- | --- |
| `get_ticker_news` | 拉某个 ticker 最近的新闻聚合 | `ticker`, `limit=10`, `since_days=7` | 1 h |
| `get_market_news` | 拉全市场最近新闻 | `limit=20`, `since_hours=24` | 1 h |
| `get_ticker_details` | 拉 ticker 元数据（与 Schwab 互补） | `ticker` | 24 h |
| `list_sec_filings_index` | 拉 Polygon 的 SEC filings 索引（含 sentiment / category） | `ticker`, `since_days=90` | 6 h |
| `health_check` | 本地健康探针（不调 Polygon） | 无 | n/a |
| `get_server_info` | 本地版本/工具列表（不调 Polygon） | 无 | n/a |

详细的"何时用 / 入参 / 返回 / 示例"四段式见
[README.md](./README.md#tooling-surface)。

---

## 文档

- [`docs/REGISTER.md`](./docs/REGISTER.md) —— Cursor / Claude Desktop 注册步骤。
- [`docs/THREAT_MODEL.md`](./docs/THREAT_MODEL.md) —— STRIDE 威胁模型。
- [`docs/RELEASE.md`](./docs/RELEASE.md) —— 发布流程。
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) —— 贡献者工作流。

---

## License

MIT —— 见 [LICENSE](./LICENSE)。

---

## 负责任使用

Polygon.io 数据按 plan 许可给操作者使用。本服务器面向**单用户交互式研究**，
不要嵌入到聚合超过你 plan 限速的服务里。免费档默认 5 req/min，token bucket
也按这个值限流；只有在 plan 允许的情况下，才提高 `POLYGON_RATE_LIMIT_PER_MIN`。
