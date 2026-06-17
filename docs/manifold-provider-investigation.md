# Manifold Provider Investigation

Issue: https://github.com/aburkard/polymarket-search/issues/35

## Recommendation

Manifold is plausible as the next provider, but it should be treated as a
small provider spike before a full launch. The API is simple enough to index
markets, but Manifold has a noisy user-generated long tail, play-money/CASH
volume semantics, and answer-level data that requires extra detail requests for
multiple-choice markets.

The simplest useful version is:

- Add Manifold as a third provider behind the existing provider switch.
- Index open Manifold markets only at first.
- Filter out low-activity markets before they reach the UI.
- Fetch full details only for high-activity multiple-choice markets, so cards
  can show answer probabilities without doing one detail request for every
  market.
- Keep Manifold volume visibly provider-specific. Do not rank or label it as
  comparable to Polymarket/Kalshi dollar volume.

Do not start with archived Manifold markets or cross-provider matching. Those
are separate follow-up projects.

## API Shape

Manifold documents a public alpha API at:

https://docs.manifold.markets/api

Useful endpoints tested on 2026-06-17:

- `GET https://api.manifold.markets/v0/markets?limit=3`
- `GET https://api.manifold.markets/v0/search-markets?term=nba%20champion&filter=open&limit=3`
- `GET https://api.manifold.markets/v0/market/{id}`
- `GET https://api.manifold.markets/v0/slug/{slug}`

The list and search endpoints return lightweight market records with fields
that are enough for binary cards:

- `id`
- `question`
- `slug`
- `url`
- `creatorName`
- `creatorUsername`
- `creatorAvatarUrl`
- `createdTime`
- `closeTime`
- `outcomeType`
- `probability`
- `p`
- `volume`
- `volume24Hours`
- `totalLiquidity`
- `uniqueBettorCount`
- `isResolved`
- `lastUpdatedTime`
- `lastBetTime`
- `token`

For multiple-choice markets, the list/search responses do not include the
answer list. Full detail calls include `answers`, where each answer has the
display text and probability.

Example detail endpoint:

https://api.manifold.markets/v0/market/PtUqSZIpQ0

That means a high-quality Manifold card needs a second request for
multiple-choice markets, but a binary card can be built from the list payload.

## Search Quality Notes

Native Manifold search works, but it should not replace our own indexed search.
A sample query for `nba champion` returned thematically related markets, but not
necessarily the clean canonical result a prediction-market search app should
prefer. That is similar to the Kalshi issue we already saw: provider-native text
is not enough; we need our normalization, enrichment, ranking, and evals.

Manifold records include less structured provider taxonomy than Kalshi events
or Polymarket tags. The useful fields for search are mostly question text,
description from detail payloads, group slugs, creator name, and generated
enrichment.

## Product Fit

Pros:

- Public unauthenticated API for read-only indexing.
- Supports the same broad UI pattern: title, probability, volume/activity,
  close date, and provider link.
- Has many markets that Polymarket/Kalshi will not cover.

Cons:

- Long tail is much noisier than Polymarket/Kalshi.
- Volume is not directly comparable to dollar volume.
- Event images are not consistently available. List payloads expose creator
  avatars, not stable market/event artwork.
- Multiple-choice display requires extra detail fetches.
- API is labeled alpha, so we should isolate provider-specific code and keep
  health checks tight.

## Suggested Implementation Plan

1. Add a Manifold eval fixture before building UI support. Include queries that
   should catch exact entities and common synonyms, for example `nba champion`,
   `bitcoin`, `world cup`, `fed rates`, and `ai benchmark`.
2. Build `scripts/build-manifold-index.py` with conservative caps:
   - fetch open markets from `/v0/markets`
   - filter by `volume`, `volume24Hours`, `totalLiquidity`, or
     `uniqueBettorCount`
   - keep the raw payload small and deterministic
3. Add detail fetches only for multiple-choice markets that pass the activity
   filter. Sort answers by probability and keep the top visible answers plus a
   hidden searchable text field.
4. Add generated enrichment for new Manifold markets after the base index is
   stable. Reuse the same "only enrich new records" guardrails used by Kalshi.
5. Add `search-data-manifold.json` and provider-specific health thresholds.
6. Add Manifold to the provider segmented control after evals and data health
   pass locally.

## Open Decisions

- Where should the activity threshold start? A reasonable first pass is at
  least one of: `volume >= 100`, `uniqueBettorCount >= 5`, or
  `volume24Hours > 0`.
- Should Manifold be opt-in only in the provider switch, or should it eventually
  participate in an "All providers" view? Initial answer: opt-in only.
- Should we show creator avatars as icons? Initial answer: only as a fallback.
  They are not market images and may make search results feel less consistent.
- Should resolved Manifold markets be indexed? Initial answer: defer. Archived
  support is useful, but active-market search quality matters more.

## Bottom Line

Build a small active-only Manifold branch if we want another provider next. The
first version should optimize for search quality and simplicity, not coverage.
If the filtered active index feels useful and fast, archived Manifold and
cross-provider market linking can become separate issues.
