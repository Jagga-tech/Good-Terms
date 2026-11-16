# GoodTerms

The full spec is `GoodTerms prototype spec and build plan.pdf` in this folder. Read it before any milestone.

## How we work

- One milestone at a time, M0 to M7. A milestone is done only when its checks pass. Stop there, show what was run and what came back, and wait for a go before the next one.
- Real live calls. No fake data.
- Ask before any push.
- If the plan is unclear or something does not work live, say so first. Do not guess.
- The model key lives in the owner's own `.env`. Never ask for it in chat and never write it to a file.

## Agent profile

- The profile is `docs/agent-profile.json`, served by jsDelivr from this GitHub repo. GitHub Pages is off: Shopify rejects its Cache-Control header, which lacks `public`.
- The one address is pinned in `docs/agent-profile.url`. The smoke script and the API both read it from there.
- Rule: whenever `docs/agent-profile.json` changes, update the pinned address in the same commit and run `make smoke` again. A commit cannot hold its own hash, so pin the new address to a new tag (`@profile-2`, `@profile-3`, ...), tag that commit, and push the tag with it. `make smoke` fails if the pinned address and the file differ.

## Commands

- `make dev` starts the API (port 8000) and the web app.
- `make test` runs the tests.
- `make smoke` runs the four live Shopify calls with our own agent profile.
- `uv run python -m api.mcp_server` runs the MCP tool `check_stores` (add `--http` for HTTP).
- `make frozen` runs the labeler and pipeline on frozen page text and saved replies, scored against the answer key. It calls the model and never calls a store.
- `make backup` starts the app in backup mode: saved results, with a banner and recorded dates. Live is the default.
- `make predemo` checks the profile and runs the demo request live twice. It sends no new Ask question unless `--ask` is added.
- `make coco` runs ten scripted conversations with Coco against saved data.
- `make live` runs five timed live checks: real search, Ask calls, paced page reads and model labels.
- `uv run python -m scripts.freeze_pages <product url or domain>` reads a store's pages once and freezes the text under `fixtures/`.
- `uv run python -m scripts.capture_search` runs the demo search once, live, and saves every raw response as a fixture. It calls the catalog and stores' public `/.well-known/ucp` files only, never Ask.

## Reading real stores

- Requests to one store are paced (0.4 s apart in a check, 1 s when freezing) and wait and retry on HTTP 429.
- robots.txt is honored for every address. A store listed in `BARRED` in `api/reader.py` is never read.
- Never change the answer key to make a check pass. Report the difference.
- Known difference from the key, left as it is: BonaNest, opened returns. The key says doesn't say; the labeler says no.

## Asking stores' assistants

- Ask without credentials has a small shared limit. One check of six stores is 18 questions. About 200 questions in an hour got us blocked for 21 minutes on 2026-11-15.
- Every reply is saved with the time it was asked and reused for the same store, product and question for the rest of the day (`labels.db`, table `replies`).
- Tests never call Ask live; `tests/conftest.py` makes any attempt fail. They use saved replies only.
- When Shopify blocks Ask, no further question is sent until the wait is over, and the screen says so in plain words.
- Do not run live checks back to back. Space rehearsals out.

## Fixtures

- `fixtures/` is the bundle as delivered. `fixtures/bundle_code/` holds its reader, MCP stub and live-call scripts for reference; the app's own code is in `api/`.
- The database is rebuilt from the fixtures every time the API starts.

## Decisions made after the plan

These two override the plan where they differ.

1. Demo rule (replaces decision 7 and the demo rule in M3): the demo needs only one store that says yes to all three conditions, counting only yeses found on pages. Everything else is reported, never forced.
2. Prices (replaces decision 3, the last sentence of guardrail 2, and the cart steps in M4): use the catalog price. No carts are created.

Rulings made during M1:

