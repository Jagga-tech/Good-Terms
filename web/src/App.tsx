import { useEffect, useRef } from 'react'
import BuyersCheck from './BuyersCheck'
import Coco from './Coco'
import MerchantView from './MerchantView'
import { Link, navigate, useRoute } from './router'

export function Footer() {
  return <footer>Prototype. Not affiliated with Shopify.</footer>
}

export function parseRoute(url: URL) {
  const check = url.pathname.match(/^\/check\/(\d+)$/)
  const asked = (name: string) => url.searchParams.get(name)
  if (check) return { screen: 'shop' as const, id: check[1], store: asked('store'), review: asked('review') }
  if (url.pathname === '/') return { screen: 'shop' as const, id: null, store: null, review: null }
  if (url.pathname === '/merchant') return { screen: 'merchant' as const, store: asked('store') }
  return { screen: 'none' as const }
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

export default function App() {
  const url = useRoute()
  const route = parseRoute(url)
  const last = useRef({ shop: '/', merchant: '/merchant' })
  if (route.screen !== 'none') last.current[route.screen] = url.pathname + url.search

  useEffect(() => {
    if (route.screen === 'none') navigate('/', true)
  }, [route.screen])

  return (
    <>
      <header>
        <span className="brand">GoodTerms</span>
        <nav>
          <Link to={last.current.shop} current={route.screen === 'shop'}>
            Coco and Buyer's Check
          </Link>
          <Link to={last.current.merchant} current={route.screen === 'merchant'}>
            Merchant View
          </Link>
        </nav>
      </header>
      {route.screen === 'shop' && (
        <div className="split">
          <Coco checkShown={route.id} />
          <div className="pane">
            {route.id ? <BuyersCheck id={route.id} openStore={route.store} review={route.review} /> : <NothingYet />}
          </div>
        </div>
      )}
      {route.screen === 'merchant' && (
        <div className="single">
          <MerchantView domain={route.store} />
        </div>
      )}
      <Footer />
    </>
  )
}
