import { renderToStaticMarkup } from 'react-dom/server'
import { expect, test } from 'vitest'
import raw from '../test-data.json'
import { Footer, parseRoute } from './App'
import type { Check, CheckStore, Row, Store, StoreName } from './api'
import { CheckView, ConditionRow, StoreEntry } from './BuyersCheck'
import { MerchantPage, MerchantStore } from './MerchantView'

const data = raw as unknown as Record<string, Check> & { stores: StoreName[]; merchant: Record<string, Store> }
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
      if (row.status_text !== row.pages_text) expect(at(words)).toBeLessThan(text(markup).lastIndexOf(row.status_text))
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
      expect(greenIn(entryMarkup(store, false))).toBe(pageYes.length * 2)
      expect(greenIn(entryMarkup(store, true))).toBe(pageYes.length * 4)
    }
})

test('an assistant-only yes shows its exact words and no green', () => {
  const napqueen = named(data.final, 'NapQueen')
  const row = napqueen.rows[2]
  expect(row.status_shown).toBe('assistant_only_yes')
  const markup = renderToStaticMarkup(<ConditionRow row={row} />)
  expect(text(markup)).toContain("Store's assistant says yes. Not found on its pages.")
  expect(markup).toContain('class="mark assistant_only_yes"')
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
  expect(entry(named(check, 'NapQueen'), false)).toContain('$229.00 catalog price')
  expect(named(check, 'NapQueen').offer!.price_cents).toBe(cheapest)
  expect(named(check, 'Novilla').offer!.price_cents).toBe(meeting)
  expect(meeting - cheapest).toBe(difference)
})

test('both screens show the same sentence, reply, link and date for the same row', () => {
  for (const store of data.final.stores) {
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

test('Merchant View speaks to the merchant, in order, with no counts, prices or buyer details', () => {
  for (const store of Object.values(data.merchant)) {
    const markup = renderToStaticMarkup(<MerchantStore store={store} />)
    let own = text(markup)
    for (const piece of quoted(store).filter(Boolean)) own = own.split(piece).join('')
    own = own.replace(/[\w.-]+\.com\S*/g, '').replace(/\d{4}-\d{2}-\d{2}/g, '')
    expect(own).not.toMatch(/this store|the merchant|buyer's|budget|\$|\d/i)
    expect(own).toMatch(/your store/i)
    const order = ['What your pages answer clearly', 'What is missing', 'Where to add it'].map((h) => own.indexOf(h))
    expect(order[0]).toBeGreaterThan(-1)
    expect(order).toEqual([...order].sort((a, b) => a - b))
    expect(own.split('Settings, then Policies').length).toBe(2)
    expect(own.split('Sales channels, Agentic, then Knowledge base').length).toBe(2)
    for (const other of data.final.stores)
      if (other.domain !== store.domain) expect(own).not.toContain(other.name!)
    expect(greenIn(markup)).toBe(0)
  }
})

test('Merchant View puts each row under the right heading', () => {
  const lines = (domain: string) => text(renderToStaticMarkup(<MerchantStore store={data.merchant[domain]} />))
  expect(lines('novillashop.com')).toContain('Your pages answer sale-item returns clearly. The answer is: yes.')
  expect(lines('novillashop.com')).toContain('Nothing is missing.')
  expect(lines('napqueensleep.com')).toContain("Your store's assistant says yes to sale-item returns, but your pages don't say it. You can add it in your return policy.")
  expect(lines('napqueensleep.com')).toContain('Buyers who ask about free return shipping get no answer from your pages. You can add it in your return policy.')
  expect(lines('bedstory.com')).toContain('Your pages say two different things about free return shipping.')
  expect(lines('leefurniture.com')).toContain("Your store's assistant says no to opened returns, and your pages don't say either way.")
  expect(lines('leefurniture.com')).toContain('Pages were not read in this saved run.')
})

test('the two screens keep separate state, and Merchant View does not open on the buyer’s store', () => {
  const buyer = parseRoute(new URL('http://app/check/1?store=novillashop.com'))
  expect(buyer).toEqual({ screen: 'buyer', id: '1', store: 'novillashop.com' })
  expect(parseRoute(new URL('http://app/merchant'))).toEqual({ screen: 'merchant', store: null })
  const lookup = renderToStaticMarkup(<MerchantPage stores={data.stores} store={null} domain={null} />)
  expect(lookup).not.toContain('<article')
  expect(text(lookup)).toContain('Or pick one:')
  const check = text(renderToStaticMarkup(<CheckView check={data.final} openStore="novillashop.com" />))
  expect(check).not.toMatch(/Shopify admin|your return policy|your pages/i)
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