3. Seed: the six stores of the live run under $400 (`live_run_under_400_2026-11-15.json`), with catalog prices. Novilla, SweetNight, NapQueen and BedStory have their pages read, with the exact sentences from `combining_cases.json`. Dwellinhaus and Lee Furniture are closed with their replies (labels signed off by the owner) and the note "Pages were not read in this saved run." No yes row exists without the store's exact sentence; the database refuses one. The six original stores are used only as combining test cases.
4. BedStory's two rows the key marks not scoreable (opened returns, sale items): page status "doesn't say", flagged, both sentences shown. A hedged sentence ("unclear") counts as "doesn't say".
5. NapQueen's replies that open with yes and attach conditions keep the answer key's label, yes.
6. Opened returns, after re-checking the page text: Novilla's sentence swapped for one naming returns and opened mattresses; SweetNight's sentence is shown with its section heading; NapQueen is downgraded to an assistant-only yes because its page hedges on an opened mattress.
8. A yes is dropped in code when its sentence does not use the words its condition is about (return or refund for opened returns, free or prepaid for return shipping, sale or discount for sale items). This follows the owner's ruling that a trial length alone is not a clean yes.
7. The "couldn't read" state has no saved store. It is covered in tests only; no made-up store goes on screen.

Rulings made during M5 and M6:

9. One screen, two halves, stacked on a phone. Left: Coco as a message thread, the buyer's messages on the right and Coco's on the left, input at the bottom. Bubbles are allowed for Coco, in our three colours and not a copy of any messaging app; still no avatars and no typing dots. Right: two tabs, one at a time, "Buyer's Check" and "Merchant view: what a store would see". This replaces the plan's separate routes and its no-bubbles rule for Coco.
10. Prices: no "catalog price" on any row. One line above the list says "Prices are from Shopify's catalog. Shipping and tax are added at checkout."
11. A card whose store's pages disagree says "Its pages say different things" on the card itself.
15. The look, set by the owner on 2026-11-15, replaces guardrail 16's three-colours rule and the earlier layout rulings (9, 16):
    - Page: max width 1200px, centered, 24px padding; two columns, left 360px and right the rest, 32px gap; stacked under 1024px.
    - Colours: page #F6F8FB, cards #FFFFFF with a 1px #D5DAE4 border and 10px corners, main text #223354, small text #5E6A85, green #3F7D5C. No shadows, no gradients.
    - Type: IBM Plex Sans, weights 400, 500, 600; body 15px at 1.5; small text 13px; nothing smaller than 13px.
    - Left, staying in place: "GoodTerms", then one chat card headed "Coco, your agent". The buyer's messages on the right in navy; Coco's on the left on the page colour with the light border. Step lines come only from real events. A status line above the input says what Coco is doing. Input 44px with a navy Send button. No setup question.
    - Right: a switch, "Buyer's check" and "Merchant view", one view at a time. Buyer's check has three sections: "Stores checked", "Your decision" (a card), "What each store says" (one card, a row per store). Merchant view has the line "What a merchant would see. Built from this check, not from Shopify's data.", a "Viewing as" dropdown, a 22px headline and one card of parts.
    - Status labels: 13px bold, 6px corners. Yes is green fill; no is navy fill; doesn't say is white with a 1.5px navy outline; other statuses are outlined with their own words.
    - Buttons: main 48px navy; second 44px white with a navy border. "Go to checkout" is the only green button. Green is only for yes and that button.
