import { useLocation, useNavigate } from 'react-router-dom'
import { Globe, MessageCircle, Film } from 'lucide-react'
import { useLanguage } from '@/i18n/LanguageContext'

interface SidebarProps {
  onCreateClick?: () => void
  hideUserFooter?: boolean
}

const Sidebar = ({ onCreateClick }: SidebarProps) => {
  const navigate = useNavigate()
  const location = useLocation()
  const { language, setLanguage, t } = useLanguage()
  const items = [
    { icon: Film, label: t('navHome'), path: '/' },
    { icon: MessageCircle, label: t('chats'), path: '/create' },
  ]

  const open = (path: string) => {
    if (path === '/' && onCreateClick && location.pathname === '/') onCreateClick()
    else navigate(path)
  }

  return (
    <aside className="fixed left-0 top-0 z-50 hidden h-screen w-20 flex-col items-center bg-sidebar py-8 md:flex">
      <nav className="flex flex-1 flex-col items-center gap-6 pt-4">
        {items.map(({ icon: Icon, label, path }) => {
          const active = path === '/' ? location.pathname === '/' : location.pathname.includes('/create')
          return (
            <button key={path} type="button" onClick={() =>{  open(path) }} className={`flex flex-col items-center gap-2 transition-colors ${active ? 'text-sidebar-foreground' : 'text-sidebar-foreground/60 hover:text-sidebar-foreground'}`}>
              <Icon className="h-6 w-6" strokeWidth={2} />
              <span className="text-[10px] font-medium">{label}</span>
            </button>
          )
        })}
      </nav>
      <button type="button" onClick={() =>{  setLanguage(language === 'en' ? 'zh' : 'en') }} className="flex flex-col items-center gap-1 text-sidebar-foreground/70 hover:text-sidebar-foreground" title={t('language')}>
        <Globe className="h-5 w-5" />
        <span className="text-[10px]">{language === 'en' ? 'EN' : '中文'}</span>
      </button>
    </aside>
  )
}

export default Sidebar
