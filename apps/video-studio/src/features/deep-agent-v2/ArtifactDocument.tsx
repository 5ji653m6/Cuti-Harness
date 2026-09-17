import { displayValue } from '../../utils/displayValue'
import { memo, useId, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useLanguage } from '../../i18n/LanguageContext'
import type { Language } from '../../i18n/translations'

const labels: Record<Language, Record<string, string>> = {
  zh: {
    title: '标题', name: '名称', summary: '概要', description: '描述', content: '正文',
    script: '剧本', story: '故事', outline: '大纲', chapters: '章节', scenes: '场景',
    shots: '镜头', characters: '角色', dialogue: '对白', narration: '旁白',
    prompt: '画面提示词', video_prompt: '视频提示词', image_prompt: '图片提示词',
    duration: '时长', duration_seconds: '时长（秒）', target_duration_seconds: '目标时长（秒）',
    location: '地点', action: '动作', appearance: '外貌', clothing: '服装',
    camera: '镜头语言', camera_movement: '运镜', transition: '转场',
    music: '音乐', audio: '音频', subtitles: '字幕', timeline: '时间线',
    start: '开始', end: '结束', text: '文字', language: '语言', style: '风格',
    aspect_ratio: '画幅', resolution: '分辨率', beat: '剧情节拍',
  },
  en: {
    title: 'Title', name: 'Name', summary: 'Summary', description: 'Description', content: 'Content',
    script: 'Script', story: 'Story', outline: 'Outline', chapters: 'Chapters', scenes: 'Scenes',
    shots: 'Shots', characters: 'Characters', dialogue: 'Dialogue', narration: 'Narration',
    prompt: 'Visual prompt', video_prompt: 'Video prompt', image_prompt: 'Image prompt',
    duration: 'Duration', duration_seconds: 'Duration (seconds)', target_duration_seconds: 'Target duration (seconds)',
    location: 'Location', action: 'Action', appearance: 'Appearance', clothing: 'Clothing',
    camera: 'Cinematography', camera_movement: 'Camera movement', transition: 'Transition',
    music: 'Music', audio: 'Audio', subtitles: 'Subtitles', timeline: 'Timeline',
    start: 'Start', end: 'End', text: 'Text', language: 'Language', style: 'Style',
    aspect_ratio: 'Aspect ratio', resolution: 'Resolution', beat: 'Story beat',
  },
}

const copy = {
  zh: { chapterNav: '章节导航', documentNav: '文档章节', tableHint: '表格 · 内容较宽时可左右滚动', tableLabel: '内容表格，可横向滚动', nested: '查看嵌套内容', yes: '是', no: '否', empty: '暂无内容', collapse: '收起列表', expand: '展开全部', items: '项', raw: '原始 JSON' },
  en: { chapterNav: 'Sections', documentNav: 'Document sections', tableHint: 'Table · scroll horizontally for wide content', tableLabel: 'Scrollable content table', nested: 'View nested content', yes: 'Yes', no: 'No', empty: 'No content', collapse: 'Collapse list', expand: 'Show all', items: 'items', raw: 'Raw JSON' },
} satisfies Record<Language, Record<string, string>>

/** Decode complete JSON documents, including fenced or string-encoded outputs. */
function parseDocument(source: string): unknown {
  let value: unknown = source
  for (let pass = 0; pass < 3 && typeof value === 'string'; pass++) {
    const candidate = value.trim().replace(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i, '$1').trim()
    if (!['[', '{', '"'].includes(candidate.charAt(0))) break
    try { value = JSON.parse(candidate) } catch { break }
  }
  return value
}

