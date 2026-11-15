import { useEffect, useState } from 'react'
import { getCheck, replayCheck, type Check, type CheckStore, type Row } from './api'
import { Mark, Reply, StoreWords } from './Evidence'
import { Link, navigate } from './router'

export function ConditionRow({ row }: { row: Row }) {
  const wordsCarryTheStatus = row.status_text === row.pages_text
  return (
    <section className="condition" data-condition={row.condition}>
      <h4>{row.condition_label}</h4>
      <div className="answer">
        <div className="said">
          {row.page_sentences.map((sentence) => (
            <StoreWords key={sentence.sentence} sentence={sentence} date={row.date_read} />
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

export function StoreEntry({ store, open, to }: { store: CheckStore; open: boolean; to: string }) {
  return (
    <li className="store" data-store={store.domain} data-result={store.result}>
      <Link to={to}>
        <span className="name">{store.name ?? store.domain}</span>
        {store.offer && (
          <span className="price">
            {store.offer.price_text} <small>{store.offer.price_basis}</small>
          </span>
        )}
      </Link>
      <p className="result">{store.result_text}</p>
      <ul className="marks">
        {store.rows.map((row) => (
          <li key={row.condition} className={row.status_shown}>
            <Mark status={row.status_shown} />
            <span>{row.condition_label}</span>
            <span className="word">{row.status_text}</span>
          </li>
        ))}
      </ul>
      {open && (
        <div className="detail">
          {store.rows.map((row) => (
            <ConditionRow key={row.condition} row={row} />
          ))}
          {store.offer && (
            <p className="offer">
              {store.offer.product_title}, {store.offer.variant_labels.join(' / ')}. {store.offer.price_text},{' '}
              {store.offer.price_basis}.
            </p>
          )}
        </div>
      )}
    </li>
  )
}

export function CheckView({ check, openStore, onReplay }: { check: Check; openStore: string | null; onReplay?: () => void }) {
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
      {groups.map(
        (group) =>
          group.stores.length > 0 && (
            <section key={group.title}>
              <h2>{group.title}</h2>
              <ul className="stores">
                {group.stores.map((store) => {
                  const open = store.domain === openStore
                  const to = open ? `/check/${check.id}` : `/check/${check.id}?store=${store.domain}`
                  return <StoreEntry key={store.domain} store={store} open={open} to={to} />
                })}
              </ul>
            </section>
          ),
      )}
    </main>
  )
}

export default function BuyersCheck({ id, openStore }: { id: string; openStore: string | null }) {
  const [check, setCheck] = useState<Check | null>(null)
  const [error, setError] = useState<string | null>(null)

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
  }, [id])

  if (error) return <main><p>We could not load this check. {error}</p></main>
  if (!check || String(check.id) !== id) return <main><p>Loading the check.</p></main>
  const replay = () => replayCheck(check.id).then((made) => navigate(`/check/${made.id}`))
  return <CheckView check={check} openStore={openStore} onReplay={replay} />
}
