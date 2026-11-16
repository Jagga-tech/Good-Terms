import { useEffect, useRef } from 'react'
import BuyersCheck from './BuyersCheck'
import Coco from './Coco'
import { MerchantTab } from './MerchantView'
import { Link, navigate, useRoute } from './router'

export function Footer() {
  return <footer>Prototype. Not affiliated with Shopify.</footer>
}

export function parseRoute(url: URL) {
  const check = url.pathname.match(/^\/check\/(\d+)$/)
  const asked = (name: string) => url.searchParams.get(name)
  if (!check && url.pathname !== '/') return { screen: 'none' as const }
  return {
    screen: 'shop' as const,
    id: check ? check[1] : null,
    tab: asked('view') === 'merchant' ? ('merchant' as const) : ('buyer' as const),
    store: asked('store'),
    review: asked('review'),
    merchantStore: asked('m'),
  }
}

export function NothingYet() {
  return (
    <main>
      <h1>Buyer's Check</h1>
      <p className="plain">Nothing is being checked yet.</p>
      <p className="request">Tell Coco what you need. Each store's answers appear here as its pages are read.</p>
      <p className="saved">
        <Link to="/check/2">Open the saved check from 2026-11-15</Link>
      </p>
    </main>
  )
}

export function Tabs({ tab, buyer, merchant }: { tab: 'buyer' | 'merchant'; buyer: string; merchant: string }) {
  return (
    <nav className="tabs">
      <Link to={buyer} current={tab === 'buyer'}>
        Buyer's Check
      </Link>
      <Link to={merchant} current={tab === 'merchant'}>
        Merchant view: what a store would see
      </Link>
    </nav>
  )
}

export default function App() {
  const url = useRoute()
  const route = parseRoute(url)
  const last = useRef<Record<string, string>>({})

  useEffect(() => {
    if (route.screen === 'none') navigate('/', true)
  }, [route.screen])

  if (route.screen === 'none') return null
  const base = route.id ? `/check/${route.id}` : '/'
  last.current[`${base}:${route.tab}`] = url.pathname + url.search
  const buyer = last.current[`${base}:buyer`] ?? base
  const merchant = last.current[`${base}:merchant`] ?? `${base}?view=merchant`
  return (
    <>
      <header>
        <span className="brand">GoodTerms</span>
      </header>
      <div className="split">
        <Coco checkShown={route.id} />
        <div className="pane">
          <Tabs tab={route.tab} buyer={buyer} merchant={merchant} />
          {route.id && (
            <BuyersCheck
              id={route.id}
              openStore={route.store}
              review={route.review}
              merchant={route.tab === 'merchant' ? { store: route.merchantStore } : null}
            />
          )}
          {!route.id && (route.tab === 'merchant' ? <MerchantTab check={null} domain={null} base="/" /> : <NothingYet />)}
        </div>
      </div>
      <Footer />
    </>
  )
}
