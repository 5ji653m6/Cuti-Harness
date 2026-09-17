import { Navigate, useParams, useLocation } from 'react-router-dom'
import { ReactNode } from 'react'

interface LanguageRouteProps {
  children: ReactNode
}

/**
 * 语言路由包装组件
 * 确保所有路由都有语言前缀（/en/... 或 /zh/...）
 * 如果没有语言前缀，重定向到默认语言版本
 */
export const LanguageRoute = ({ children }: LanguageRouteProps) => {
  const { lang } = useParams<{ lang: string }>()
  const location = useLocation()

  // 验证语言参数
  if (!lang || (lang !== 'en' && lang !== 'zh')) {
    // 如果没有语言前缀或语言无效，重定向到默认语言版本
    const defaultLang = localStorage.getItem('language') || 'en'
    // 获取当前路径，移除可能存在的语言前缀（包括重复的）
    const pathWithoutLang = location.pathname.replace(/^\/(en|zh)\/(en|zh)\//, '/').replace(/^\/(en|zh)\//, '/').replace(/^\/(en|zh)$/, '/') || '/'
    const newPath = `/${defaultLang}${pathWithoutLang}${location.search}`
    return <Navigate to={newPath} replace />
  }

  // 检查路径中是否有重复的语言前缀（如 /zh/zh/create）
  const pathParts = location.pathname.split('/').filter(Boolean)
  if (pathParts.length >= 2 && pathParts[0] === lang && pathParts[1] === lang) {
    // 如果检测到重复的语言前缀，重定向到正确的路径
    const restPath = pathParts.slice(2).join('/')
    const newPath = `/${lang}${restPath ? '/' + restPath : ''}${location.search}`
    return <Navigate to={newPath} replace />
  }

  return <>{children}</>
}
