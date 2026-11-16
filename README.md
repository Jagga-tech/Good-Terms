# GoodTerms

GoodTerms checks each store against a buyer's own conditions before checkout. It shows whether the store says yes, says no or doesn't say, with the store's own words as the evidence.

This is a prototype. It runs on your laptop against live Shopify stores. It is not affiliated with Shopify.

## The problem

A shopping agent can find a product and a price in seconds. It cannot tell you whether the store will take the product back.

Return terms are not data. Shopify's catalog gives a link to a refund policy, not the terms inside it. A store's assistant will answer a question about returns, but its answer has no link to the page behind it, changes from one call to the next, and sometimes says "yes" when the policy only fails to say "no".

So a buyer who cares about three things (can I return it once opened, is return shipping free, can I return it if I bought it on sale) has to read every store's policy pages by hand, or trust an agent's retelling.

## What GoodTerms does

For each store an agent finds, GoodTerms:

1. Asks the store's assistant each of the buyer's conditions, with the exact product attached.
2. Reads the store's own public pages: the product page, the return policy and the shipping policy first, then up to eight more only when a condition is still open.
3. Labels each source separately, and for the pages keeps the exact sentence and its address.
4. Checks that sentence is on the saved page word for word. If it is not, the page answer is dropped.
5. Combines the two sources into one status per condition.

The rules that decide the status:

- A yes needs the store's exact sentence on one of its pages.
- A yes that comes only from the store's assistant is not a yes. It gets its own status: "Store's assistant says yes. Not found on its pages."
- "Not excluded" is not a yes. A page that only lists clearance items as final sale says nothing about an item bought at a sale price.
- When the pages and the assistant contradict each other, or two of the store's own pages do, the stricter answer wins and the row is flagged.
- Silence and unreadable pages are never a yes.
- No store shows a yes until its pages are fully read.

Asking and reading are done in code. A model is used for one job only, labeling, and its labels are saved with the page text so the same page always gets the same answer.

## The screen

One screen, two halves.

**Coco, on the left.** Coco is the buyer's personal agent. You chat with it. It already knows the buyer's three conditions and ZIP code. It searches Shopify's catalog, confirms each offer is the size asked for, sends the stores to GoodTerms, and shows its work as it goes ("Searched Shopify's catalog · 6 stores"). It speaks in one or two short sentences, never recommends a store, and never states an answer that differs from the rows. Asked to buy, it takes the lowest-priced store that says yes to all three conditions and opens the review screen for it. It never pays and never enters anything.

**Buyer's check, on the right.** The rows from GoodTerms, drawn directly and not from Coco's words:

- *Stores checked*: the request, the buyer's conditions and one line stating the cheapest store overall and the cheapest that says yes to all three.
- *Your decision*: what the buyer can do at the store they have opened. The options depend on the result: review before checkout, skip, continue without an answer, or buy anyway.
- *What each store says*: one row per store with the product, the price and a status for each condition. Opening a row shows the store's own sentences first, with their address and the date read, then the status, then the assistant's reply.

Before checkout, one screen repeats the three answers and records the buyer's choice. "Go to checkout" opens the store's own checkout page in a new tab. The buyer enters their details and pays there.

**Merchant view**, the other tab on the right. The same rows from the store's side, written to the store owner: what your pages answer clearly, what is missing, and where to add it. It is built from the check, not from Shopify's data, and it shows nothing about the buyer's budget or choices.

## How it uses Shopify

Everything runs without a Shopify key or token. Each call carries the address of our own agent profile.

| Part | What we use it for |
|---|---|
| Global Catalog (`search_catalog`, `get_product`) | A live search with price, ships-to and availability filters and no store filter. `get_product` with the size selected confirms the size and gives the price and the checkout link. |
| UCP Ask (`ask_business`) | One question per condition per store, with the product attached. |
| Store profile (`/.well-known/ucp`) | Where a store's endpoint is and whether it offers Ask. |
| The catalog's checkout link | The page the buyer is sent to. GoodTerms never creates or completes a checkout. |
| Agent profile | A JSON file in `docs/`, served through jsDelivr. Stores fetch it on every call. |

Carts are not used. Prices are the catalog's, and shipping and tax appear on the store's checkout page.

Ask without credentials has a small shared limit. A check of six stores is 18 questions, and about 200 questions in an hour got this project blocked for 21 minutes. So every reply is saved with the time it was asked and reused for the same store, product and question for the rest of the day. When Shopify blocks Ask, the screen says so in plain words.

## Setup

You need:

- macOS or Linux
- [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 or newer for you)
- Node 20 or newer
- An Anthropic API key
- An internet connection

Then:

```sh
git clone https://github.com/Jagga-tech/Good-Terms.git
cd Good-Terms
uv sync
npm --prefix web install
cp .env.example .env
```

