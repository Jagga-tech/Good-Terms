import { useEffect, useState, type FormEvent } from 'react'
import { getStore, getStores, type Row, type Store, type StoreName } from './api'
import { Reply, StoreWords } from './Evidence'
import { Link, navigate } from './router'

const topic = (row: Row) => row.condition_label.toLowerCase()
const isClear = (row: Row) =>
  row.page_sentences.length > 0 && ['yes', 'no'].includes(row.page_status) && !row.contradiction

function missingLine(row: Row) {
  const pagesAnswer = ['yes', 'no'].includes(row.page_status)
  if (row.page_sentences.length > 1 && row.contradiction)
    return `Your pages say two different things about ${topic(row)}. You can settle it in your return policy.`
  if (pagesAnswer && row.contradiction)
    return `Your pages and your store's assistant say different things about ${topic(row)}. You can settle it in your return policy.`
  if (row.assistant_status === 'yes')
    return `Your store's assistant says yes to ${topic(row)}, but your pages don't say it. You can add it in your return policy.`
  if (row.assistant_status === 'no')
    return `Your store's assistant says no to ${topic(row)}, and your pages don't say either way. You can add your answer in your return policy.`
  return `Buyers who ask about ${topic(row)} get no answer from your pages. You can add it in your return policy.`
}

function Evidence({ row }: { row: Row }) {
  return (
    <>
      <p className="asked">Your buyers ask: “{row.question}”</p>
      {row.page_sentences.map((sentence) => (
        <StoreWords key={sentence.sentence} sentence={sentence} date={row.date_read} />
      ))}
      <Reply row={row} label="Your store's assistant says" />
    </>
  )
}

export function MerchantStore({ store }: { store: Store }) {
  const clear = store.rows.filter(isClear)
  const missing = store.rows.filter((row) => !isClear(row))
  const note = store.rows.find((row) => row.read_note)?.read_note
  return (
    <article className="merchant" data-store={store.domain}>
      <h2>Your store: {store.name}</h2>
      {note && <p className="plain">{note}</p>}
      <section>
        <h3>What your pages answer clearly</h3>
        {clear.length === 0 && <p>Nothing yet.</p>}
        {clear.map((row) => (
          <div key={row.condition} className="condition" data-condition={row.condition}>
            <p className="line">
              Your pages answer {topic(row)} clearly. The answer is: {row.status_text.toLowerCase()}.
            </p>
            <Evidence row={row} />
          </div>
        ))}
      </section>
      <section>
        <h3>What is missing</h3>
        {missing.length === 0 && <p>Nothing is missing.</p>}
        {missing.map((row) => (
          <div key={row.condition} className="condition" data-condition={row.condition}>
            <p className="line">{missingLine(row)}</p>
            <Evidence row={row} />
          </div>
        ))}
      </section>
      <section>
        <h3>Where to add it</h3>
        <p>Your return policy: in your Shopify admin, go to Settings, then Policies.</p>
        <p>
          The knowledge base your store's assistant reads: in your Shopify admin, go to Sales channels, Agentic, then
          Knowledge base.
        </p>
      </section>
    </article>
  )
}

export function Lookup({ stores, current }: { stores: StoreName[]; current: string | null }) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const typed = String(new FormData(event.currentTarget).get('store') ?? '').trim()
    if (typed) navigate(`/merchant?store=${encodeURIComponent(typed)}`)
  }
  return (
    <div className="lookup">
      <form onSubmit={submit}>
        <label htmlFor="store">Your store's domain</label>
        <input id="store" name="store" list="stores" defaultValue={current ?? ''} placeholder="yourstore.com" />
        <datalist id="stores">
          {stores.map((store) => (
            <option key={store.domain} value={store.domain} />
          ))}
        </datalist>
        <button type="submit">Look up</button>
      </form>
      <p className="pick">
        Or pick one:{' '}
        {stores.map((store) => (
          <Link key={store.domain} to={`/merchant?store=${store.domain}`} current={store.domain === current}>
            {store.name}
          </Link>
        ))}
      </p>
    </div>
  )
}

export function MerchantPage({ stores, store, domain }: { stores: StoreName[]; store: Store | null; domain: string | null }) {
  return (
    <main>
      <h1>Merchant View</h1>
      <p className="request">What your pages and your store's assistant tell your buyers.</p>
      <Lookup stores={stores} current={domain} />
      {store && store.checked && store.progress?.pages_read && <MerchantStore store={store} />}
      {store && !(store.checked && store.progress?.pages_read) && (
        <p className="plain">We have no finished check for {domain} yet.</p>
      )}
    </main>
  )
}

export default function MerchantView({ domain }: { domain: string | null }) {
  const [stores, setStores] = useState<StoreName[]>([])
  const [store, setStore] = useState<Store | null>(null)
  useEffect(() => {
    getStores().then(setStores)
  }, [])
  useEffect(() => {
    setStore(null)
    if (domain) getStore(domain).then(setStore)
  }, [domain])
  return <MerchantPage stores={stores} store={store} domain={domain} />
}