function MarkdownText({ text, language }: { text: string; language: Language }) {
  const scope = useId()
  const headings = useMemo(() => {
    let fenced = false
    return text.split('\n').flatMap((line, index) => {
      if (/^\s*(```|~~~)/.test(line)) { fenced = !fenced; return [] }
      const match = fenced ? null : /^#{2,3}\s+(.+)/.exec(line)
      return match?.[1] ? [{ label: match[1].replace(/[*`]/g, ''), id: `${scope}-${index + 1}` }] : []
    })
  }, [scope, text])
  const navigation = headings.length >= 4 ? <details className="mb-5 rounded-xl border border-border/60 bg-muted/20 p-3">
    <summary className="cursor-pointer text-xs font-medium text-muted-foreground">{copy[language].chapterNav} · {headings.length}</summary>
    <nav aria-label={copy[language].documentNav} className="mt-3 grid gap-1 sm:grid-cols-2">{headings.map(heading => <button key={heading.id} type="button" className="rounded-md px-2 py-1.5 text-left text-xs leading-5 hover:bg-muted focus-visible:outline focus-visible:outline-2" onClick={() => document.getElementById(heading.id)?.scrollIntoView({ block: 'start' })}>{heading.label}</button>)}</nav>
  </details> : null
  return <div className="artifact-prose min-w-0 whitespace-normal break-words text-sm leading-7 text-foreground/90 [&_p]:my-3 [&_p]:whitespace-pre-wrap [&_h1]:mb-5 [&_h1]:mt-7 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-3 [&_h2]:mt-6 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-5 [&_h3]:font-semibold [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-6 [&_li]:my-1 [&_blockquote]:my-4 [&_blockquote]:border-l-2 [&_blockquote]:border-primary/50 [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-muted/50 [&_pre]:p-4 [&_pre]:text-xs [&_hr]:my-6 [&_strong]:font-semibold">
    {navigation}
    <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} components={{
      h2: ({ node, children }) => <h2 id={`${scope}-${node?.position?.start.line}`} className="scroll-mt-4 border-b border-border/50 pb-2">{children}</h2>,
      h3: ({ node, children }) => <h3 id={`${scope}-${node?.position?.start.line}`} className="scroll-mt-4">{children}</h3>,
      table: ({ children }) => <div className="my-5 min-w-0">
        <p className="mb-2 text-[11px] text-muted-foreground">{copy[language].tableHint}</p>
        <div role="region" aria-label={copy[language].tableLabel} tabIndex={0} className="max-w-full overflow-x-auto rounded-xl border border-border/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
          <table className="w-full border-collapse text-left text-sm leading-6">{children}</table>
        </div>
      </div>,
      thead: ({ children }) => <thead className="bg-muted/60 text-foreground">{children}</thead>,
      th: ({ children, style }) => <th style={style} scope="col" className="min-w-32 border-b border-border/70 px-4 py-3 align-top text-xs font-semibold">{children}</th>,
      td: ({ children, style }) => <td style={style} className="min-w-40 border-b border-border/40 px-4 py-3 align-top text-foreground/85 first:min-w-28 first:font-medium">{children}</td>,
      tr: ({ children }) => <tr className="even:bg-muted/20 hover:bg-muted/30">{children}</tr>,
      a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-4">{children}</a>,
    }}>{text}</ReactMarkdown>
  </div>
}

function ValueView({ value, language, depth = 0 }: { value: unknown; language: Language; depth?: number }) {
  const [expanded, setExpanded] = useState(false)
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>
  if (typeof value === 'string') return <MarkdownText text={value} language={language} />
  if (typeof value !== 'object') return <span className="text-sm leading-7">{typeof value === 'boolean' ? (value ? copy[language].yes : copy[language].no) : displayValue(value)}</span>
  if (depth >= 6) return <details className="rounded-lg border border-border/50 p-3"><summary className="cursor-pointer text-sm">{copy[language].nested}</summary><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(value, null, 2)}</pre></details>
  if (Array.isArray(value)) {
    const shown: unknown[] = expanded ? value : value.slice(0, 8)
    return <div className="space-y-3">
      {shown.map((item, index) => <section key={index} className="flex min-w-0 gap-3 rounded-xl border border-border/50 bg-muted/15 p-4">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">{index + 1}</span>
        <div className="min-w-0 flex-1"><ValueView value={item} language={language} depth={depth + 1} /></div>
      </section>)}
      {!value.length && <p className="text-sm text-muted-foreground">{copy[language].empty}</p>}
      {value.length > 8 && <button type="button" onClick={() =>{  setExpanded(!expanded) }} className="rounded-md px-2 py-1 text-sm text-primary hover:bg-muted focus-visible:outline focus-visible:outline-2">{expanded ? copy[language].collapse : `${copy[language].expand} ${value.length} ${copy[language].items}`}</button>}
    </div>
  }
  const fields: [string, unknown][] = Object.entries(value)
  const heading = fields.find(([key, item]) => ['title', 'name'].includes(key) && typeof item === 'string')
  return <div className="min-w-0">
    {heading && <h3 className="mb-4 whitespace-pre-wrap break-words text-base font-semibold leading-7">{displayValue(heading[1])}</h3>}
    <dl className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">{fields.filter(([key]) => key !== heading?.[0]).map(([key, item]) => <div key={key} className={typeof item === 'object' || (typeof item === 'string' && item.length > 60) ? 'min-w-0 sm:col-span-2' : 'min-w-0'}>
      <dt className="mb-1 break-words text-xs font-medium tracking-wide text-muted-foreground">{labels[language][key] || key.replace(/[_-]/g, ' ')}</dt>
      <dd className="min-w-0"><ValueView value={item} language={language} depth={depth + 1} /></dd>
    </div>)}</dl></div>
}

/** Readable generated content; raw data stays available without executing model HTML. */
export const ArtifactDocument = memo(function ArtifactDocument({ children }: { children: string }) {
  const { language } = useLanguage()
  const value = useMemo(() => parseDocument(children), [children])
  const [rawOpen, setRawOpen] = useState(false)
  const structured = value !== null && typeof value === 'object'
  return <div className="not-prose min-w-0" data-testid="artifact-document">
    <div className="max-h-[36rem] overflow-y-auto overscroll-contain pr-2 [overflow-wrap:anywhere]">
      <ValueView value={value} language={language} />
    </div>
    {structured && <details className="mt-5 border-t border-border/50 pt-3" onToggle={(event) =>{  setRawOpen(event.currentTarget.open) }}>
      <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">{copy[language].raw}</summary>
      {rawOpen && <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted/40 p-4 font-mono text-xs leading-5">{JSON.stringify(value, null, 2)}</pre>}
    </details>}
  </div>
})
