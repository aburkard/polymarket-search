# Cloudflare Worker — Curl-able JSON API

Same search engine as the static site, exposed as a JSON API that works with plain `curl`. Free tier: 100k requests/day.

## Deploy

```bash
cd worker
npm install -g wrangler   # or use bunx wrangler
wrangler login            # one-time
wrangler deploy
```

The worker will be deployed to `https://polymarket-search-api.<your-subdomain>.workers.dev`. Wrangler prints the URL after deploy.

## Test

```bash
curl 'https://polymarket-search-api.<your-subdomain>.workers.dev/?q=canada'
curl 'https://polymarket-search-api.<your-subdomain>.workers.dev/?q=bitcoin&limit=5'
curl 'https://polymarket-search-api.<your-subdomain>.workers.dev/?q=bitcoin&provider=kalshi&archived=1&limit=5'
curl 'https://polymarket-search-api.<your-subdomain>.workers.dev/?trending=1&limit=10'
curl 'https://polymarket-search-api.<your-subdomain>.workers.dev/kalshi/events/KXBTC-26JUN'
```

## How it works

The worker fetches provider-specific search indexes from GitHub Pages on cold start, caches them in memory for 5 minutes, and runs the same `search()` function as the browser frontend. Cloudflare's CDN also caches the upstream fetch. The Kalshi live event route is a narrow CORS proxy that returns the current markets for an event ticker so the static UI can refresh visible prices.

The `/kalshi/events/:ticker` route is a narrow CORS proxy for live Kalshi event payloads. It streams Kalshi's public event response and caches it for a few seconds so the static frontend can show fresh visible-card prices without calling Kalshi directly from the browser.

Cold latency: ~150-300ms (fetching index from GH Pages).
Warm latency: ~10-30ms (in-memory search at edge).
