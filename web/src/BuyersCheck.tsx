import { useEffect, useState } from 'react'
import { decide, getCheck, getCheckoutLink, replayCheck, type Action, type Check, type CheckStore, type Row } from './api'
import { Photo, Reply, Status, StoreWords } from './Evidence'
import { MerchantPanel } from './MerchantView'
import { Link, navigate, withParam } from './router'

export function ConditionRow({ row }: { row: Row }) {
  return (
    <section className="condition" data-condition={row.condition}>
      <h4>{row.condition_label}</h4>
      <div className="said">
        {row.page_sentences.map((sentence) => (
          <StoreWords key={sentence.sentence + sentence.url} sentence={sentence} date={row.date_read} />
        ))}
        {row.pages_text && <p className="plain">{row.pages_text}</p>}
        {row.page_status !== 'pending' && <p className="small">From the store's pages</p>}
      </div>
      <p className="verdict">
        <Status status={row.status_shown} text={row.status_text} />
      </p>
      {row.contradiction_text && <p className="flag">{row.contradiction_text}</p>}
      <Reply row={row} label="From the store's assistant" />
    </section>
  )
}

type Act = (store: CheckStore, action: Action) => void

export function StoreEntry({ store, open, to, recorded }: { store: CheckStore; open: boolean; to: string; recorded?: string | null }) {
  return (
    <li className="store" data-store={store.domain} data-result={store.result}>
      <Link to={to} current={open}>
        <Photo url={store.offer?.image_url} title={store.offer?.product_title ?? store.name ?? store.domain} />
        <span className="what">
          <span className="name">{store.offer?.product_title ?? store.name ?? store.domain}</span>
          {store.offer && <span className="small">{store.name ?? store.domain}</span>}
        </span>
        {store.offer && (
          <span className="price">
            {store.offer.price_text}
            {recorded && <span className="small"> recorded {recorded}</span>}
          </span>
        )}
      </Link>
      <p className="result">{store.result_text}</p>
      {store.card_note && <p className="note">{store.card_note}</p>}
      <ul className="marks">
        {store.rows.map((row) => (
          <li key={row.condition}>
            <span>{row.condition_label}</span>
            <span>
              <Status status={row.status_shown} text={row.status_text} />
              {recorded && <span className="small"> recorded {recorded}</span>}
            </span>
          </li>
        ))}
      </ul>
      {store.decision && <p className="decision">{store.decision.text}</p>}
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

export function Decision({ check, store, onAct }: { check: Check; store: CheckStore | null; onAct?: Act }) {
  const decided = check.stores.filter((entry) => entry.decision)
  if (!store)
    return (
      <div className="card decide">
        <p>Pick a store below to see what it says and decide.</p>
        {decided.map((entry) => (
          <p key={entry.domain} className="small">
            {entry.name}: {entry.decision!.text}
          </p>
        ))}
      </div>
    )
  return (
    <div className="card decide" data-store={store.domain}>
      <h3>{store.name}</h3>
      <p className="result">{store.result_text}</p>
      {store.decision && <p className="decision">{store.decision.text}</p>}
      {(store.actions ?? []).length > 0 && (
        <p className="actions">
          {(store.actions ?? []).map((action) =>
            action.action === 'open_site' ? (
              <a key={action.action} className="second" href={store.storefront_url ?? '#'} target="_blank" rel="noopener noreferrer">
                {action.label}
              </a>
            ) : (
              <button key={action.action} className={action.first ? 'primary' : 'second'} onClick={() => onAct?.(store, action)}>
                {action.label}
              </button>
            ),
          )}
        </p>
      )}
    </div>
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
    <div className="card decide review" data-store={store.domain}>
      <h3>Before you go to checkout</h3>
      <p className="small">{store.name}</p>
      {store.rows.map((row) => (
        <section key={row.condition} className="condition" data-condition={row.condition}>
          <h4>{row.condition_label}</h4>
          <div className="said">
            {row.page_sentences.slice(0, 1).map((sentence) => (
              <StoreWords key={sentence.sentence} sentence={sentence} date={row.date_read} />
            ))}
            {(row.pages_text || row.page_sentences.length === 0) && <p className="plain">{row.pages_text}</p>}
          </div>
          <p className="verdict">
            <Status status={row.status_shown} text={row.status_text} />
          </p>
        </section>
      ))}
      <p className="result">{store.result_text}</p>
      {store.decision && (
        <p className="decision">
          {store.decision.text} <span className="small">Recorded {store.decision.time}.</span>
        </p>
      )}
      {store.offer && (
        <p className="offer">
          {store.offer.product_title}, {store.offer.variant_labels.join(' / ')}. {store.offer.price_text}.
        </p>
      )}
      <p className="small">{check.final_total_note}</p>
      <p className="actions">
        {link && (
          <a className="primary checkout" href={link} target="_blank" rel="noopener noreferrer" onClick={onCheckout}>
            Go to checkout
          </a>
        )}
        <Link to={withParam('review', null)}>Back to all stores</Link>
      </p>
      {link && (
        <p className="small">
          This opens {store.name}'s own checkout in a new tab. You enter your details and pay there, not here.
        </p>
      )}
      {!link && <p className="plain">The checkout link is given after your choice at this store.</p>}
    </div>
  )
}

export function CheckView({
  check,
  openStore,
  review,
  link,
  onReplay,
  onAct,
  onCheckout,
}: {
  check: Check
  openStore: string | null
  review?: string | null
  link?: string | null
  onReplay?: () => void
  onAct?: Act
  onCheckout?: () => void
}) {
  const groups = [
    { title: 'Within budget', stores: check.stores.filter((store) => !store.offer || store.offer.within_budget) },
    { title: 'Over budget', stores: check.stores.filter((store) => store.offer && !store.offer.within_budget) },
  ]
  const find = (domain?: string | null) => check.stores.find((store) => store.domain === domain) ?? null
  const reviewed = find(review)
  return (
    <div className="view">
      <section>
        <h2>Stores checked</h2>
        <p className="small">
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
        {check.price_gap && <p className="gap">{check.price_gap.text}</p>}
        {check.price_note && <p className="small">{check.price_note}</p>}
        {check.saved_on && (
          <p className="small">
            Saved rows from {check.saved_on}. {onReplay && <button className="link" onClick={onReplay}>Replay this check from the start</button>}
          </p>
        )}
      </section>
      <section>
        <h2>Your decision</h2>
        {reviewed ? (
          <Review check={check} store={reviewed} link={link ?? null} onCheckout={onCheckout} />
        ) : (
          <Decision check={check} store={find(openStore)} onAct={onAct} />
        )}
      </section>
      <section>
        <h2>What each store says</h2>
        <div className="card">
          {groups.map(
            (group) =>
              group.stores.length > 0 && (
                <div key={group.title}>
                  <p className="small group">{group.title}</p>
                  <ul className="stores">
                    {group.stores.map((store) => {
                      const open = store.domain === openStore
                      return <StoreEntry key={store.domain} store={store} open={open} to={withParam('store', open ? null : store.domain)} recorded={check.saved_on} />
                    })}
                  </ul>
                </div>
              ),
          )}
        </div>
      </section>
    </div>
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
  const [notice, setNotice] = useState<string | null>(null)

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

  if (error)
    return (
      <p className="plain" role="alert">
        We could not load this check. {error}{' '}
        <button className="link" onClick={() => (setError(null), setVersion((now) => now + 1))}>
          Try again
        </button>
      </p>
    )
  if (!check || String(check.id) !== id) return <p className="plain">Loading the check.</p>
  if (merchant) return <MerchantPanel check={check} domain={merchant.store} />
  const reload = () => setVersion((now) => now + 1)
  const act: Act = async (store, action) => {
    setNotice(null)
    try {
      if (action.action !== 'review') await decide(check.id, store.domain, action.action)
    } catch {
      setNotice('That choice could not be saved. Try again.')
      return
    }
    if (action.action === 'skip') reload()
    else navigate(withParam('review', store.domain))
  }
  const replay = () => replayCheck(check.id).then((made) => navigate(`/check/${made.id}`))
  const checkout = () => review && decide(check.id, review, 'checkout').then(reload)
  return (
    <>
      {notice && (
        <p className="plain" role="alert">
          {notice}
        </p>
      )}
      <CheckView check={check} openStore={openStore} review={review} link={link} onReplay={replay} onAct={act} onCheckout={checkout} />
    </>
  )
}
