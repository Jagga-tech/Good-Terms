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
  if (check) return { screen: 'buyer' as const, id: check[1], store: url.searchParams.get('store') }
  if (url.pathname === '/merchant') return { screen: 'merchant' as const, store: url.searchParams.get('store') }
  if (url.pathname === '/') return { screen: 'coco' as const }
  return { screen: 'none' as const }
}

export default function App() {
  const url = useRoute()
  const route = parseRoute(url)
  const last = useRef({ buyer: '/check/1', merchant: '/merchant' })
  if (route.screen === 'buyer' || route.screen === 'merchant') last.current[route.screen] = url.pathname + url.search

  useEffect(() => {
    if (route.screen === 'none') navigate('/', true)
  }, [route.screen])

  return (
    <>
      <header>
        <span className="brand">GoodTerms</span>
        <nav>
          <Link to="/" current={route.screen === 'coco'}>
            Coco
          </Link>
          <Link to={last.current.buyer} current={route.screen === 'buyer'}>
            Buyer's Check
          </Link>
          <Link to={last.current.merchant} current={route.screen === 'merchant'}>
            Merchant View
          </Link>
        </nav>
      </header>
      {route.screen === 'coco' && <Coco />}
      {route.screen === 'buyer' && <BuyersCheck id={route.id} openStore={route.store} />}
      {route.screen === 'merchant' && <MerchantView domain={route.store} />}
      <Footer />
    </>
  )
}
