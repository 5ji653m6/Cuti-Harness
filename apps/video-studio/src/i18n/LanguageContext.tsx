import React, { createContext, useCallback, useContext, useEffect, useMemo } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { translations, Language, TranslationKey } from './translations'

interface LanguageContextType {
  language: Language
  setLanguage: (lang: Language) => void
  t: (key: TranslationKey) => string
}

const LanguageContext = createContext<LanguageContextType | undefined>(undefined)

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation()
  const navigate = useNavigate()

  // 从URL路径中提取语言，格式: /en/... 或 /zh/...
  const language = useMemo<Language>(() => {
    // 从路径中提取
    const pathParts = location.pathname.split('/').filter(Boolean)
    const firstPart = pathParts[0]
    if (firstPart === 'en' || firstPart === 'zh') {
      return firstPart
    }

    // 如果没有语言前缀，从localStorage读取或使用默认值
    const saved = localStorage.getItem('language')
    return saved === 'zh' ? 'zh' : 'en'
  }, [location.pathname])

  // 保存语言到localStorage
  useEffect(() => {
    localStorage.setItem('language', language)
  }, [language])

  const setLanguage = useCallback((lang: Language) => {
    localStorage.setItem('language', lang)

    // 更新URL路径中的语言前缀
    const pathParts = location.pathname.split('/').filter(Boolean)
    const firstPart = pathParts[0]

    // 检查路径是否已经包含语言前缀
    const hasLangPrefix = firstPart === 'en' || firstPart === 'zh'

    if (hasLangPrefix) {
      // 如果当前路径有语言前缀，替换它
      // 移除第一个元素（语言前缀），保留剩余路径
      const restPath = pathParts.slice(1).join('/')
      const newPath = `/${lang}${restPath ? '/' + restPath : ''}${location.search}`
      navigate(newPath, { replace: true })
    } else {
      // 如果当前路径没有语言前缀，添加它
      // 先移除可能存在的语言前缀（防止重复）
      let currentPath = location.pathname.replace(/^\/(en|zh)\//, '/').replace(/^\/(en|zh)$/, '/')
      if (!currentPath.startsWith('/')) {
        currentPath = `/${currentPath}`
      }
      const newPath = `/${lang}${currentPath === '/' ? '' : currentPath}${location.search}`
      navigate(newPath, { replace: true })
    }
  }, [location.pathname, location.search, navigate])

  const t = useCallback((key: TranslationKey): string => {
    return translations[language][key] || translations.en[key] || key
  }, [language])

  const value = useMemo(
    () => ({ language, setLanguage, t }),
    [language, setLanguage, t],
  )

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  )
}

export const useLanguage = () => {
  const context = useContext(LanguageContext)
  if (!context) {
    throw new Error('useLanguage must be used within a LanguageProvider')
  }
  return context
}
