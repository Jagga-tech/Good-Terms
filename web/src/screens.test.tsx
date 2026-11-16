import { renderToStaticMarkup } from 'react-dom/server'
import { expect, test } from 'vitest'
import raw from '../test-data.json'
import { Banner, Footer, NothingYet, Switch, parseRoute } from './App'
import type { Check, CheckStore, Row, Store, StoreName } from './api'
import { CheckView, ConditionRow, Decision, Review, StoreEntry } from './BuyersCheck'
import { Steps, Talk, doing } from './Coco'
import type { CocoState } from './api'
import { MerchantPanel, MerchantStore } from './MerchantView'

const data = raw as unknown as Record<string, Check> & {
  stores: StoreName[]
  merchant: Record<string, Store>
  checkout_links: Record<string, string>
}
const checks = ['final', 'replay_start', 'replay_replies', 'replay_partial', 'could_not_read', 'two_yes_one_assistant_only', 'ask_blocked']

const text = (markup: string) =>
  markup
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
const entry = (store: CheckStore, open = true) => text(renderToStaticMarkup(<StoreEntry store={store} open={open} to="/" />))
const entryMarkup = (store: CheckStore, open = true) => renderToStaticMarkup(<StoreEntry store={store} open={open} to="/" />)
const greenIn = (markup: string) => (markup.match(/class="[^"]*(?<![\w-])yes(?![\w-])[^"]*"/g) ?? []).length
const named = (check: Check, name: string) => check.stores.find((store) => store.name === name)!
const allRows = (name: string) => data[name].stores.flatMap((store) => store.rows.map((row) => ({ store, row })))

test('the store’s words come before the status on every row', () => {
  for (const name of checks)
    for (const { row } of allRows(name)) {
      const markup = renderToStaticMarkup(<ConditionRow row={row} />)
      const words = row.page_sentences[0]?.sentence ?? row.pages_text!
      const at = (needle: string) => text(markup).indexOf(needle)
      expect(at(words)).toBeGreaterThan(-1)
      expect(markup.indexOf('class="said"')).toBeLessThan(markup.indexOf('class="status'))
      expect(text(markup)).toContain(row.status_text)
      expect(at(words)).toBeLessThan(text(markup).lastIndexOf(row.status_text))
      if (row.page_status !== 'pending') expect(at(words)).toBeLessThan(at("From the store's pages"))
      if (row.assistant_reply) expect(at(words)).toBeLessThan(at("From the store's assistant"))
    }
})

test('all five result states render', () => {
  const seen = new Map<string, string>()
  for (const name of checks)
    for (const store of data[name].stores) {
      expect(entry(store, false)).toContain(store.result_text)
      seen.set(store.result, store.result_text)
    }
  expect([...seen.keys()].sort()).toEqual(['could_not_read', 'meets_all_3', 'not_answered_on_pages', 'says_no', 'still_reading'])
  expect(seen.get('could_not_read')).toBe("We couldn't read this store's pages")
})

test('while pages are being read: replies show, nothing green, no Meets all 3, no price gap, no decision button', () => {
  const check = data.replay_replies
  const markup = renderToStaticMarkup(<CheckView check={check} openStore="novillashop.com" onReplay={() => {}} />)
  expect(greenIn(markup)).toBe(0)
  expect(text(markup)).not.toContain('Meets all 3')
  expect(markup).not.toContain('class="gap"')
  expect(markup.match(/<button/g)).toHaveLength(1)
  for (const store of check.stores) {
    const open = entry(store)
    expect(open).toContain("Still reading this store's pages")
    for (const row of store.rows) expect(open).toContain(row.assistant_reply!)
  }
  for (const store of data.replay_start.stores)
    for (const row of store.rows) {
      expect(row.assistant_reply).toBeNull()
      expect(entry(store)).not.toContain("From the store's assistant")
    }
})

