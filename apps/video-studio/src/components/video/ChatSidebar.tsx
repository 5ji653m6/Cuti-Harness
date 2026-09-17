import React from 'react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  Plus,
  Search,
  ChevronLeft,
  ChevronRight,
  MoreHorizontal,
  Globe,
  Loader2,
  Pin,
  PinOff,
  RefreshCw,
  Trash2,
  Settings as SettingsIcon,
} from 'lucide-react'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { useLanguage } from '@/i18n/LanguageContext'
import { useNavigate } from 'react-router-dom'
import aiAvatar from '@/assets/ai-avatar-capybara.png'
import { isConversationPinned, getPinnedConversationsData } from '@/utils/pinnedConversations'

interface Chat {
  id: string
  title: string
  thread_id: string
  conversation_id: number
  /** 与后端 AgentType 对齐：video | story | music | image | clarify | auto */
  agent_type?: string
  /** 任务消息/用户输入预览，用于手机端列表项展示 */
  preview?: string
  /** 用户输入的图片 URL，用于列表项头像展示 */
  previewImageUrl?: string
  /** 创建时间（ISO），用于展示任务大致时间 */
  created_at?: string
  /** 最后活跃时间（ISO），优先用于展示任务大致时间 */
  last_active_at?: string
}

interface PinnedChat extends Chat {
  isUnloaded?: boolean // Flag to indicate if this chat is pinned but not yet loaded from API
}