Open `.env` and put your key after `ANTHROPIC_API_KEY=`. Leave the other two lines empty to use the defaults. The file is ignored by git; keep the key out of every other file.

Start the app:

```sh
make dev
```

Open http://localhost:5173 and send Coco a message, for example "I need a queen mattress under $400".

### Settings

All optional, all in `.env` or the environment.

| Name | What it does | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | The model key. Required. | none |
| `LABELER_MODEL` | The model that labels sources. | `claude-sonnet-5-5` |
| `LABELER_EFFORT` | How hard the labeler thinks. | `low` |
| `COCO_MODEL` | The model behind Coco. | `claude-sonnet-5-5` |
| `LABEL_CACHE` | `refresh` labels everything again; `off` saves nothing. | `on` |
| `GOODTERMS_MODE` | `saved` switches on backup mode. | live |

### Backup mode

The app is live by default. Backup mode replays one saved live check and is switched on only by hand:

```sh
make backup
```

In backup mode a banner across the top says the results are saved and not live, and every row and price carries the date it was recorded. No store is contacted.

### Publishing the agent profile

The profile is `docs/agent-profile.json`. Shopify rejects a profile unless it is served with a `Cache-Control` header that includes `public`, which GitHub Pages does not send, so it is served through jsDelivr from this repository. The one address is in `docs/agent-profile.url`.

If you fork this, or change the profile:

1. Edit `docs/agent-profile.json`.
2. In the same commit, change the address in `docs/agent-profile.url` to point at a new tag, for example `@profile-2`.
3. Tag that commit with the same name and push the tag.
4. Run `make smoke`. It fails if the address and the file differ.

## Testing

```sh
make test
```

This runs the Python tests, then draws both halves of the screen from the API's own answers and tests those. It needs no key, calls no model and contacts no store.

The other checks call the model, and say so:

| Command | What it does | Contacts stores |
|---|---|---|
| `make smoke` | Four live Shopify calls with our own profile. | Yes, one Ask call |
| `make frozen` | Runs the labeler and the whole pipeline on saved page text and saved replies, scored against the answer key. | No |
| `make coco` | Ten scripted conversations with Coco, each checked line by line. | No |
| `make predemo` | Checks the profile, then runs the demo request live twice and reports timings and whether one store says yes to all three. It sends no new Ask question unless you add `--ask`. | Yes, page reads |
| `make live` | Five timed live checks. | Yes |

Space live runs out. They read real stores' pages, paced and within each store's `robots.txt`.

### What the fixtures are

`fixtures/` holds real saved data from November 15, 2026. Nothing in it is made up.

- **The answer key.** Page labels for ten stores: `rows_six_stores.json` and `labels_five_extra_stores.json`. The labels came from the research session with an AI assistant, and the project's owner signed off some of them. They were not checked by anyone independent. `make frozen` scores against it. One known difference is listed and left as it is: BonaNest's opened-returns row.
- **Saved page text.** A folder per store, `pages_*`, with the text of each page read and a report of every address tried.
- **Saved replies.** Store assistants' answers, word for word, with a label for each, including the "not excluded" cases the labeler must not call a yes.
- **Combining cases.** `combining_cases.json`: every row of the table that combines the two sources, and real cases from a live run with their exact sentences.
- **One saved search and one saved check.** `search_run_2026-11-15.json` and `live_check_2026-11-15.json`. Backup mode and Coco's scripted runs replay these.

## Limitations

- **A row is a dated statement, not a promise.** It says what a store's pages said on the day they were read. Nothing checks that the store honors it.
- **The labeler can be wrong.** It errs toward "doesn't say", and a wrong yes has not appeared in testing, but a wrong no or a missed yes can. A saved label stays until the page text changes.
- **The answer key was not checked independently.** Its labels came from a research session with an AI assistant, some of them signed off by the project's owner. Someone else should label the stores without seeing these.
- **One category, three conditions, one buyer.** The demo is a queen mattress under $400. The three conditions are fixed and the ZIP code is fixed at 94541.
- **The search is not pinned.** Stores and prices change between runs.
- **Prices are catalog prices.** Shipping and tax appear only on the store's checkout page.
- **No credentials means the lowest access tier.** Catalog and Ask traffic share small limits that Shopify does not guarantee. Fine for a demo, not for a launch.
- **One conversation at a time.** Coco's conversation lives in memory and a restart clears it.
- **Saved replies and labels live in one local file, `labels.db`.** A fresh clone asks and labels from scratch.
- **The typeface loads from Google Fonts.** Offline, the system font is used.
- **Terms.** Commercial use falls under Shopify's API terms, and one store in the fixtures reportedly bars automated access; that store is never read. Have both looked at before any public launch.
