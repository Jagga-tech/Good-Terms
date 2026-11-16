import type { Check, CheckStore, Row, Sentence, Store } from './api'
import { Reply, StoreWords } from './Evidence'
import { Link, withParam } from './router'

const SALE_PAGE = /sale|deal|promo|black-friday|cyber|clearance|outlet/i
const topic = (row: Row) => row.condition_label.toLowerCase()
const page = (url: string) => new URL(url).pathname
const saysYes = (sentence: Sentence) => sentence.label === 'yes'
const against = (sentence: Sentence) => sentence.label === 'no' || sentence.label === 'unclear'

type Kind = 'clear' | 'disagree' | 'differs' | 'missing'

export function kindOf(row: Row): Kind {
  if (row.page_sentences.some(saysYes) && row.page_sentences.some(against)) return 'disagree'
  if (!['yes', 'no'].includes(row.page_status) || row.page_sentences.length === 0) return 'missing'
  return row.contradiction ? 'differs' : 'clear'
}

export function saleTip(row: Row) {
  const yes = row.page_sentences.filter(saysYes)
  if (row.page_status !== 'yes' || yes.length === 0 || !yes.every((sentence) => SALE_PAGE.test(page(sentence.url)))) return null
  return `This answer sits on a sale page (${page(yes[0].url)}) that may change when the sale ends. Add it to your return policy so it stays.`
}

export function lineFor(row: Row) {
  const kind = kindOf(row)
  if (kind === 'clear') return `Your pages answer ${topic(row)} clearly.`
  if (kind === 'disagree') {
    const first = page(row.page_sentences.find(saysYes)!.url)
    const second = page(row.page_sentences.find(against)!.url)
    return first === second
      ? `Two sentences on your page ${first} say different things about ${topic(row)}. Make them agree.`
      : `Your pages ${first} and ${second} say different things about ${topic(row)}. Make them agree.`
  }
  if (kind === 'differs')
    return `Your pages and your store's assistant say different things about ${topic(row)}. Make them agree.`
  if (row.assistant_status === 'yes')
    return `Your store's assistant says yes to ${topic(row)}, but your pages don't say it. You can add it in your return policy.`
  if (row.assistant_status === 'no')
    return `Your store's assistant says no to ${topic(row)}, and your pages don't say either way. You can add your answer in your return policy.`
  return `Buyers who ask about ${topic(row)} get no answer from your pages. You can add it in your return policy.`
}

export function headline(store: Store) {
  const rows = store.rows
  if (rows.length === 0 || !rows.every((row) => kindOf(row) === 'clear')) return null
  const yes = rows.filter((row) => row.page_status === 'yes').length
  const no = rows.length - yes
  if (no === 0) return `Your pages say yes to all ${rows.length} of this buyer's conditions`
  const counts = [yes > 0 ? `${yes} yes` : '', `${no} no`].filter(Boolean).join(' and ')
  return `Your pages answer all ${rows.length} of this buyer's conditions clearly: ${counts}`
}

function Evidence({ row }: { row: Row }) {
  return (
    <>
      <p className="asked">Your buyers ask: “{row.question}”</p>
      {row.page_sentences.map((sentence) => (
        <StoreWords key={sentence.sentence + sentence.url} sentence={sentence} date={row.date_read} />
      ))}
      <Reply row={row} label={row.assistant_reply ? "Your store's assistant says" : "Your store's assistant"} />
    </>
  )
}

export function MerchantStore({ store }: { store: Store }) {
  const clear = store.rows.filter((row) => kindOf(row) === 'clear')
  const open = store.rows.filter((row) => kindOf(row) !== 'clear')
  const note = store.rows.find((row) => row.read_note)?.read_note
  const tips = clear.filter(saleTip)
  return (
    <article className="merchant" data-store={store.domain}>
      <h2>Your store: {store.name}</h2>
      {note && <p className="plain">{note}</p>}
      {headline(store) && <p className="headline">{headline(store)}</p>}
      <section>
        <h3>What your pages answer clearly</h3>
        {clear.length === 0 && <p>Nothing yet.</p>}
        {clear.map((row) => (
          <div key={row.condition} className="condition" data-condition={row.condition}>
            <p className="line">
              {lineFor(row)} The answer is: {row.status_text.toLowerCase()}.
            </p>
            {saleTip(row) && <p className="tip">{saleTip(row)}</p>}
            <Evidence row={row} />
          </div>
        ))}
      </section>
      <section>
        <h3>What is missing</h3>
        {open.length === 0 && <p>Nothing is missing.</p>}
        {open.map((row) => (
          <div key={row.condition} className="condition" data-condition={row.condition}>
            <p className="line">{lineFor(row)}</p>
            <Evidence row={row} />
          </div>
        ))}
      </section>
      {(open.length > 0 || tips.length > 0) && (
        <section>
          <h3>Where to add it</h3>
          <p>Your return policy: in your Shopify admin, go to Settings, then Policies.</p>
          <p>
            The knowledge base your store's assistant reads: in your Shopify admin, go to Sales channels, Agentic, then
            Knowledge base.
          </p>
        </section>
      )}
    </article>
  )
}

export function MerchantBox({ check, domain }: { check: Check | null; domain: string | null }) {
  const store: CheckStore | undefined = check?.stores.find((entry) => entry.domain === domain)
  return (
    <section className="box">
      <h1>Merchant view: what a store would see</h1>
      {!check && <p className="plain">Nothing is being checked yet.</p>}
      {check && (
        <p className="pick">
          Demo: view as{' '}
          {check.stores.map((entry) => (
            <Link key={entry.domain} to={withParam('m', entry.domain)} current={entry.domain === domain}>
              {entry.name}
            </Link>
          ))}
        </p>
      )}
      {store && store.progress?.pages_read && <MerchantStore store={store} />}
      {store && !store.progress?.pages_read && <p className="plain">{store.result_text}</p>}
    </section>
  )
}
