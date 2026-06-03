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
curl 'https://polymarket-search-api.<your-subdomain>.workers.dev/?trending=1&limit=10'
```

## How it works

The worker fetches `search-data.json` from GitHub Pages on cold start, caches it in memory for 5 minutes, and runs the same `search()` function as the browser frontend. Cloudflare's CDN also caches the upstream fetch.

Cold latency: ~150-300ms (fetching index from GH Pages).
Warm latency: ~10-30ms (in-memory search at edge).
