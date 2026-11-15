# GoodTerms fixtures bundle

Saved on 2026-11-15 from the research session. Goes with `GOODTERMS_HANDOFF.md` (the spec "GoodTerms: prototype spec and build plan").

## fixtures/
- `rows_six_stores.json`: the answer key for the six original stores (statuses use confirms / rejects / doesnt_say; the brief's yes / no / doesnt_say map one to one). Findings are summaries, not the stores' exact sentences.
- `labels_five_extra_stores.json`: labels for the five extra stores, with product URLs. One sale label is not scoreable; one store must not be re-read until its terms are checked.
- `ask_replies_2026-11-15.json`: 18 `ask_business` replies, word for word, with a label for each reply and the page label beside it (16 of 18 agree).
- `catalog_search_2026-11-15.json`: one raw `search_catalog` response (queen mattress, max $200, ships to 94541).
- `pages_novilla/`: the reader's saved page text for novillashop.com, including the Black Friday page. Page text is kept for five stores (Novilla, Bear, SweetNight, NapQueen, BedStory). The others have to be re-read.
- `ask_probe_2026-11-15.json`: a second round of `ask_business` replies with the product attached: one opened-returns question at 30 more stores, and all three questions at 17 stores, including official stores of well-known brands.
- `not_excluded_cases.json`: saved replies and page sentences with the label each must get. The labeler tests in M3 run against these.
- `stores_seen_2026-11-15.json`: six stores seen that day, with variant IDs and prices where known. Reference only. The search is live and never pinned to a store list.
- `live_run_under_400_2026-11-15.json`: one run of the real scenario (live search, queen, under $400, ZIP 94541, no fixed stores): the first six stores after the size check, with their three Ask replies.
- `pages_bear/`: the reader's saved page text for bearmattress.com.
- `pages_sweetnight/`, `pages_napqueen/`, `pages_bedstory/`: the reader's saved page text for three stores from the live run, read on 2026-11-15. Each folder has a `report.json` listing the pages reached and the ones `robots.txt` blocked.
- `combining_cases.json`: the test cases for how the two sources combine. A yes counts only when the store's exact sentence is on one of its pages; a yes from the store's assistant alone is `assistant_only_yes`. Holds one case per row of the combining table, 12 saved cases from the live run with the exact page sentences (each one is present word for word in the saved page text), the expected result per store, and the 18 pairs from the six original stores.
- `checkout_links_2026-11-15.json`: the product URL and the catalog `checkout_url` for the six size-checked variants of the live run. None of these links has been opened.
- `status_definitions.md`: the recipe with the status definitions used for labelling.

## reader/
- `collector.py`: the scripted page reader. Usage: `python3 collector.py <outdir> <cap> <width> <product_url> [...]`

## mcp_tool/
- `server.py`, `core.py`, `rules.json`: the stub MCP tool `check_stores` (MCP Python SDK 2.x, `MCPServer`). `core.py` reads `evidence.json`; point it at `rows_six_stores.json`.

## live_call_scripts/
Working JSON-RPC calls with no credentials, using Shopify's example agent profiles. Replace the profile URL with your own.
- `ucp_caps.py`: reads each store's `/.well-known/ucp` and lists capabilities and the endpoint.
- `ucp_call.py`: `tools/list` for an endpoint and profile.
- `ask_test.py`: three `ask_business` questions per store.
- `catalog_test.py`: one `search_catalog` call.

Nothing here creates a cart or a checkout.