test('a store has no green until its own pages are read, and its rows update in place', () => {
  const stillReading = data.replay_partial.stores.filter((store) => !store.progress!.pages_read)
  const finished = data.replay_partial.stores.filter((store) => store.progress!.pages_read)
  expect(stillReading.length).toBeGreaterThan(0)
  expect(finished.length).toBeGreaterThan(0)
  for (const store of stillReading) expect(greenIn(entryMarkup(store))).toBe(0)
  const skeleton = (store: CheckStore) => entryMarkup(store).match(/data-condition="[^"]+"|class="(said|status|marks|detail)/g)
  const order = (check: Check) => check.stores.map((store) => store.domain)
  expect(order(data.replay_partial)).toEqual(order(data.replay_replies))
  for (const store of data.replay_replies.stores) {
    const after = data.final.stores.find((s) => s.domain === store.domain)!
    expect(skeleton(store)).toEqual(skeleton(after))
  }
  expect(renderToStaticMarkup(<CheckView check={data.final} openStore={null} />)).toContain('class="gap"')
})

test('green appears only on a yes found on the store’s pages', () => {
  for (const name of checks)
    for (const store of data[name].stores) {
      const pageYes = store.rows.filter((row) => row.status_shown === 'yes')
      for (const row of pageYes) expect(row.page_status).toBe('yes')
      expect(greenIn(entryMarkup(store, false))).toBe(pageYes.length)
      expect(greenIn(entryMarkup(store, true))).toBe(pageYes.length * 2)
    }
})


test('an assistant-only yes shows its exact words and no green', () => {
  const napqueen = named(data.final, 'NapQueen')
  const row = napqueen.rows[2]
  expect(row.status_shown).toBe('assistant_only_yes')
  const markup = renderToStaticMarkup(<ConditionRow row={row} />)
  expect(text(markup)).toContain("Store's assistant says yes. Not found on its pages.")
  expect(markup).toContain('class="status assistant_only_yes"')
  expect(greenIn(markup)).toBe(0)
  expect(entry(napqueen, false)).toContain("Store's assistant says yes. Not found on its pages.")
  expect(greenIn(entryMarkup(napqueen))).toBe(0)
})

test('two page yeses and one assistant-only yes show the unanswered result, not Meets all 3', () => {
  const store = named(data.two_yes_one_assistant_only, 'SweetNight')
  expect(store.rows.map((row) => row.status_shown)).toEqual(['yes', 'yes', 'assistant_only_yes'])
  expect(entry(store)).toContain('1 of your conditions is not answered on its pages. That is not a yes.')
  expect(entry(store)).not.toContain('Meets all 3')
})

test('a no that comes only from the store’s assistant says so, with the pages-not-read note', () => {
  for (const name of ['Dwellinhaus', 'Lee Furniture, NC']) {
    const open = entry(named(data.final, name))
    expect(open).toContain("Store's assistant says no.")
    expect(open).toContain('Pages were not read in this saved run.')
    expect(open).toContain("From the store's assistant")
  }
})

test('the price gap line is the API’s, and its two prices are the prices shown', () => {
  const check = data.final
  const page = text(renderToStaticMarkup(<CheckView check={check} openStore={null} />))
  expect(page).toContain(check.price_gap!.text)
  const [cheapest, meeting, difference] = [...check.price_gap!.text.matchAll(/\$([\d,]+)\.(\d\d)/g)].map((m) => Number(m[1].replace(',', '') + m[2]))
  expect(entry(named(check, 'NapQueen'), false)).toContain('$229.00')
  expect(named(check, 'NapQueen').offer!.price_cents).toBe(cheapest)
  expect(named(check, 'Novilla').offer!.price_cents).toBe(meeting)
  expect(meeting - cheapest).toBe(difference)
})

test('both screens show the same sentence, reply, link and date for the same row', () => {
  const latest = new Set(data.latest.stores.map((store) => store.domain))
  const shown = [...data.latest.stores, ...data.final.stores.filter((store) => !latest.has(store.domain))]
  expect(shown.length).toBe(Object.keys(data.merchant).length)
  for (const store of shown) {
    const buyer = entryMarkup(store)
    const merchant = renderToStaticMarkup(<MerchantStore store={data.merchant[store.domain]} />)
    expect(data.merchant[store.domain].rows).toEqual(store.rows)
    for (const row of store.rows)
      for (const screen of [buyer, merchant]) {
        for (const sentence of row.page_sentences) {
          expect(text(screen)).toContain(`“${sentence.sentence}”`)
          expect(screen).toContain(`href="${sentence.url}"`)
          expect(text(screen)).toContain(`read ${row.date_read}`)
        }
        expect(text(screen)).toContain(row.assistant_reply!)
        expect(text(screen)).toContain(`asked ${row.reply_time}`)
      }
  }
})

