import { useLocation } from 'react-router-dom'
import { useEffect } from 'react'
import { useLanguage } from '@/i18n/LanguageContext'

const NotFound = () => {
  const location = useLocation()
  const { language } = useLanguage()
  const zh = language === 'zh'

  useEffect(() => {
    console.error('404 Error: User attempted to access non-existent route:', location.pathname)
  }, [location.pathname])

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-100">
      <div className="text-center">
        <h1 className="mb-4 text-4xl font-bold">404</h1>
        <p className="mb-4 text-xl text-gray-600">{zh ? '抱歉，找不到这个页面' : 'Oops! Page not found'}</p>
        <a href="/" className="text-blue-500 underline hover:text-blue-700">
          {zh ? '返回首页' : 'Return to Home'}
        </a>
      </div>
    </div>
  )
}

export default NotFound
