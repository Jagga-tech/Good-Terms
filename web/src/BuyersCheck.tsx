import { useEffect, useState } from 'react'
import { decide, getCheck, getCheckoutLink, replayCheck, type Action, type Check, type CheckStore, type Row } from './api'
import { Mark, Reply, StoreWords } from './Evidence'
import { MerchantTab } from './MerchantView'
import { Link, navigate } from './router'

export function ConditionRow({ row }: { row: Row }) {
  const wordsCarryTheStatus = row.status_text === row.pages_text
  return (
    <section className="condition" data-condition={row.condition}>
      <h4>{row.condition_label}</h4>
      <div className="answer">
        <div className="said">
          {row.page_sentences.map((sentence) => (
            <StoreWords key={sentence.sentence + sentence.url} sentence={sentence} date={row.date_read} />
          ))}
          {row.pages_text && <p className="plain">{row.pages_text}</p>}
          {row.page_status !== 'pending' && <p className="label">From the store's pages</p>}
        </div>
        <p className={`status ${row.status_shown}`}>
          <Mark status={row.status_shown} />
          {!wordsCarryTheStatus && <span>{row.status_text}</span>}
        </p>
      </div>
      {row.contradiction_text && <p className="flag">{row.contradiction_text}</p>}
      <Reply row={row} label="From the store's assistant" />
    </section>
  )
}

type Act = (store: CheckStore, action: Action) => void

export function StoreEntry({ store, open, to, onAct }: { store: CheckStore; open: boolean; to: string; onAct?: Act }) {
  return (
    <li className="store" data-store={store.domain} data-result={store.result}>
      <Link to={to}>
        <span className="name">{store.name ?? store.domain}</span>
        {store.offer && <span className="price">{store.offer.price_text}</span>}
      </Link>
      <p className="result">{store.result_text}</p>
      {store.card_note && <p className="note">{store.card_note}</p>}
      <ul className="marks">
        {store.rows.map((row) => (
          <li key={row.condition} className={row.status_shown}>
            <Mark status={row.status_shown} />
            <span>{row.condition_label}</span>
            <span className="word">{row.status_text}</span>
          </li>
        ))}
      </ul>
      {store.decision && <p className="decision">{store.decision.text}</p>}
      {(store.actions ?? []).length > 0 && (
        <p className="actions">
          {(store.actions ?? []).map((action) =>
            action.action === 'open_site' ? (
              <a key={action.action} className="button" href={store.storefront_url ?? '#'} target="_blank" rel="noopener noreferrer">
                {action.label}
              </a>
            ) : (
              <button key={action.action} className={action.first ? 'primary' : 'button'} onClick={() => onAct?.(store, action)}>
                {action.label}
              </button>
            ),
          )}
        </p>
      )}
      {open && (
        <div className="detail">
          {store.rows.map((row) => (
            <ConditionRow key={row.condition} row={row} />
          ))}
          {store.offer && (
            <p className="offer">
              {store.offer.product_title}, {store.offer.variant_labels.join(' / ')}. {store.offer.price_text}.
            </p>
          )}
        </div>
      )}
    </li>
  )
}

export function CheckView({
  check,
  openStore,
  onReplay,
  onAct,
}: {
  check: Check
  openStore: string | null
  onReplay?: () => void
  onAct?: Act
}) {
  const groups = [
    { title: 'Within budget', stores: check.stores.filter((store) => !store.offer || store.offer.within_budget) },
    { title: 'Over budget', stores: check.stores.filter((store) => store.offer && !store.offer.within_budget) },
  ]
  return (
    <main>
      <h1>Buyer's Check</h1>
      <p className="request">
        {check.search_text}
        {check.requested_size && <span> · size {check.requested_size}</span>}
      </p>
      <p className="conditions">
        Your conditions:{' '}
        {check.conditions.map((label) => (
          <span key={label} className="chip">
            {label}
          </span>
        ))}
      </p>
      {check.saved_on && (
        <p className="saved">
          Saved rows from {check.saved_on}. {onReplay && <button onClick={onReplay}>Replay this check from the start</button>}
        </p>
      )}
      {check.price_gap && <p className="gap">{check.price_gap.text}</p>}
      {check.price_note && <p className="pricenote">{check.price_note}</p>}
      {groups.map(
        (group) =>
          group.stores.length > 0 && (
            <section key={group.title}>
              <h2>{group.title}</h2>
              <ul className="stores">
                {group.stores.map((store) => {
                  const open = store.domain === openStore
                  const to = open ? `/check/${check.id}` : `/check/${check.id}?store=${store.domain}`
                  return <StoreEntry key={store.domain} store={store} open={open} to={to} onAct={onAct} />
                })}
              </ul>
            </section>
          ),
      )}
    </main>
  )
}

export function Review({
  check,
  store,
  link,
  onCheckout,
}: {
  check: Check
  store: CheckStore
  link: string | null
  onCheckout?: () => void
}) {
  return (
    <main className="review" data-store={store.domain}>
      <h1>Before you go to checkout</h1>
      <p className="request">{store.name}</p>
      {store.rows.map((row) => (
        <section key={row.condition} className="condition" data-condition={row.condition}>
          <h4>{row.condition_label}</h4>
          <div className="answer">
            <div className="said">
              {row.page_sentences.slice(0, 1).map((sentence) => (
                <StoreWords key={sentence.sentence} sentence={sentence} date={row.date_read} />
              ))}
              {(row.pages_text || row.page_sentences.length === 0) && <p className="plain">{row.pages_text}</p>}
            </div>
            <p className={`status ${row.status_shown}`}>
              <Mark status={row.status_shown} />
              <span>{row.status_text}</span>
            </p>
          </div>
        </section>
      ))}
      <p className="result">{store.result_text}</p>
      {store.decision && (
        <p className="decision">
          {store.decision.text} <span className="label">Recorded {store.decision.time}.</span>
        </p>
      )}
      {store.offer && (
        <p className="offer">
          {store.offer.product_title}, {store.offer.variant_labels.join(' / ')}. {store.offer.price_text}.
        </p>
      )}
      <p className="pricenote">{check.final_total_note}</p>
      <p className="actions">
        {link && (
          <a className="primary" href={link} target="_blank" rel="noopener noreferrer" onClick={onCheckout}>
            Go to checkout
          </a>
        )}
        <Link to={`/check/${check.id}`}>Back to all stores</Link>
      </p>
      {link && (
        <p className="label">
          This opens {store.name}'s own checkout in a new tab. You enter your details and pay there, not here.
        </p>
      )}
      {!link && <p className="plain">The checkout link is given after your choice at this store.</p>}
    </main>
  )
}

export default function BuyersCheck({
  id,
  openStore,
  review,
  merchant,
}: {
  id: string
  openStore: string | null
  review?: string | null
  merchant?: { store: string | null } | null
}) {
  const [check, setCheck] = useState<Check | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)
  const [link, setLink] = useState<string | null>(null)

  useEffect(() => {
    let timer = 0
    let stopped = false
    const load = () =>
      getCheck(id)
        .then((next) => {
          if (stopped) return
          setCheck(next)
          if (!next.done) timer = window.setTimeout(load, 1000)
        })
        .catch((problem) => !stopped && setError(String(problem)))
    load()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [id, version])

  useEffect(() => {
    setLink(null)
    if (review)
      getCheckoutLink(Number(id), review)
        .then((found) => setLink(found.url))
        .catch(() => setLink(null))
  }, [id, review, version])

  if (error) return <main><p>We could not load this check. {error}</p></main>
  if (!check || String(check.id) !== id) return <main><p>Loading the check.</p></main>
  if (merchant) return <MerchantTab check={check} domain={merchant.store} base={`/check/${check.id}`} />
  const reload = () => setVersion((now) => now + 1)
  const act: Act = async (store, action) => {
    if (action.action !== 'review') await decide(check.id, store.domain, action.action)
    if (action.action === 'skip') reload()
    else navigate(`/check/${check.id}?review=${store.domain}`)
  }
  const reviewed = review ? check.stores.find((store) => store.domain === review) : null
  if (reviewed)
    return (
      <Review check={check} store={reviewed} link={link} onCheckout={() => decide(check.id, reviewed.domain, 'checkout').then(reload)} />
    )
  const replay = () => replayCheck(check.id).then((made) => navigate(`/check/${made.id}`))
  return <CheckView check={check} openStore={openStore} onReplay={replay} onAct={act} />
}