/** 把 ISO 时间格式化为「大致时间」：今天显示时:分，7 天内显示 N 天前，更早显示日期 */
const formatChatTime = (iso: string | undefined, language: string): string => {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const dayMs = 24 * 60 * 60 * 1000
  const isZh = language === 'zh'
  if (diffMs < dayMs && now.getDate() === d.getDate()) {
    return d.toLocaleTimeString(isZh ? 'zh-CN' : 'en-US', { hour: '2-digit', minute: '2-digit' })
  }
  const days = Math.floor(diffMs / dayMs)
  if (days < 7) {
    if (days <= 1) return isZh ? '昨天' : '1d ago'
    return isZh ? `${days}天前` : `${days}d ago`
  }
  const sameYear = d.getFullYear() === now.getFullYear()
  if (isZh) {
    return sameYear ? `${d.getMonth() + 1}月${d.getDate()}日` : `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
  }
  return d.toLocaleDateString('en-US', sameYear ? { month: 'short', day: 'numeric' } : { year: 'numeric', month: 'short', day: 'numeric' })
}

interface UserInfo {
  email: string
}

interface UserCredits {
  balance: number
}

interface ChatSidebarProps {
  collapsed: boolean
  selectedChat: string | null
  chats: Chat[]
  userInfo: UserInfo | null
  userCredits: UserCredits | null
  isLoadingChats?: boolean
  hasMoreChats?: boolean
  onToggleCollapse: () => void
  onNewTask: () => void
  /** 打开会话搜索弹窗 */
  onOpenSearch?: () => void
  onSelectChat: (chatId: string) => void
  onDeleteChat: (chatId: string, e: React.MouseEvent) => void
  onTogglePin: (chatId: string, e: React.MouseEvent) => void
  onRerunChat?: (chat: Chat) => void
  onLoadMore?: () => void
  showConversationActions?: boolean
  showDeleteAction?: boolean
  /** 手机端全屏模式：铺满屏幕，每项显示 Cuti 头像 + 任务消息 */
  isMobileFullScreen?: boolean
}

export const ChatSidebar = ({
  collapsed,
  selectedChat,
  chats,
  isLoadingChats = false,
  hasMoreChats = true,
  onToggleCollapse,
  onNewTask,
  onOpenSearch,
  onSelectChat,
  onDeleteChat,
  onTogglePin,
  onRerunChat,
  onLoadMore,
  showConversationActions = true,
  showDeleteAction = false,
  isMobileFullScreen = false,
}: ChatSidebarProps) => {
  const { language, setLanguage, t } = useLanguage()
  const navigate = useNavigate()
  const scrollAreaRef = React.useRef<HTMLDivElement>(null)
  const selectedChatRef = React.useRef<HTMLDivElement>(null)
  const savedScrollPositionRef = React.useRef<number>(0)
  const scrollAreaViewportRef = React.useRef<HTMLElement | null>(null)

  // Merge pinned conversations with loaded chats
  // This ensures pinned conversations are always visible even if not loaded yet
  const mergedChats: PinnedChat[] = React.useMemo(() => {
    const pinnedData = getPinnedConversationsData()
    const loadedChatIds = new Set(chats.map(c => c.id))

    // Find pinned conversations that are not in the loaded chats
    const unloadedPinned = pinnedData
      .filter(p => !loadedChatIds.has(p.id))
      .map(p => ({
        id: p.id,
        title: p.title,
        thread_id: p.thread_id,
        conversation_id: p.conversation_id,
        isUnloaded: true,
      }))

    // Mark loaded chats that are pinned
    const markedChats = chats.map(chat => ({
      ...chat,
      isUnloaded: false,
    }))

    // Combine: unloaded pinned first, then loaded chats; sort so pinned always appear at top
    const combined: PinnedChat[] = [...unloadedPinned, ...markedChats]
    return combined.sort((a, b) => {
      const aPinned = isConversationPinned(a.id)
      const bPinned = isConversationPinned(b.id)
      if (aPinned && !bPinned) return -1
      if (!aPinned && bPinned) return 1
      return 0
    })
  }, [chats])

  const handleScroll = (event: React.UIEvent<HTMLDivElement>) => {
    if (!onLoadMore || isLoadingChats || !hasMoreChats) return

    const target = event.currentTarget
    const scrollPercentage = (target.scrollTop + target.clientHeight) / target.scrollHeight

    // 当滚动到 80% 时加载更多
    if (scrollPercentage > 0.8) {
      onLoadMore()
    }
  }

  const handleSidebarRootClick = (e: React.MouseEvent) => {
    if (collapsed && !(e.target as HTMLElement).closest('button')) {
      onToggleCollapse()
    }
  }

  // Save scroll position when sidebar collapses
  React.useEffect(() => {
    if (collapsed && scrollAreaViewportRef.current) {
      savedScrollPositionRef.current = scrollAreaViewportRef.current.scrollTop
    }
  }, [collapsed])

  // Restore scroll position when sidebar expands
  React.useEffect(() => {
    if (!collapsed) {
      // Small delay to ensure DOM is updated and ScrollArea is rendered
      const timeoutId = setTimeout(() => {
        // Try to get viewport if not already stored
        if (!scrollAreaViewportRef.current && scrollAreaRef.current) {
          const scrollAreaRoot = scrollAreaRef.current.closest('[data-radix-scroll-area-root]')
          scrollAreaViewportRef.current = scrollAreaRoot?.querySelector<HTMLElement>('[data-radix-scroll-area-viewport]') ?? null
        }

        const viewport = scrollAreaViewportRef.current
        if (!viewport) return

        // Restore saved scroll position
        if (savedScrollPositionRef.current > 0) {
          viewport.scrollTo({
            top: savedScrollPositionRef.current,
            behavior: 'instant', // Use instant to restore position immediately
          })
        } else if (selectedChat && selectedChatRef.current) {
          // If no saved position but there's a selected chat, scroll to it (first time)
          selectedChatRef.current.scrollIntoView({
            behavior: 'smooth',
            block: 'nearest',
            inline: 'nearest',
          })
        }
      }, 150)

      return () =>{  clearTimeout(timeoutId) }
    }
  }, [collapsed, selectedChat])

  // Find and store ScrollArea viewport reference, and set up scroll listener
  React.useEffect(() => {
    if (!collapsed && scrollAreaRef.current) {
      const findViewport = () => {
        // Try to find viewport from scrollAreaRef's parent (ScrollArea root)
        const scrollAreaRoot = scrollAreaRef.current?.closest('[data-radix-scroll-area-root]')
        const viewport = scrollAreaRoot?.querySelector<HTMLElement>('[data-radix-scroll-area-viewport]')

        if (viewport) {
          scrollAreaViewportRef.current = viewport
          // Set up scroll listener to save position continuously
          const handleViewportScroll = () => {
            savedScrollPositionRef.current = viewport.scrollTop
          }
          viewport.addEventListener('scroll', handleViewportScroll, { passive: true })
          return () => {
            viewport.removeEventListener('scroll', handleViewportScroll)
          }
        }
        return undefined
      }

      // Try immediately
      let cleanup = findViewport()

      // Retry if viewport not found immediately (DOM might not be ready)
      if (!scrollAreaViewportRef.current) {
        const retryTimeout = setTimeout(() => {
          cleanup = findViewport()
        }, 100)
        return () => {
          clearTimeout(retryTimeout)
          cleanup?.()
        }
      }

      return cleanup
    } else {
      scrollAreaViewportRef.current = null
    }
  }, [collapsed])

  return (
    <div
      className={`${
        isMobileFullScreen ? 'w-full grow h-0' : (collapsed ? 'w-20' : 'w-80') + ' flex-shrink-0'
      } transition-all duration-300 flex flex-col border-r-0 bg-zinc-100/90 dark:bg-[#000000] backdrop-blur-md overflow-hidden ${collapsed ? 'cursor-e-resize' : ''}`}
      onClick={handleSidebarRootClick}
      title={collapsed ? t('da.page.expandSidebar') : undefined}
    >
      {/* Sidebar Header - logo 展开前后位置一致 */}
      <div className="w-full min-w-0 flex-shrink-0 p-4 flex items-center justify-between box-border">
        {collapsed ? (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onToggleCollapse() }}
            className="group h-8 w-8 flex items-center justify-center flex-shrink-0 hover:opacity-80 transition-opacity"
            title={t('da.page.expandSidebar')}
          >
            <img src={`${import.meta.env.BASE_URL}logo-internal.png`} alt="Cuti" className="h-8 w-8 object-contain group-hover:hidden" />
            <ChevronRight className="w-4 h-4 text-muted-foreground hidden group-hover:block" />
          </button>
        ) : (
          <>
            <button onClick={(e) => { e.stopPropagation(); navigate('/') }} className="h-8 w-8 flex items-center justify-center flex-shrink-0 hover:opacity-80 transition-opacity">
              <img src={`${import.meta.env.BASE_URL}logo-internal.png`} alt="Cuti" className="h-8 w-8 object-contain" />
            </button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggleCollapse}
              className="rounded-full hover:bg-black/10 dark:hover:bg-white/10"
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
          </>
        )}
      </div>

      {/* Main Content Area with Fixed Sections */}
      <div className="grow h-0 flex flex-col overflow-hidden">
        {/* Fixed Top Section - New Task & Chatbots */}
        <div className="p-4 space-y-6 flex-shrink-0">
          {/* New Video Task 按钮（仅按钮，无重复标题） */}
          <div>
            <Button
              type="button"
              className={collapsed
                ? 'w-8 h-8 p-0 rounded-full text-white bg-gradient-to-b from-pink-500 via-fuchsia-500 to-purple-600 hover:from-pink-400 hover:via-fuchsia-400 hover:to-purple-500 dark:from-pink-600 dark:via-fuchsia-600 dark:to-purple-700 dark:hover:from-pink-500 dark:hover:via-fuchsia-500 dark:hover:to-purple-600'
                : 'w-full justify-start apple-button text-primary-foreground dark:bg-primary dark:text-primary-foreground dark:border-primary'}
              onClick={(event) => {
                event.stopPropagation()
                onNewTask()
              }}
            >
              <Plus className={`w-4 h-4 shrink-0 ${collapsed ? 'text-white' : ''}`} />
              {!collapsed && <span className="ml-2 truncate">{t('newTask')}</span>}
            </Button>
          </div>

          {/* 搜索聊天入口 */}
          {onOpenSearch && (
            <div>
              <Button
                variant="ghost"
                onClick={(e) => { e.stopPropagation(); onOpenSearch() }}
                className={`${
                  collapsed
                    ? 'w-8 h-8 p-0 rounded-full'
                    : 'w-full justify-start text-muted-foreground hover:text-foreground'
                } hover:bg-black/10 dark:hover:bg-white/10`}
                title={t('searchChats')}
              >
                <Search className="w-4 h-4 shrink-0" />
                {!collapsed && <span className="ml-2 truncate">{t('searchChats')}</span>}
              </Button>
            </div>
          )}
        </div>

        {/* Scrollable Chats Section */}
        {!collapsed && (
          <div className="grow h-0 flex flex-col overflow-hidden px-4 pb-4">
            <h3 className="text-sm font-medium text-muted-foreground dark:text-foreground mb-3 flex-shrink-0">
              {t('chats')}
            </h3>
            {/* Mobile fullscreen: native scroll; Desktop: Radix ScrollArea */}
            {isMobileFullScreen ? (
              <div className="grow h-0 overflow-y-auto overscroll-contain touch-pan-y" style={{ WebkitOverflowScrolling: 'touch' }} onScroll={handleScroll}>
                <div className="space-y-2 pb-4" ref={scrollAreaRef}>
                  <TooltipProvider delayDuration={300}>
                    {mergedChats.map(chat => (
                      <Card
                        key={chat.id}
                        ref={selectedChat === chat.id ? selectedChatRef : null}
                        className={`group p-4 cursor-pointer transition-all duration-200 font-inter relative bg-transparent border-0 shadow-none hover:shadow-none dark:hover:shadow-md ${
                          selectedChat === chat.id
                            ? 'bg-primary/10 dark:bg-primary/20 border-l-2 border-l-primary hover:bg-primary/15 dark:hover:bg-primary/25'
                            : chat.isUnloaded
                              ? 'opacity-70 hover:bg-black/5 dark:hover:bg-white/5'
                              : 'hover:bg-black/5 dark:hover:bg-white/5'
                        }`}
                        onClick={() =>{  onSelectChat(chat.id) }}
                      >
                        {/* Mobile full-screen chat item content - reuse same structure */}
                        <div className="flex items-start gap-3 flex-1 min-w-0">
                          <div className="flex-shrink-0 w-10 h-10 rounded-full overflow-hidden bg-muted">
                            <img
                              src={chat.previewImageUrl || aiAvatar}
                              alt=""
                              className="w-full h-full object-cover"
                              onError={(e) => { e.currentTarget.src = aiAvatar }}
                            />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium text-sm text-foreground truncate">{chat.title}</span>
                              {isConversationPinned(chat.id) && <Pin className="w-3 h-3 text-primary flex-shrink-0" />}
                            </div>
                            {chat.preview && (
                              <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{chat.preview}</p>
                            )}
                          </div>
                        </div>
                      </Card>
                    ))}
                    {isLoadingChats && (
                      <div className="flex justify-center py-4">
                        <Loader2 className="h-5 w-5 animate-spin text-primary" />
                      </div>
                    )}
                    {!isLoadingChats && hasMoreChats && onLoadMore && (
                      <button onClick={onLoadMore} className="w-full text-center py-3 text-sm text-muted-foreground hover:text-foreground">
                        {t('loadMore')}
                      </button>
                    )}
                  </TooltipProvider>
                </div>
              </div>
            ) : (
              <ScrollArea className="flex-1 min-h-0" onScrollCapture={handleScroll}>
                <div className="space-y-2 pr-4 pb-4" ref={scrollAreaRef}>
                  <TooltipProvider delayDuration={300}>
                    {mergedChats.map(chat => (
                      <Card
                        key={chat.id}
                        ref={selectedChat === chat.id ? selectedChatRef : null}
                        className={`group p-3 cursor-pointer transition-all duration-200 font-inter relative bg-transparent border-0 shadow-none hover:shadow-none dark:hover:shadow-md ${
                          selectedChat === chat.id
                            ? 'bg-primary/10 dark:bg-primary/20 border-l-2 border-l-primary hover:bg-primary/15 dark:hover:bg-primary/25'
                            : chat.isUnloaded
                              ? 'opacity-70 hover:bg-black/5 dark:hover:bg-white/5'
                              : 'hover:bg-black/5 dark:hover:bg-white/5'
                        }`}
                        onClick={() =>{  onSelectChat(chat.id) }}
                      >
                        <div className={'flex items-start gap-2 flex-1 min-w-0 justify-between'}>
                          <div className="flex items-start gap-2 flex-1 min-w-0">
                            {isConversationPinned(chat.id) && (
                              <Pin className="w-3.5 h-3.5 text-primary flex-shrink-0 mt-0.5" />
                            )}
                            <div className="flex-1 min-w-0 pr-2">
                              <h4 className={'font-medium leading-tight text-sm'}>
                                <span
                                  className="break-words line-clamp-2"
                                >
                                  {chat.title}
                                </span>
                              </h4>
                              {(chat.last_active_at || chat.created_at) && (
                                <span className="mt-0.5 block text-[11px] leading-none text-muted-foreground/70">
                                  {formatChatTime(chat.last_active_at || chat.created_at, language)}
                                </span>
                              )}
                            </div>
                          </div>
                          {(showConversationActions || showDeleteAction) && <DropdownMenu>
                            <DropdownMenuTrigger
                              asChild
                              onClick={(e) =>{  e.stopPropagation() }}
                            >
                              <Button
                                variant="ghost"
                                size="sm"
                                className={'h-6 w-6 p-0 hover:bg-white/20 transition-opacity flex-shrink-0 opacity-0 group-hover:opacity-100'}
                              >
                                <MoreHorizontal className="h-3 w-3" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                              align="end"
                              className="w-48 bg-card/95 backdrop-blur-md border-white/20"
                            >
                              {showConversationActions && <DropdownMenuItem
                                className="cursor-pointer"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  onTogglePin(chat.id, e)
                                }}
                              >
                                {isConversationPinned(chat.id) ? (
                                  <>
                                    <PinOff className="w-4 h-4 mr-2" />
                                    {t('unpin')}
                                  </>
                                ) : (
                                  <>
                                    <Pin className="w-4 h-4 mr-2" />
                                    {t('pin')}
                                  </>
                                )}
                              </DropdownMenuItem>}
                              {showConversationActions && onRerunChat && (
                                <DropdownMenuItem
                                  className="cursor-pointer"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    onRerunChat(chat)
                                  }}
                                >
                                  <RefreshCw className="w-4 h-4 mr-2" />
                                  {t('regenerate')}
                                </DropdownMenuItem>
                              )}
                              <DropdownMenuItem
                                className="cursor-pointer text-destructive focus:text-destructive"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  onDeleteChat(chat.id, e)
                                }}
                              >
                                <Trash2 className="w-4 h-4 mr-2 text-red-500" />
                                {t('delete')}
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>}
                        </div>
                      </Card>
                    ))}
                    {isLoadingChats && (
                      <div className="flex justify-center py-4">
                        <Loader2 className="h-5 w-5 animate-spin text-primary" />
                      </div>
                    )}
                  </TooltipProvider>
                </div>
              </ScrollArea>
            )}
          </div>
        )}
      </div>

      <div className="p-4">
        <TooltipProvider delayDuration={150}>
          <Tooltip>
            <Popover>
              <TooltipTrigger asChild>
                <PopoverTrigger asChild>
                  <Button variant="ghost" size="sm" className={collapsed ? 'h-8 w-8 p-0' : 'w-full justify-start'}>
                    <SettingsIcon className="h-4 w-4" />
                    {!collapsed && <span className="ml-2">{t('settings') || 'Settings'}</span>}
                  </Button>
                </PopoverTrigger>
              </TooltipTrigger>
              {collapsed && <TooltipContent side="right">{t('settings') || 'Settings'}</TooltipContent>}
              <PopoverContent className="w-52 rounded-lg border border-border bg-popover p-4" align="start" side="right" sideOffset={8}>
                <button type="button" className="flex w-full items-center justify-between gap-3 text-sm hover:opacity-80" onClick={() =>{  setLanguage(language === 'en' ? 'zh' : 'en') }}>
                  <span className="flex items-center gap-2"><Globe className="h-4 w-4" />{t('language') || 'Language'}</span>
                  <span className="text-xs text-muted-foreground">{language === 'en' ? 'English' : '中文'}</span>
                </button>
              </PopoverContent>
            </Popover>
          </Tooltip>
        </TooltipProvider>
      </div>
    </div>
  )
}
