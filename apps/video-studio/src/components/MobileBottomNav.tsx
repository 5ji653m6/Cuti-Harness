import { useLocation, useNavigate } from 'react-router-dom'
import { Film, MessageCircle } from 'lucide-react'
import { useLanguage } from '@/i18n/LanguageContext'

interface MobileBottomNavProps {
  onCreateClick?: () => void
}

const MobileBottomNav = ({ onCreateClick }: MobileBottomNavProps) => {
  const navigate = useNavigate()
  const location = useLocation()
  const { t } = useLanguage()
  const items = [
    { icon: Film, label: t('navHome'), path: '/' },
    { icon: MessageCircle, label: t('chats'), path: '/create' },
  ]

  const open = (path: string) => {
    if (path === '/' && onCreateClick && location.pathname === '/') onCreateClick()
    else navigate(path)
  }

  return (
    <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-border/50 bg-background/95 pb-safe backdrop-blur-lg md:hidden">
      <div className="flex items-center justify-around px-2 py-1">
        {items.map(({ icon: Icon, label, path }) => {
          const active = path === '/' ? location.pathname === '/' : location.pathname.includes('/create')
          return (
            <button key={path} type="button" onClick={() =>{  open(path) }} className={`flex min-h-11 min-w-20 flex-col items-center gap-0.5 rounded-lg px-3 py-1.5 ${active ? 'text-foreground' : 'text-muted-foreground'}`}>
              <Icon className="h-5 w-5" strokeWidth={active ? 2.5 : 2} />
              <span className="text-[10px] font-medium">{label}</span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}

export default MobileBottomNav
