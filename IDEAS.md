# Polymarket Search — Ideas Log

Running braindump from early discussion. Not a plan. Cull/edit freely.

## Why this exists

Polymarket's own search (`gamma-api.polymarket.com/public-search`) ranks poorly:
top hit for `q=trump` was an already-closed daily-novelty market, not the
high-volume current Trump markets. Reddit threads confirm UX pain
(r/PolymarketTrading "UX is getting bad", r/CryptoCurrency "closed markets UI is
broken"). Several aggregators exist (Matchr, Metaforecast, Prediction Hunt,
Betmoar, Nevua, Stand.trade, NexusTools, PolySpyBot, etc.) but most bundle
search inside heavier products — there isn't an obvious clean
"Google-for-Polymarket."

## Core insight

Prediction-market queries are NOT document queries. They look like
`{entity, time bound, condition}` tuples — "fed cut december",
"btc 100k 2026", "trump 2028 win", "drake album before gta 6". Pure BM25
misses; pure embeddings hallucinate. Leverage is in understanding the
query structure.

## High-leverage ranking / retrieval ideas

1. **LLM-generated alt-phrasings at index time.** For each market, run a small
   model (Haiku) once to produce 5–10 ways a human might search for it.
   Index those alongside the question. ~$1 one-time per 10k markets.
   Likely the single biggest quality lift over Polymarket's own search.

2. **LLM query understanding at search time.** Pass query through a small
   model to extract entities, time bounds, conditions, domain. Only fire when
   lexical retrieval is low-confidence. ~$0.0001/search.

3. **Cross-encoder rerank on top-K.** Retrieve 50 with BM25 + vector,
   rerank with `bge-reranker-v2-m3` on local CPU (~50ms for 50 docs).
   Free, biggest post-retrieval quality lift.

4. **Quality boost from market signals.** Use `volume24hr`, `liquidity`,
   `commentCount`, `endDate` proximity, `volume1wk` to multiply BM25 score.
   Polymarket's own search clearly doesn't do this — that's why expired
   daily markets surface for evergreen queries.

5. **Index Polymarket's own `eventMetadata.context_description`.**
   They already generate LLM summaries per event; index them. Free
   semantic enrichment.

6. **Hand-curated synonyms.** ~50 lines: `btc↔bitcoin`, `fed↔federal reserve`,
   `cpi↔inflation`, ticker↔company. Catches 90% of abbreviation pain.

7. **Hybrid retrieval (BM25 + vector + rerank).** Textbook modern search.
   Meilisearch has built-in hybrid via HF embedders.

## Static / SEO leverage

8. **Pre-render ~5–20k entity × time × tag landing pages.** `/q/btc-2026`,
   `/q/trump-2028`, `/q/fed-rate-cuts`, `/topic/elections`. Each is a
   curated page with JSON-LD, regenerated weekly. Polymarket's own pages
   don't rank well for these long-tail queries — opportunity.

9. **Server-render `/m/[slug]` market pages** with og:images from
   Polymarket's S3 (free image hosting). SEO + share previews.

10. **Live odds badges in result rows** via Polymarket's CLOB WebSocket.
    Tiny detail, makes search results feel alive.

## Exotic / longer shots

11. **DuckDB-WASM client-side search.** Ship ~5MB compressed index to
    browser, FTS entirely client-side after first load. ~5ms searches.
    Loses LLM rerank, gains "feels instant." Worth prototyping.

12. **Cloudflare Vectorize + Workers AI.** All-edge stack, generous free
    tier, single provider.

13. **Static inverted-index shards on R2.** Worker fetches relevant shards
    by query token, ranks. Practically free.

14. **Browser-side embeddings via transformers.js / WebGPU.** Zero server
    cost. Ships the model + index, gets big — viability unclear.

15. **Subscribe-to-this-search via email/RSS.** Adjacent feature, could be
    sticky.

## Infra options compared

| Option | Cost | DX | Notes |
|---|---|---|---|
| Vercel + Neon (user's default) | free → ~$20/mo | great | Postgres FTS (tsvector + pg_trgm + ts_rank) is genuinely solid for this. pgvector when ready. |
| Vercel + Turso | free → cheap | good | libSQL/SQLite-as-service, edge-replicated, FTS5 + sqlite-vec. New dep to learn. |
| Cloudflare-everything (Pages + Workers + D1 + KV) | nearly free | medium | Free tier huge. D1 has FTS5 but no extensions (no sqlite-vec). Workers ≠ Node. |
| Fly.io + SQLite | $0–5/mo | high | Easy `fly deploy`, anycast. Premium over raw VPS. |
| **Hetzner CAX11 + Coolify** | **€3.29/mo** | **medium** | **2 vCPU / 4GB / 20TB egress. Best $/RAM. Coolify gives Fly-like DX.** |
| Meilisearch Cloud | free → $30/mo | great | Native hybrid, instant-search built-in, custom ranking rules one-liner. |
| Algolia | free (10k records) → $$$ | great | Best UX, gets expensive fast. |
| Typesense Cloud | ~$25/mo | good | Similar to Meili, less generous free tier. |

## Recommended starting combo (subject to revision)

- **Hetzner CAX11** running Coolify
- **Meilisearch** in hybrid mode (BM25 + HF embeddings)
- **Cron worker** that polls Polymarket `/events?active=true&closed=false`
  ordered by `updatedAt`, calls Haiku for alt-phrasings on new markets,
  upserts to Meilisearch
- **Local cross-encoder microservice** for reranking top 50
- **Postgres** (Neon free or on-the-box) as source of truth
- **Next.js on Vercel** for the frontend, with static `/m/[slug]` and
  `/q/[query]` pages
- **Cloudflare** in front for edge caching

Total: ~$5/mo + ~$1–5/mo Haiku.

## Things to skip

- Custom-trained embedding models (diminishing returns vs. off-the-shelf)
- Twitter/X scraping for alt-phrasings (LLM-generation is cleaner)
- Pure vector search alone (loses entity precision: "trump 2028" → year drops)
- User accounts / watchlists / alerts at v1

## Open questions for the experimentation phase

- How many active markets actually exist? Order-of-magnitude affects choices.
- Are the descriptions / context_descriptions consistently populated?
- What's the realistic update rate? (Drives polling cadence.)
- Does Polymarket expose a WebSocket for market-metadata changes, or only
  CLOB price updates?
- What does `/public-search` actually return for a battery of realistic
  queries? Need a concrete baseline.
- What's the tag taxonomy depth? Useful as ranking signal and facets.
