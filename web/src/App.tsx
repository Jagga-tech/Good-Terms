import { useEffect, useState } from 'react'
import { getCoco } from './api'
import BuyersCheck from './BuyersCheck'
import Coco from './Coco'
import { MerchantPanel } from './MerchantView'
import { Link, navigate, useRoute, withParam } from './router'

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

export function NothingYet({ backup }: { backup: boolean }) {
  return (
    <div className="view">
      <section>
        <h2>Stores checked</h2>
        <p className="plain">Nothing is being checked yet.</p>
        <p className="small">Tell Coco what you need. Each store's answers appear here as its pages are read.</p>
        {backup && (
          <p className="small">
            <Link to="/check/2">Open the saved check from 2026-11-15</Link>
          </p>
        )}
      </section>
    </div>
  )
}

export function Switch({ tab, buyer, merchant }: { tab: 'buyer' | 'merchant'; buyer: string; merchant: string }) {
  return (
    <nav className="switch" aria-label="View">
      <Link to={buyer} current={tab === 'buyer'}>
        Buyer's check
      </Link>
      <Link to={merchant} current={tab === 'merchant'}>
        Merchant view
      </Link>
    </nav>
  )
}

export default function App() {
  const url = useRoute()
  const route = parseRoute(url)
  const [backup, setBackup] = useState(false)
  useEffect(() => {
    getCoco().then((state) => setBackup(state.backup_mode))
  }, [])
  useEffect(() => {
    if (route.screen === 'none') navigate('/', true)
  }, [route.screen])

  if (route.screen === 'none') return null
  const merchant = route.tab === 'merchant'
  return (
    <>
      <div className="page">
        <aside className="left">
          <p className="brand">GoodTerms</p>
          <Coco checkShown={route.id} />
        </aside>
        <div className="right">
          <Switch tab={route.tab} buyer={withParam('view', null)} merchant={withParam('view', 'merchant')} />
          {route.id && (
            <BuyersCheck
              id={route.id}
              openStore={route.store}
              review={route.review}
              merchant={merchant ? { store: route.merchantStore } : null}
            />
          )}
          {!route.id && (merchant ? <MerchantPanel check={null} domain={null} /> : <NothingYet backup={backup} />)}
        </div>
      </div>
      <Footer />
    </>
  )
}