17. Product photos are allowed (owner, 2026-11-15; replaces the no-photo rule). Each store row in Buyer's check shows the product photo, 72px square with 6px corners, then the product title and store name, with the price on the right. Merchant view's card starts with the product that was checked: photo, title and price. The photo is the real one from Shopify's catalog. When the catalog gives none, show a plain square with the product's first letter. Never a stock or made-up image.
18. Coco goes ahead when asked to buy (owner, 2026-11-15; replaces the refusal in M5 and the "never recommend a purchase" reading for this one case). With no store named, it takes the lowest-priced store that says yes to all 3, says so in one line with the price, and opens the review before checkout screen. A named store with a no or a gap is told to the buyer first and opened only after the buyer's own yes in a later message. If no store meets all 3, Coco says so and asks which store. The gate is in code (`open_review`): nothing opens before the whole check has finished. Coco never pays, never completes a checkout and never enters anything; the buyer pays on the store's page.
19. Coco talks like an agent, not a form. A hello gets a short hello back. It asks nothing before the buyer names a product, then asks only for what is missing, one thing at a time ("What size?", "What's your budget?"). The chat starts empty. A message of more than two sentences is cut to two in code.
13. The buyer's conditions show in one place only, above the store list on Buyer's Check.
14. Merchant view works for every store in the check and shows nothing about the buyer (no budget, price, choice or other store). Rules: pages answer all 3 → "Your pages answer all 3 of this buyer's conditions"; an answer that sits only on a sale page → tip to add it to the return policy; something missing → say what and where to add it; two pages disagree → name the two and say to make them agree; a clear no → "Your pages answer this clearly", with no advice to change policy. Every store gets a headline: all yes → "Your pages say yes to all 3 of this buyer's conditions"; all clear with some no → the counts of yes and no; pages disagree → "Your pages say different things about" plus the conditions; answers missing → "Your pages leave N of this buyer's conditions unanswered"; pages not read → the read note. No winning or losing words, no sales numbers.
12. Coco may quote a store's result in the row's exact words when asked about it after its check has finished.

## Guardrails

From the plan, as written.

1. Never call `complete_checkout`. No card or payment data anywhere in the system.
2. GoodTerms creates no checkout in the main flow and never sends the buyer's email or phone to a store. "Go to checkout" opens the catalog's checkout link for the exact variant shown. Comparison prices come from carts created with no buyer details.
3. Honor robots.txt and each store's terms. A store that bars automated reading is shown as "couldn't read".
4. Search is live and never pinned to a store list.
5. A status changes only through a new check of the store. Coco, the web app and merchants cannot change one.
6. A yes needs the store's exact sentence on one of its pages. "Not excluded" is never a yes. Silence and unreadable pages are never a yes.
7. A yes that comes only from the store's assistant is not a yes. It has its own status, "Store's assistant says yes. Not found on its pages." It is never green and never counts toward "Meets all 3".
8. The two sources are always labeled, shown word for word and dated. When they contradict each other, or two of the store's own pages do, the row is flagged and shows the stricter status.
9. Until a store's pages are fully read, each of its conditions shows "Still reading this store's pages". No green and no "Meets all 3" appear for that store before then. The assistant's replies show as they arrive.
10. On Buyer's Check the store's own words come first, before any status or label.
11. The interface never uses the words safe, verified, trusted, guaranteed or protected. This covers the app's own text and Coco's messages. A store's quoted words are shown as written.
12. Coco and Buyer's Check never recommend a store or a purchase. The price-gap line states two prices and their difference, nothing more.
13. Coco speaks as the buyer's own agent, in one or two short sentences.
14. Merchant View speaks to the merchant directly ("your store", "your pages", "your buyers"), starts with what the pages answer clearly, then what is missing, then where to add it. It never blames.
15. Merchant View holds no sales numbers, counts, promises, outcomes or selection, and shows nothing about the buyer.
16. Three colours only: sage green #3F7D5C, cool white #F6F8FB, navy #223354. Green appears only on a yes found on the store's pages.
17. GoodTerms does not look like a shopping site or a chatbot, and carries no Shopify logos, colours or wordmarks. Every screen has the footer "Prototype. Not affiliated with Shopify."
18. Secrets live in environment variables only: the model API key, and the Shopify client secret if the optional token checkout is ever built. They never appear in chat, source files, logs or commits.
19. Every offer shown is the size the buyer asked for.
20. The demo runs live. Recorded results are a backup and show their dates on screen.
21. The main flow uses no Shopify key or token, only our own agent profile. The Shop skill for personal agents is for personal use only, and `search_shop_policies_and_faqs` is deprecated.
22. Checkout links are https only and open in the buyer's browser. A `continue_url` from the optional token checkout is never stored or logged.
23. The optional token checkout is built last and is off by default. It needs the buyer's agreement before their email or phone goes to a store, and the buyer's IP goes only where Shopify requires it and is not stored.
24. No inline comments in Python.