const quoted = (store: Store) =>
  store.rows.flatMap((row: Row) => [row.assistant_reply!, row.question, ...row.page_sentences.flatMap((s) => [s.sentence, s.heading ?? '', s.url])])

test('Merchant view speaks to the merchant, in order, with no counts, prices or buyer details', () => {
  const names = [...data.final.stores, ...data.latest.stores]
  for (const store of [...Object.values(data.merchant), ...data.final.stores, ...data.decided.stores]) {
    const markup = renderToStaticMarkup(<MerchantStore store={store} />)
    let own = text(markup)
    for (const piece of quoted(store).filter(Boolean).sort((a, b) => b.length - a.length)) own = own.split(piece).join('')
    own = own.replace(/[\w.-]+\.com\S*/g, '').replace(/\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?/g, '')
    const sold = 'offer' in store ? (store as CheckStore).offer : null
    if (sold) for (const piece of [sold.product_title, sold.variant_labels.join(' / '), sold.price_text]) own = own.split(piece).join('')
    own = own.replace(/Your pages (say yes to|answer) all 3 of this buyer's conditions( clearly: [\w ]+?(?= What| Your| The| $))?/, '').replace(/Your pages leave \d of this buyer's conditions unanswered/, '').replace(/\(\/[\w/-]+\)|\/(pages|policies|products)\/[\w-]+/g, '')
    expect(own).not.toMatch(/this store|the merchant|buyer's|budget|\$|\d/i)
    expect(own.replace('Sales channels', '')).not.toMatch(/\b(win|wins|winning|won|lose|loses|losing|lost|beat|ahead|behind|rank|best|worse|competitor|sales|revenue|conversion|chose|skipped)\b/i)
    expect(own).toMatch(/your store/i)
    const order = ['What your pages answer clearly', 'What is missing'].map((h) => own.indexOf(h))
    expect(order[0]).toBeGreaterThan(-1)
    expect(order[0]).toBeLessThan(order[1])
    const adds = own.indexOf('Where to add it')
    if (adds > -1) expect(adds).toBeGreaterThan(order[1])
    expect(own.split('Settings, then Policies').length).toBe(adds > -1 ? 2 : 1)
    expect(own.split('Sales channels, Agentic, then Knowledge base').length).toBe(adds > -1 ? 2 : 1)
    for (const other of names) if (other.domain !== store.domain) expect(own).not.toContain(other.name!)
    expect(greenIn(markup)).toBe(0)
  }
})

test('Merchant view follows the rules for each kind of row', () => {
  const view = (check: Check, domain: string) =>
    text(renderToStaticMarkup(<MerchantStore store={check.stores.find((store) => store.domain === domain)!} />))
  const novilla = view(data.final, 'novillashop.com')
  expect(novilla).toContain("Your pages say yes to all 3 of this buyer's conditions")
  expect(novilla).toContain('Your pages answer sale-item returns clearly. The answer is: yes.')
  expect(novilla).toContain('This answer sits on a sale page (/pages/black-friday-sale) that may change when the sale ends. Add it to your return policy so it stays.')
  expect(novilla).toContain('Nothing is missing.')
  expect(novilla).toContain('Where to add it')

  const napqueen = view(data.final, 'napqueensleep.com')
  expect(napqueen).toContain("Your store's assistant says yes to sale-item returns, but your pages don't say it. You can add it in your return policy.")
  expect(napqueen).toContain('Buyers who ask about free return shipping get no answer from your pages. You can add it in your return policy.')
  expect(napqueen).not.toMatch(/Your pages (answer|say yes to) all/)
  expect(napqueen).toContain("Your pages leave 3 of this buyer's conditions unanswered")

  const bedstory = view(data.final, 'bedstory.com')
  expect(bedstory).toContain('Your pages /pages/return-policy and /pages/365-night-home-trial say different things about free return shipping. Make them agree.')
  expect(bedstory).toContain('Two sentences on your page /pages/365-night-home-trial say different things about opened returns. Make them agree.')

  expect(bedstory).toContain('Your pages say different things about opened returns, free return shipping and sale-item returns')
  expect(view(data.latest, 'napqueensleep.com')).toContain("Your pages leave 3 of this buyer's conditions unanswered")
  for (const check of [data.final, data.latest])
    for (const store of check.stores) expect(renderToStaticMarkup(<MerchantStore store={store} />)).toMatch(/<p class="headline">[^<]+<\/p>/)
  const lee = view(data.final, 'leefurniture.com')
  expect(lee).toContain("Your store's assistant says no to opened returns, and your pages don't say either way.")
  expect(lee).toContain('Pages were not read in this saved run.')

  const clearNo = view(data.latest, 'comformattress.com')
  expect(clearNo).toContain("Your pages answer all 3 of this buyer's conditions clearly: 3 no")
  expect(clearNo).not.toContain('say yes to all')
  const yesStore = data.final.stores.find((store) => store.domain === 'novillashop.com')!
  const noStore = data.latest.stores.find((store) => store.domain === 'comformattress.com')!
  const mixed = { ...yesStore, rows: [yesStore.rows[0], yesStore.rows[1], noStore.rows[2]] }
  expect(text(renderToStaticMarkup(<MerchantStore store={mixed} />))).toContain("Your pages answer all 3 of this buyer's conditions clearly: 2 yes and 1 no")
  expect(clearNo).toContain('Your pages answer opened returns clearly. The answer is: no.')
  expect(clearNo).not.toMatch(/You can add|Add it to|Make them agree|Where to add it|change/i)
})

test('one view at a time: a switch for Buyer’s check and Merchant view, which opens on no store', () => {
  const buyer = parseRoute(new URL('http://app/check/1?store=novillashop.com'))
  expect(buyer).toEqual({ screen: 'shop', id: '1', tab: 'buyer', store: 'novillashop.com', review: null, merchantStore: null })
  expect(parseRoute(new URL('http://app/check/1?view=merchant&m=bedstory.com'))).toMatchObject({ tab: 'merchant', merchantStore: 'bedstory.com' })
  expect(parseRoute(new URL('http://app/merchant'))).toEqual({ screen: 'none' })
  const toggle = renderToStaticMarkup(<Switch tab="merchant" buyer="/check/1" merchant="/check/1?view=merchant" />)
  expect([...toggle.matchAll(/<a[^>]*>([^<]+)</g)].map((m) => m[1].replace(/&#x27;/g, "'"))).toEqual(["Buyer's check", 'Merchant view'])
  expect(toggle.match(/aria-current="page"/g)).toHaveLength(1)
  const check = renderToStaticMarkup(<CheckView check={data.final} openStore="novillashop.com" />)
  const headings = [...check.matchAll(/<h2>([^<]+)</g)].map((m) => m[1])
  expect(headings).toEqual(['Stores checked', 'Your decision', 'What each store says'])
  expect(text(check)).not.toMatch(/Shopify admin|your return policy|your pages|Merchant view/i)
  const unpicked = renderToStaticMarkup(<MerchantPanel check={data.decided} domain={null} />)
  expect(text(unpicked)).toContain("What a merchant would see. Built from this check, not from Shopify's data.")
  expect(text(unpicked)).toContain('Viewing as')
  expect(unpicked).toContain('<select')
  expect(unpicked).not.toContain('<article')
  for (const store of data.decided.stores) expect(text(unpicked)).toContain(store.name!)
  const picked = text(renderToStaticMarkup(<MerchantPanel check={data.decided} domain="napqueensleep.com" />))
  expect(picked).toContain('Your store: NapQueen')
  expect(picked).not.toMatch(/You chose|under \$400|94541|budget/)
  expect(picked).toContain('The product that was checked')
  expect(picked).toContain('$229.00')
  const reading = text(renderToStaticMarkup(<MerchantPanel check={data.replay_replies} domain="novillashop.com" />))
  expect(reading).toContain("Still reading this store's pages")
  expect(reading).not.toContain('Your store:')
  expect(text(renderToStaticMarkup(<MerchantPanel check={null} domain={null} />))).toContain('Nothing is being checked yet.')
})



test('every screen has the footer', () => {
  expect(text(renderToStaticMarkup(<Footer />)).trim()).toBe('Prototype. Not affiliated with Shopify.')
})

test('a blocked Ask is said on screen in plain words, on both screens', () => {
  const store = named(data.ask_blocked, 'SweetNight')
  const said = store.rows[0].assistant_text!
  expect(said).toMatch(/^Shopify's limit on questions to store assistants was reached/)
  expect(entry(store)).toContain(said)
  expect(entry(store)).toContain("From the store's assistant")
  const merchant = text(renderToStaticMarkup(<MerchantStore store={store} />))
  expect(merchant).toContain(said)
  expect(merchant).not.toMatch(/this store|the merchant/i)
})

const coco: CocoState = {
  conditions_confirmed: true,
  conditions: [
    { id: 'opened_returns', label: 'Opened returns', definition: 'the item can be returned after it has been opened and used.' },
    { id: 'free_return_shipping', label: 'Free return shipping', definition: 'the buyer pays nothing to send it back.' },
    { id: 'sale_item_returns', label: 'Sale-item returns', definition: 'an item bought at a sale price can still be returned.' },
  ],
  zip: '94541',
  backup_mode: false,
  lines: [],
  check_id: null,
  check_done: false,
  busy: false,
}

test('the chat starts empty: only the header and the message box, and Coco says nothing first', () => {
  const markup = renderToStaticMarkup(<Talk state={coco} lines={[]} working={false} />)
  expect(text(markup).replace(/\s+/g, ' ').trim()).toBe('Coco, your agent Message Coco Send')
  expect(markup).toMatch(/<div class="thread"[^>]*><\/div>/)
  expect(markup).not.toMatch(/What do you need|Remembers|Looks right|Is that right/)
  expect(markup.match(/<input/g)).toHaveLength(1)
})





test('Coco is one chat card: header, messages, step lines, a status line and one message box', () => {
  const lines = [
    { who: 'you' as const, text: 'I need a queen mattress under $400' },
    { who: 'steps' as const, steps: [
      { text: "Searched Shopify's catalog · 6 stores", done: true },
      { text: "Asked each store's assistant · 18 answers", done: true },
      { text: 'Reading store pages · 4 of 6', done: false },
    ] },
    { who: 'coco' as const, text: "I searched for a Queen and found 6 stores. Buyer's Check is open." },
  ]
  const markup = renderToStaticMarkup(<Talk state={coco} lines={lines} working={false} />)
  const page = text(markup)
  expect(markup).toMatch(/^<section class="card chat">/)
  expect(page).toContain('Coco, your agent')
  expect(page).not.toContain('Remembers')
  expect(markup).toContain('class="mine"')
  expect(markup).toContain('class="theirs"')
  expect(markup).not.toMatch(/avatar|typing|<img|<svg|…|\.\.\./i)
  expect(page.indexOf(lines[0].text)).toBeLessThan(page.indexOf('Searched Shopify'))
  expect(markup).toContain('placeholder="Message Coco"')
  expect(markup.indexOf('class="thread"')).toBeLessThan(markup.indexOf('<form'))
  expect(markup).toContain('<p class="small doing">Reading store pages · 4 of 6</p>')
  expect(doing(lines.slice(0, 1), true)).toBe('Working on your message')
  expect(doing(lines.slice(0, 1), false)).toBeNull()
  for (const condition of coco.conditions) expect(page).not.toContain(condition.label)
  const check = text(renderToStaticMarkup(<CheckView check={data.final} openStore={null} />))
  expect(check.indexOf('Your conditions:')).toBeLessThan(check.indexOf('What each store says'))
  expect(greenIn(markup)).toBe(0)
  expect(parseRoute(new URL('http://app/'))).toMatchObject({ screen: 'shop', id: null, tab: 'buyer' })
})


test('a step line shows a tick only when that step is done', () => {
  const markup = renderToStaticMarkup(<Steps steps={[{ text: 'Searched Shopify’s catalog · 6 stores', done: true }, { text: 'Reading store pages · 4 of 6', done: false }]} />)
  expect(markup.match(/✓/g)).toHaveLength(1)
  expect(markup.indexOf('✓')).toBeLessThan(markup.indexOf('6 stores'))
  expect(text(markup)).toContain('Reading store pages · 4 of 6 (in progress)')
})


test('one price line above the list, and no price basis on any row', () => {
  for (const name of ['final', 'latest', 'replay_replies']) {
    const page = text(renderToStaticMarkup(<CheckView check={data[name]} openStore={data[name].stores[0].domain} />))
    expect(page.split("Prices are from Shopify's catalog. Shipping and tax are added at checkout.").length).toBe(2)
    expect(page).not.toMatch(/catalog price/i)
  }
})

test('a card whose store’s pages disagree says so on the card itself', () => {
  const closed = entry(named(data.latest, 'BedStory'), false)
  expect(closed).toContain('Its pages say different things')
  expect(entry(named(data.latest, 'Novilla'), false)).not.toContain('Its pages say different things')
  expect(text(renderToStaticMarkup(<MerchantStore store={named(data.latest, 'BedStory')} />))).not.toContain('Its pages say')
})

test('decision buttons follow the result, and none show while pages are being read', () => {
  const card = (check: Check, store: CheckStore) => renderToStaticMarkup(<Decision check={check} store={store} />)
  const buttons = (check: Check, store: CheckStore) =>
    [...card(check, store).matchAll(/<(?:button|a) class="(primary|second)"[^>]*>([^<]+)</g)].map((m) => `${m[1]}:${m[2].replace(/&#x27;/g, "'")}`)
  expect(buttons(data.latest, named(data.latest, 'Novilla'))).toEqual(['primary:Review before checkout'])
  expect(buttons(data.latest, named(data.latest, 'Comformattress'))).toEqual(['primary:Skip this store', 'second:Buy anyway'])
  expect(buttons(data.latest, named(data.latest, 'NapQueen'))).toEqual(['second:Skip this store', 'second:Continue without an answer'])
  const unreadable = named(data.could_not_read, 'SweetNight')
  expect(unreadable.result).toBe('could_not_read')
  const withSite = { ...unreadable, actions: [{ action: 'skip', label: 'Skip this store', first: false }, { action: 'open_site', label: "Open the store's site", first: false }] }
  expect(buttons(data.could_not_read, withSite)).toEqual(['second:Skip this store', "second:Open the store's site"])
  for (const name of ['replay_start', 'replay_replies'])
    for (const store of data[name].stores) {
      expect(buttons(data[name], store)).toEqual([])
      expect(text(card(data[name], store))).toContain("Still reading this store's pages")
    }
  expect(text(card(data.decided, named(data.decided, 'Dwellinhaus')))).toContain('You skipped this store.')
  const none = text(renderToStaticMarkup(<Decision check={data.decided} store={null} />))
  expect(none).toContain('Pick a store below to see what it says and decide.')
  expect(none).toContain('NapQueen: You chose to continue without an answer.')
  expect(card(data.latest, named(data.latest, 'Novilla'))).not.toContain('checkout"')
})


test('the before-checkout screen repeats the three answers with the date and records the choice', () => {
  const store = named(data.decided, 'NapQueen')
  const link = data.checkout_links['napqueensleep.com']
  const markup = renderToStaticMarkup(<Review check={data.decided} store={store} link={link} />)
  const page = text(markup)
  for (const row of store.rows) {
    expect(page).toContain(row.condition_label)
    expect(page).toContain(row.status_text)
  }
  expect(page).toContain('You chose to continue without an answer.')
  expect(page).toContain(`Recorded ${store.decision!.time}.`)
  expect(page).toContain("The final total, with shipping and tax, appears on the store's own checkout page.")
  expect(page).toContain(store.result_text)
  expect(markup).not.toMatch(/<input|<form|<select|<textarea/)
  expect(greenIn(markup)).toBe(0)

  const novilla = named(data.decided, 'Novilla')
  const good = renderToStaticMarkup(<Review check={data.decided} store={novilla} link={data.checkout_links['novillashop.com']} />)
  for (const row of novilla.rows) {
    expect(text(good)).toContain(`“${row.page_sentences[0].sentence}”`)
    expect(text(good)).toContain(`read ${row.date_read}`)
    expect(good.indexOf(row.page_sentences[0].url)).toBeLessThan(good.lastIndexOf(`>${row.status_text}<`))
  }
  const anchor = good.match(/<a class="primary checkout"[^>]*>Go to checkout<\/a>/)![0]
  expect(good.match(/class="[^"]*checkout[^"]*"/g)).toHaveLength(1)
  expect(anchor).toContain(`href="${data.checkout_links['novillashop.com'].replace(/&/g, '&amp;')}"`)
  expect(anchor).toContain('target="_blank"')
  expect(anchor).toContain('rel="noopener noreferrer"')
  expect(data.checkout_links['novillashop.com']).toMatch(/^https:\/\/www\.novillashop\.com\/buy\/\d+:1/)
  const noLink = renderToStaticMarkup(<Review check={data.decided} store={named(data.decided, 'Dwellinhaus')} link={null} />)
  expect(noLink).not.toContain('Go to checkout')
})

test('with nothing being checked, the right side says so', () => {
  const page = text(renderToStaticMarkup(<NothingYet backup={false} />))
  expect(page).toContain('Nothing is being checked yet.')
  expect(page).not.toMatch(/saved check/i)
  expect(text(renderToStaticMarkup(<NothingYet backup={true} />))).toContain('Open the saved check from 2026-11-15')
})

test('each store row shows the catalog’s own product photo, or a plain letter when there is none', () => {
  const withPhoto = named(data.latest, 'Novilla')
  const row = entryMarkup(withPhoto, false)
  const image = row.match(/<img[^>]*>/)![0]
  expect(image).toContain(`src="${withPhoto.offer!.image_url}"`)
  expect(withPhoto.offer!.image_url).toMatch(/^https:\/\/cdn\.shopify\.com\//)
  expect(image).toContain('width="72"')
  expect(row.indexOf('<img')).toBeLessThan(row.indexOf(withPhoto.offer!.product_title))
  expect(row.indexOf(withPhoto.offer!.product_title)).toBeLessThan(row.indexOf(withPhoto.offer!.price_text))
  expect(text(row)).toContain('Novilla')
  const without = named(data.final, 'Novilla')
  const plain = entryMarkup(without, false)
  expect(plain).not.toContain('<img')
  expect(plain).toContain(`<span class="photo letter" aria-hidden="true">${without.offer!.product_title.charAt(0)}</span>`)
  const merchant = renderToStaticMarkup(<MerchantStore store={withPhoto} />)
  expect(merchant.indexOf('The product that was checked')).toBeLessThan(merchant.indexOf('What your pages answer clearly'))
  expect(merchant).toContain(`src="${withPhoto.offer!.image_url}"`)
  expect(text(merchant)).toContain(withPhoto.offer!.price_text)
})

test('backup mode cannot be mistaken for live: a banner, and the recorded date on every row and price', () => {
  const banner = text(renderToStaticMarkup(<Banner date="2026-11-15" />))
  expect(banner).toContain('Backup mode.')
  expect(banner).toContain('saved results from 2026-11-15')
  expect(banner).toContain('This is not a live check.')
  const saved = data.latest
  expect(saved.saved_on).toBe('2026-11-15')
  for (const store of saved.stores) {
    const row = text(renderToStaticMarkup(<StoreEntry store={store} open={false} to="/" recorded={saved.saved_on} />))
    expect(row).toContain(`${store.offer!.price_text} recorded 2026-11-15`)
    expect(row.split('recorded 2026-11-15').length).toBe(1 + 1 + store.rows.length)
  }
  const page = text(renderToStaticMarkup(<CheckView check={saved} openStore={null} />))
  expect(page).toContain('Saved rows from 2026-11-15.')
  expect(page.split('recorded 2026-11-15').length).toBe(1 + 6 * 4)
  const live = { ...saved, saved_on: null }
  expect(text(renderToStaticMarkup(<CheckView check={live} openStore={null} />))).not.toMatch(/recorded|Saved rows/)
})

test('trouble reaching Coco is said in the chat card, in place of the status line', () => {
  const markup = renderToStaticMarkup(<Talk state={coco} lines={[]} working={true} trouble="Your message did not reach Coco. Try again." />)
  expect(text(markup)).toContain('Your message did not reach Coco. Try again.')
  expect(markup).toContain('role="alert"')
  expect(text(markup)).not.toContain('Working on your message')
})
