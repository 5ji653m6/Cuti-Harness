import { displayValue } from '@/utils/displayValue'
import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { ArtifactDocument } from './ArtifactDocument'
import {
  AlertTriangle, BookOpen, Check, CheckCircle2, ChevronDown, Circle, FileText, Film,
  Image, Images, ListChecks, Loader2, Music, RefreshCw, Scissors,
} from 'lucide-react'
import { toast } from 'sonner'
import { useLanguage } from '@/i18n/LanguageContext'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  videoRuntimeClient,
  type RuntimeWorkspace,
} from '@/features/video-runtime/client'
import type { RuntimeProductionProgress } from './AgentProductionProgress'
import {
  artifactTitle,
  capabilityLabel,
  interpolate,
  planStepLabel,
  resultCountLabel,
  runtimeMessage,
  statusLabel,
  type Translate,
} from './labels'
import type { DeepAgentArtifact, DeepAgentSnapshot, DeepAgentTask } from './types'

function formatTimestamp(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00.00'
  const whole = Math.floor(seconds)
  const mins = Math.floor(whole / 60)
  const secs = whole % 60
  const frac = Math.floor((seconds - whole) * 100)
  return `${mins}:${displayValue(secs).padStart(2, '0')}.${displayValue(frac).padStart(2, '0')}`
}

function useWhenVisible(eager = false) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [visible, setVisible] = useState(eager)
  useEffect(() => {
    if (eager || visible) return
    const node = hostRef.current
    if (!node) return
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry?.isIntersecting) return
      setVisible(true)
      observer.disconnect()
    }, { rootMargin: '240px 0px' })
    observer.observe(node)
    return () => observer.disconnect()
  }, [eager, visible])
  return { hostRef, visible }
}

function VideoFramePicker({
  mediaUri,
  title,
  extracting,
  eager = false,
  onExtract,
}: {
  mediaUri: string
  title?: string
  extracting: boolean
  eager?: boolean
  onExtract: (timestamp: number) => void | Promise<void>
}) {
  const { t } = useLanguage()
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const { hostRef, visible } = useWhenVisible(eager)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  const capturePreview = () => {
    const video = videoRef.current
    if (!video || !video.videoWidth) return
    try {
      const canvas = document.createElement('canvas')
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      const context = canvas.getContext('2d')
      if (!context) return
      context.drawImage(video, 0, 0, canvas.width, canvas.height)
      setPreviewUrl(canvas.toDataURL('image/jpeg', 0.92))
    } catch {
      setPreviewUrl(null)
    }
  }

  return (
    <div className="space-y-3">
      <div
        ref={hostRef}
        className="flex min-h-[12rem] max-h-[calc(100dvh-14rem)] w-full min-w-0 items-center justify-center overflow-hidden rounded-lg bg-black"
      >
        {visible ? (
          <video
            ref={videoRef}
            key={mediaUri}
            src={mediaUri}
            controls
            playsInline
            preload="metadata"
            className="block h-auto max-h-[calc(100dvh-14rem)] max-w-full object-contain"
            onLoadedMetadata={(event) => {
              setDuration(event.currentTarget.duration || 0)
              setCurrentTime(event.currentTarget.currentTime || 0)
            }}
            onTimeUpdate={(event) =>{  setCurrentTime(event.currentTarget.currentTime || 0) }}
            onSeeked={capturePreview}
            onPause={capturePreview}
          />
        ) : (
          <Film className="h-8 w-8 text-white/40" />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="font-mono text-[11px]">
          {formatTimestamp(currentTime)}
          {duration > 0 ? ` / ${formatTimestamp(duration)}` : ''}
        </Badge>
        <Button
          size="sm"
          variant="secondary"
          disabled={extracting || !mediaUri}
          onClick={() => {
            capturePreview()
            void onExtract(videoRef.current?.currentTime ?? currentTime)
          }}
        >
          {extracting ? (
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Scissors className="mr-1 h-3.5 w-3.5" />
          )}
          {t('da.workspace.useThisFrame')}
        </Button>
        <span className="text-xs text-muted-foreground">
          {t('da.workspace.scrubHint')}
        </span>
      </div>
      {previewUrl && (
        <div className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/30 p-2">
          <img
            src={previewUrl}
            alt={title
              ? interpolate(t('da.workspace.framePreviewTitled'), { title })
              : t('da.workspace.framePreview')}
            className="h-20 w-auto rounded object-contain"
          />
          <p className="pt-1 text-xs text-muted-foreground">
            {t('da.workspace.framePreviewHint')}
          </p>
        </div>
      )}
    </div>
  )
}

const isMediaUrl = (value: string | null | undefined, type: 'image' | 'audio' | 'video') => {
  if (!value) return false
  const patterns = {
    image: /\.(png|jpe?g|webp|gif|bmp|svg)(\?|#|$)/i,
    audio: /\.(mp3|wav|m4a|ogg|aac|flac)(\?|#|$)/i,
    video: /\.(mp4|webm|mov|m3u8|mkv)(\?|#|$)/i,
  }
  if (patterns[type].test(value)) return true
  if (value.startsWith('blob:')) return true
  // Path heuristics for local storage URLs without clear extensions.
  if (type === 'video' && /\/(videos?|media\/.*concat_|files\/videos)\//i.test(value)) return true
  if (type === 'image' && /\/(images?|files\/media\/.*\.(webp|png|jpe?g))/i.test(value)) return true
  return false
}

const artifactMediaUri = (artifact: DeepAgentArtifact): string | undefined => {
  if (artifact.uri) return artifact.uri
  const meta = artifact.metadata
  // Prefer typed media fields before generic url/uri.
  const preferredKeys = artifact.type.includes('video')
    ? ['video_url', 'result_url', 'uri', 'url']
    : artifact.type === 'image' || artifact.type === 'keyframe' || artifact.type === 'character'
      ? ['image_url', 'character_image_url', 'uri', 'url']
      : artifact.type === 'music'
        ? ['audio_url', 'uri', 'url']
        : ['video_url', 'image_url', 'audio_url', 'result_url', 'url', 'uri']
  for (const key of preferredKeys) {
    const value = meta[key]
    if (typeof value === 'string' && value) return value
  }
  for (const key of ['videos', 'images', 'characters', 'audio']) {
    const items = meta[key]
    if (!Array.isArray(items)) continue
    for (const item of items) {
      if (!item || typeof item !== 'object') continue
      for (const mediaKey of ['video_url', 'image_url', 'character_image_url', 'audio_url', 'url', 'uri']) {
        const value = (item as Record<string, unknown>)[mediaKey]
        if (typeof value === 'string' && value) return value
      }
    }
  }
  return undefined
}

const asRecord = (value: unknown): Record<string, unknown> => (
  value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
)

const stringField = (...values: unknown[]): string => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

const buildStepEntityNames = (videoSpec: Record<string, unknown> | null | undefined) => {
  const names: Record<string, string> = {}
  const visit = (value: unknown, depth = 0) => {
    if (depth > 8 || !value || typeof value !== 'object') return
    if (Array.isArray(value)) {
      value.forEach((item) =>{  visit(item, depth + 1) })
      return
    }
    const entity = asRecord(value)
    if (Object.keys(entity).length > 0) {
      const id = stringField(entity.id, entity.character_id, entity.scene_id, entity.shot_id)
      const name = stringField(entity.name, entity.display_name, entity.title)
      if (id && name) names[id] = name
      Object.values(entity).forEach((item) =>{  visit(item, depth + 1) })
    }
  }
  visit(videoSpec)
  return names
}

const isResearchArtifact = (artifact: DeepAgentArtifact) => {
  if (artifact.type === 'research') return true
  const meta = asRecord(artifact.metadata)
  return (typeof meta.research_summary === 'string' && Array.isArray(meta.directions))
}

const researchLinks = (items: unknown, keys: { title?: string; url?: string; note?: string }) => {
  if (!Array.isArray(items)) return []
  return items.flatMap((item, index) => {
    const row = asRecord(item)
    const url = keys.url ? stringField(row[keys.url]) : ''
    const title = (keys.title ? stringField(row[keys.title]) : '') || url || `Item ${index + 1}`
    const note = keys.note ? stringField(row[keys.note]) : ''
    if (!url && !title) return []
    return [{ key: `${index}-${title}`, title, url, note }]
  })
}

function ResearchDetails({ artifact }: { artifact: DeepAgentArtifact }) {
  const { t } = useLanguage()
  const meta = asRecord(artifact.metadata)
  const summary = stringField(meta.research_summary, artifact.summary)
  const landscape = asRecord(meta.landscape)
  const gaps = Array.isArray(landscape.underserved_gaps)
    ? landscape.underserved_gaps.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : []
  const existing = researchLinks(landscape.existing_content, { title: 'title', url: 'url', note: 'what_it_misses' })
  const directions = Array.isArray(meta.directions) ? meta.directions : []
  const sources = researchLinks(meta.sources, { title: 'title', url: 'url', note: 'used_for' })
  if (!summary && directions.length === 0 && sources.length === 0) return null
  return (
    <div className="space-y-4">
      {summary ? (
        <div className="prose prose-sm max-w-none text-foreground dark:prose-invert">
          <ReactMarkdown>{summary}</ReactMarkdown>
        </div>
      ) : null}
      {gaps.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">{t('da.workspace.researchGaps')}</p>
          <ul className="list-disc space-y-1 pl-4 text-sm">
            {gaps.map(gap => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      )}
      {directions.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">{t('da.workspace.researchDirections')}</p>
          {directions.map((item, index) => {
            const row = asRecord(item)
            const name = stringField(row.name) || interpolate(t('da.workspace.researchDirectionN'), { n: index + 1 })
            const type = stringField(row.type)
            const hook = stringField(row.hook)
            const motion = stringField(row.motion_commitment)
            const audio = stringField(row.mood_direction)
            const refs = researchLinks(row.visual_references, { title: 'description', url: 'url', note: 'what_works' })
            return (
              <div key={`${artifact.id}-dir-${index}`} className="space-y-1 rounded-md border border-border/50 p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium">{name}</p>
                  {type ? <Badge variant="outline" className="font-normal">{type}</Badge> : null}
                </div>
                {hook ? <p className="text-sm leading-snug">{hook}</p> : null}
                {motion ? <p className="text-xs text-muted-foreground">{motion}</p> : null}
                {audio ? <p className="text-xs text-muted-foreground">{audio}</p> : null}
                {refs.length > 0 && (
                  <div className="space-y-0.5">
                    {refs.map(ref => (
                      <p key={ref.key} className="text-xs">
                        {ref.url ? (
                          <a href={ref.url} target="_blank" rel="noreferrer" className="text-primary underline-offset-4 hover:underline">
                            {ref.title}
                          </a>
                        ) : ref.title}
                        {ref.note ? <span className="text-muted-foreground"> — {ref.note}</span> : null}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
      {existing.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">{t('da.workspace.researchExistingWork')}</p>
          {existing.map(work => (
            <p key={work.key} className="text-sm">
              {work.url ? (
                <a href={work.url} target="_blank" rel="noreferrer" className="text-primary underline-offset-4 hover:underline">
                  {work.title}
                </a>
              ) : work.title}
              {work.note ? <span className="text-muted-foreground"> — {work.note}</span> : null}
            </p>
          ))}
        </div>
      )}
      {sources.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">{t('da.workspace.researchSources')}</p>
          <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border/50 p-2">
            {sources.map(source => (
              <p key={source.key} className="text-xs">
                {source.url ? (
                  <a href={source.url} target="_blank" rel="noreferrer" className="text-primary underline-offset-4 hover:underline">
                    {source.title}
                  </a>
                ) : source.title}
                {source.note ? <span className="text-muted-foreground"> — {source.note}</span> : null}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const isStoryArtifact = (artifact: DeepAgentArtifact) => {
  if (isResearchArtifact(artifact)) return false
  return ['story', 'story_outline', 'outline', 'script'].includes(artifact.type)
    || /story|script|outline|剧本|脚本|梗概/i.test(artifact.title || '')
}

const isImageArtifact = (artifact: DeepAgentArtifact) => {
  if (artifact.type.includes('video')) return false
  const uri = artifactMediaUri(artifact)
  // Character artifacts are image cards only when a preview URL exists.
  if (artifact.type === 'character') return Boolean(uri)
  if (['image', 'keyframe', 'poster'].includes(artifact.type)) return true
  return Boolean(uri && isMediaUrl(uri, 'image') && !isMediaUrl(uri, 'video'))
}

const isVideoArtifact = (artifact: DeepAgentArtifact) => {
  if (artifact.type === 'video_spec') return false
  if (isVideoAnalysisArtifact(artifact)) return false
  if (artifact.type.includes('video') || artifact.type === 'video_segment') return true
  const uri = artifactMediaUri(artifact)
  return Boolean(uri && isMediaUrl(uri, 'video'))
}

type WorkspaceTab = 'process' | 'final' | 'assets' | 'script'
type AssetKind = 'all' | 'image' | 'video' | 'audio' | 'text' | 'other'

const isExplicitFinalVideoArtifact = (artifact: DeepAgentArtifact): boolean => {
  if (!isVideoArtifact(artifact)) return false
  const metadata = asRecord(artifact.metadata)
  const values = [
    artifact.type,
    artifact.title,
    metadata.plan_step_id,
    metadata.output_role,
    metadata.artifact_role,
    metadata.capability,
  ].filter((value): value is string => typeof value === 'string')
  return values.some(value => (
    /(?:^|[\s._-])(?:final|master|assembled?|concat(?:enated)?|export)(?:$|[\s._-])/i.test(value)
    || /最终|成片|总片|合成/.test(value)
  ))
}

const containsInternalModelPayload = (artifact: DeepAgentArtifact): boolean => {
  const values = [artifact.summary, ...Object.values(artifact.metadata)]
    .filter((value): value is string => typeof value === 'string')
  return values.some(value =>
    value.includes('encrypted_content')
    || /"type"\s*:\s*"(?:reasoning|thinking)"/.test(value)
    || /'type'\s*:\s*'(?:reasoning|thinking)'/.test(value)
    || /gAAAA[A-Za-z0-9_]{20,}/.test(value),
  )
}

const isInternalExecutionArtifact = (artifact: DeepAgentArtifact): boolean => {
  const type = (artifact.type || '').trim().toLowerCase().replace(/[.\s-]+/g, '_')
  if ([
    'action_suggestions',
    'reasoning',
    'thinking',
    'trace',
    'event_log',
    'operation_log',
    'task_log',
    'model_request',
    'model_response',
    'llm_request',
    'llm_response',
    'tool_input',
    'tool_output',
    'tool_request',
    'tool_response',
  ].includes(type)) return true

  const title = (artifact.title || '').trim()
  return /^(?:model|llm|tool)\s+(?:request|response|input|output)$|^(?:execution\s+)?trace$/i.test(title)
}

const normalizeArtifactType = (type: string): string =>
  (type || '').trim().toLowerCase().replace(/[.\s-]+/g, '_')

/** Text-generation results are user documents, not generic execution records. */
const isReadableTextArtifact = (artifact: DeepAgentArtifact): boolean => {
  const type = normalizeArtifactType(artifact.type)
  return [
    'text',
    'document',
    'markdown',
    'creative_brief',
    'product_brief',
    'shot_plan',
    'storyboard_plan',
    'video_spec',
    'characters',
    'character_definition',
    'scene',
    'scenes',
    'shot',
    'storyboard',
    'timeline',
    'subtitle',
    'subtitles',
    'validation',
    'validation_result',
    'report',
  ].includes(type)
}

const isAudioArtifact = (artifact: DeepAgentArtifact): boolean => [
  'audio',
  'audio_cut',
  'audio_bgm',
  'bgm',
  'music',
  'narration',
  'sound_effect',
  'speech',
  'tts',
  'voiceover',
].includes(normalizeArtifactType(artifact.type))

const isAudioAnalysisArtifact = (artifact: DeepAgentArtifact): boolean => [
  'audio_analysis',
  'audiomap',
  'audio_map',
].includes(normalizeArtifactType(artifact.type))

const isVideoAnalysisArtifact = (artifact: DeepAgentArtifact): boolean => [
  'videomap',
  'video_map',
  'video_analysis',
].includes(normalizeArtifactType(artifact.type))

const stringList = (value: unknown): string => {
  if (typeof value === 'string') return value.trim()
  if (!Array.isArray(value)) return ''
  return value
    .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    .join(' · ')
}

const boolField = (...values: unknown[]): boolean | undefined => {
  for (const value of values) {
    if (typeof value === 'boolean') return value
    if (value === 'true' || value === 'false') return value === 'true'
  }
  return undefined
}

const vocalGenderLabel = (value: string, t: Translate): string => {
  if (value === 'f') return t('da.workspace.vocalFemale')
  if (value === 'm') return t('da.workspace.vocalMale')
  return value
}

function MetaField({ label, value }: { label: string; value?: string }) {
  if (!value) return null
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-semibold text-foreground">{label}</p>
      <p className="mt-0.5 whitespace-pre-wrap break-words text-xs leading-5 text-muted-foreground">{value}</p>
    </div>
  )
}

function MusicArtifactDetails({ artifact }: { artifact: DeepAgentArtifact }) {
  const { t } = useLanguage()
  const meta = artifact.metadata
  const params = asRecord(meta.generation_parameters)
  const resolved = asRecord(meta.resolved_generation_parameters)
  const lyrics = stringField(meta.lyrics, meta.generated_lyrics, params.lyrics, resolved.lyrics)
  const style = stringField(meta.tags, params.tags, resolved.tags, meta.style)
  const prompt = stringField(params.prompt, resolved.prompt, meta.prompt)
  const title = stringField(meta.clip_title, params.title, resolved.title)
  const vocal = stringField(meta.vocal_gender, params.vocal_gender, resolved.vocal_gender)
  const instrumental = boolField(
    meta.make_instrumental,
    meta.instrumental,
    params.make_instrumental,
    params.instrumental,
    resolved.make_instrumental,
    resolved.instrumental,
  )
  const lyricsOrPrompt = lyrics || (instrumental ? '' : prompt)
  const structurePrompt = instrumental ? prompt : (lyrics ? prompt : '')
  if (!artifact.summary && !lyricsOrPrompt && !style && !title && vocal === '' && instrumental === undefined) {
    return null
  }
  return (
    <div className="space-y-3">
      {artifact.summary ? (
        <p className="text-xs text-muted-foreground">{artifact.summary}</p>
      ) : null}
      {instrumental === true ? (
        <Badge variant="outline" className="text-[10px]">{t('da.workspace.instrumental')}</Badge>
      ) : null}
      <MetaField label={t('da.workspace.songTitle')} value={title} />
      <MetaField label={t('da.workspace.musicStyle')} value={style} />
      <MetaField
        label={t('da.workspace.vocalGender')}
        value={vocal ? vocalGenderLabel(vocal, t) : ''}
      />
      <MetaField label={t('da.workspace.lyrics')} value={lyricsOrPrompt} />
      {structurePrompt && structurePrompt !== lyricsOrPrompt ? (
        <MetaField label={t('da.workspace.musicPrompt')} value={structurePrompt} />
      ) : null}
    </div>
  )
}

function AudioAnalysisDetails({ artifact }: { artifact: DeepAgentArtifact }) {
  const { t } = useLanguage()
  const meta = artifact.metadata
  const sections = Array.isArray(meta.sections) ? meta.sections : []
  const segments = Array.isArray(meta.segments) ? meta.segments : []
  const instrumental = boolField(meta.is_instrumental)
  const duration = typeof meta.audio_duration_sec === 'number'
    ? `${meta.audio_duration_sec}s`
    : stringField(meta.audio_duration_sec, meta.duration)
  return (
    <div className="space-y-3">
      {artifact.summary ? (
        <p className="text-xs text-muted-foreground">{artifact.summary}</p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <MetaField label={t('da.workspace.songName')} value={stringField(meta.song_name)} />
        <MetaField label={t('da.workspace.genre')} value={stringField(meta.genre)} />
        <MetaField label={t('da.workspace.globalBpm')} value={meta.global_bpm == null ? '' : displayValue(meta.global_bpm)} />
        <MetaField label={t('da.workspace.globalEmotion')} value={stringField(meta.global_emotion)} />
        <MetaField label={t('da.workspace.suggestedTheme')} value={stringField(meta.suggested_global_theme)} />
        <MetaField label={t('da.workspace.suggestedPalette')} value={stringField(meta.suggested_color_palette)} />
        <MetaField label={t('da.workspace.audioDuration')} value={duration} />
        <MetaField
          label={t('da.workspace.isInstrumental')}
          value={instrumental == null ? '' : instrumental ? t('da.workspace.yes') : t('da.workspace.no')}
        />
        <MetaField label={t('da.workspace.language')} value={stringField(meta.language)} />
      </div>
      <MetaField label={t('da.workspace.transcriptionText')} value={stringField(meta.text)} />
      {sections.length > 0 ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold text-foreground">{t('da.workspace.sections')}</p>
          {sections.map((item, index) => {
            const row = asRecord(item)
            const start = row.start_sec ?? row.start
            const end = row.end_sec ?? row.end
            return (
              <div key={`section-${index}`} className="rounded-md border border-border/60 bg-muted/20 p-2 space-y-1">
                <p className="text-xs font-medium">
                  {stringField(row.section_type, `${t('da.workspace.section')} ${index + 1}`)}
                  {start != null && end != null ? ` · ${displayValue(start)}–${displayValue(end)}s` : ''}
                </p>
                <p className="text-xs text-muted-foreground">{stringField(row.emotion, row.musical_features)}</p>
                <p className="text-xs text-muted-foreground">{stringField(row.suggested_visual_theme)}</p>
              </div>
            )
          })}
        </div>
      ) : null}
      {segments.length > 0 ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold text-foreground">{t('da.workspace.segments')}</p>
          <div className="max-h-64 space-y-2 overflow-y-auto">
            {segments.map((item, index) => {
              const row = asRecord(item)
              const start = row.start_sec ?? row.start
              const end = row.end_sec ?? row.end
              const gender = stringField(row.vocal_gender)
              const presence = boolField(row.vocal_presence)
              return (
                <div key={`segment-${index}`} className="rounded-md border border-border/60 bg-muted/20 p-2 space-y-1">
                  <p className="whitespace-pre-wrap text-xs">{stringField(row.text) || '—'}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {start != null && end != null ? `${displayValue(start)}–${displayValue(end)}s` : ''}
                    {row.emotion ? ` · ${displayValue(row.emotion)}` : ''}
                    {row.tempo ? ` · ${displayValue(row.tempo)}` : ''}
                    {presence == null ? '' : ` · ${presence ? t('da.workspace.vocalsYes') : t('da.workspace.vocalsNo')}`}
                    {gender ? ` · ${vocalGenderLabel(gender, t)}` : ''}
                  </p>
                </div>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function VideoAnalysisDetails({ artifact }: { artifact: DeepAgentArtifact }) {
  const { t } = useLanguage()
  const meta = artifact.metadata
  const shots = Array.isArray(meta.storyboard) ? meta.storyboard : []
  const characters = Array.isArray(meta.characters) ? meta.characters : []
  const duration = typeof meta.duration_sec === 'number'
    ? `${meta.duration_sec}s`
    : stringField(meta.duration_sec, meta.duration)
  return (
    <div className="space-y-3">
      {artifact.summary ? (
        <p className="text-xs text-muted-foreground">{artifact.summary}</p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <MetaField label={t('da.workspace.videoDuration')} value={duration} />
        <MetaField label={t('da.workspace.theme')} value={stringField(meta.theme)} />
        <MetaField label={t('da.workspace.overallStyle')} value={stringField(meta.overall_style)} />
        <MetaField label={t('da.workspace.globalEmotion')} value={stringField(meta.mood)} />
        <MetaField label={t('da.workspace.suggestedPalette')} value={stringField(meta.color_palette)} />
        <MetaField label={t('da.workspace.narrativeStructure')} value={stringField(meta.narrative_structure)} />
      </div>
      <MetaField label={t('da.workspace.productionTechniques')} value={stringList(meta.production_techniques)} />
      <MetaField label={t('da.workspace.visualElements')} value={stringList(meta.visual_elements)} />
      <MetaField label={t('da.workspace.onScreenText')} value={stringField(meta.spoken_or_on_screen_text)} />
      {stringField(meta.answer) ? (
        <MetaField label={t('da.workspace.analysisAnswer')} value={stringField(meta.answer)} />
      ) : null}
      {characters.length > 0 ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold text-foreground">{t('da.workspace.characters')}</p>
          {characters.map((item, index) => {
            const row = asRecord(item)
            return (
              <div key={`character-${index}`} className="rounded-md border border-border/60 bg-muted/20 p-2 space-y-1">
                <p className="text-xs font-medium">
                  {stringField(row.name, `${t('da.workspace.character')} ${index + 1}`)}
                  {stringField(row.role) ? ` · ${stringField(row.role)}` : ''}
                  {stringField(row.appearance_time) ? ` · ${stringField(row.appearance_time)}` : ''}
                </p>
                <p className="text-xs text-muted-foreground">
                  {stringField(row.description, row.appearance)}
                </p>
              </div>
            )
          })}
        </div>
      ) : null}
      {shots.length > 0 ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold text-foreground">{t('da.workspace.storyboard')}</p>
          <div className="max-h-80 space-y-2 overflow-y-auto">
            {shots.map((item, index) => {
              const row = asRecord(item)
              const start = row.start_sec ?? row.start ?? row.time_start
              const end = row.end_sec ?? row.end ?? row.time_end
              return (
                <div key={`shot-${index}`} className="rounded-md border border-border/60 bg-muted/20 p-2 space-y-1">
                  <p className="text-xs font-medium">
                    {start != null && end != null ? `${displayValue(start)}–${displayValue(end)}s` : `${t('da.workspace.shot')} ${index + 1}`}
                    {stringField(row.camera_angle) ? ` · ${stringField(row.camera_angle)}` : ''}
                  </p>
                  <p className="text-xs text-muted-foreground">{stringField(row.action, row.action_description)}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {[
                      stringField(row.on_screen),
                      stringField(row.production_method),
                      stringField(row.visual_style),
                      stringField(row.emotion),
                    ].filter(Boolean).join(' · ')}
                  </p>
                </div>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

const firstMarkdownHeading = (body: string): string | undefined => {
  const match = body.match(/^\s{0,3}#{1,3}\s+(.+?)\s*#*\s*$/m)
  return match?.[1]?.replace(/[*_`]/g, '').trim() || undefined
}

const readableTextTitle = (artifact: DeepAgentArtifact, body: string, t: Translate): string => {
  const metadataTitle = typeof artifact.metadata.title === 'string'
    ? artifact.metadata.title.trim()
    : ''
  const rawTitle = (artifact.title || '').trim()
  const titleIsGeneric = !rawTitle
    || /^(?:text|document|markdown|output|result|generated text)$/i.test(rawTitle)
  return metadataTitle
    || (!titleIsGeneric ? artifactTitle(rawTitle, artifact.type, t) : '')
    || firstMarkdownHeading(body)
    || t('da.workspace.generatedDocument')
}

const promptFromRecord = (value: unknown): string | undefined => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const row = value as Record<string, unknown>
  for (const key of ['prompt', 'generated_prompt', 'generation_prompt', 'final_prompt']) {
    const prompt = row[key]
    if (typeof prompt === 'string' && prompt.trim()) return prompt.trim()
  }
  return undefined
}

/**
 * Return only an explicitly persisted final generation prompt. Do not render
 * request bodies, tool arguments, provider responses, or the rest of `raw`.
 */
const artifactGenerationPrompt = (artifact: DeepAgentArtifact): string | undefined => {
  const metadata = artifact.metadata
  return promptFromRecord(metadata.resolved_generation_parameters)
    || promptFromRecord(metadata.generation_parameters)
    || promptFromRecord(metadata)
    || promptFromRecord(metadata.raw)
}

function GenerationPrompt({
  artifact,
  prompt: providedPrompt,
}: {
  artifact?: DeepAgentArtifact
  prompt?: string
}) {
  const { t } = useLanguage()
  const prompt = providedPrompt?.trim() || (artifact ? artifactGenerationPrompt(artifact) : undefined)
  return (
    <details className="group min-w-0 rounded-lg border border-border/60 bg-muted/20">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2.5 text-xs font-semibold text-foreground [&::-webkit-details-marker]:hidden">
        <span>{t('da.workspace.generationPrompt')}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-border/50 px-3 py-3">
        <p className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words text-xs leading-5 text-muted-foreground">
          {prompt || t('da.workspace.generationPromptUnavailable')}
        </p>
      </div>
    </details>
  )
}

const storyBody = (artifact: DeepAgentArtifact): string => {
  const meta = artifact.metadata
  for (const key of ['script', 'content', 'outline', 'story', 'text', 'body', 'markdown', 'description']) {
    const value = meta[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (value && typeof value === 'object') return JSON.stringify(value)
  }
  if (Array.isArray(meta.chapters) && meta.chapters.length > 0) {
    return JSON.stringify({ ...(meta.title ? { title: meta.title } : {}), chapters: meta.chapters })
  }
  if (typeof meta.chapters === 'object' && meta.chapters && !Array.isArray(meta.chapters)) {
    try {
      return '```json\n' + JSON.stringify(meta.chapters, null, 2) + '\n```'
    } catch {
      /* ignore */
    }
  }
  for (const key of ['content', 'timeline', 'result', 'data', 'payload']) {
    const value = meta[key]
    if (value === undefined || value === null || value === '') continue
    try {
      return '```json\n' + JSON.stringify(value, null, 2) + '\n```'
    } catch {
      /* ignore values that cannot be serialized */
    }
  }
  return (artifact.summary || '').trim()
}

const runIsTerminalFailed = (snapshot: DeepAgentSnapshot) =>
  snapshot.run.status === 'failed' || snapshot.run.status === 'cancelled'

const taskFailureIsSoft = (task: DeepAgentTask, snapshot: DeepAgentSnapshot) => {
  if (task.status !== 'failed') return false
  if (task.progress_message === 'Content moderation: user revision required') return false
  if (runIsTerminalFailed(snapshot)) return false
  // Later succeeded task with overlapping objective prefix ⇒ superseded by retry.
  const laterSuccess = snapshot.tasks.some(other =>
    other.id !== task.id
    && other.status === 'succeeded'
    && other.created_at >= task.created_at
    && other.capability_id === task.capability_id,
  )
  return laterSuccess || !['failed', 'cancelled', 'completed'].includes(snapshot.run.status)
}

export function DeepAgentArtifacts({
  snapshot,
  onSelectArtifact,
  onRefresh,
  onExtractFrame,
  onRuntimeProgress,
}: {
  snapshot: DeepAgentSnapshot
  onSelectArtifact: (versionId: string) => void
  onRefresh: () => void | Promise<void>
  onExtractFrame?: (options: {
    timestamp: number
    versionId?: string
    videoUrl?: string
  }) => Promise<unknown>
  onRuntimeProgress?: (progress: RuntimeProductionProgress | null) => void
}) {
  const { t } = useLanguage()
  const tRef = useRef(t)
  tRef.current = t
  const [runtimeWorkspace, setRuntimeWorkspace] = useState<RuntimeWorkspace | null>(null)
  const [workspaceError, setWorkspaceError] = useState<string | null>(null)
  const [workspaceLoading, setWorkspaceLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('process')
  const [assetKind, setAssetKind] = useState<AssetKind>('all')
  const [selectingArtifactId, setSelectingArtifactId] = useState<string | null>(null)
  const [extractingKey, setExtractingKey] = useState<string | null>(null)
  const latestResultRef = useRef<HTMLElement | null>(null)
  const projectId = snapshot.run.project_id
  const runtimeArtifacts = useMemo<DeepAgentArtifact[]>(() => (
    runtimeWorkspace?.artifacts
      .map(artifact => ({
        id: artifact.id,
        artifact_id: artifact.artifact_id,
        project_id: projectId,
        type: artifact.type,
        version: artifact.version,
        status: artifact.status,
        produced_by_task_id: displayValue(artifact.metadata?.build_id || 'video-runtime'),
        title: artifact.title || artifact.logicalId || artifact.type,
        summary: artifact.summary || '',
        uri: artifact.uri || null,
        metadata: {
          ...(artifact.metadata),
          logical_id: artifact.logicalId,
          runtime_status: artifact.status,
          runtime_selected: artifact.isSelected,
        },
        created_at: artifact.created_at || snapshot.run.updated_at,
      })) || []
  ), [projectId, runtimeWorkspace?.artifacts, snapshot.run.updated_at])
  const allArtifacts = useMemo(() => {
    const runtimeIds = new Set(runtimeArtifacts.map(item => item.id))
    return [...snapshot.artifacts.filter(item => !runtimeIds.has(item.id)), ...runtimeArtifacts]
  }, [runtimeArtifacts, snapshot.artifacts])

  useEffect(() => {
    if (!projectId) {
      setRuntimeWorkspace(null)
      setWorkspaceError(null)
      setWorkspaceLoading(false)
      return
    }
    setRuntimeWorkspace(null)
    setWorkspaceLoading(true)
    let active = true
    const isActive = () => active
    let inFlight = false
    let queued = false
    let debounceTimer: number | undefined
    const load = async () => {
      if (!isActive()) return
      if (inFlight) {
        queued = true
        return
      }
      inFlight = true
      setWorkspaceLoading(true)
      try {
        const next = await videoRuntimeClient.workspace(projectId)
        if (isActive()) {
          setRuntimeWorkspace(next)
          setWorkspaceError(null)
        }
      } catch {
        if (isActive()) {
          setWorkspaceError(tRef.current('da.runtime.requestFailedGeneric'))
        }
      } finally {
        inFlight = false
        if (isActive()) setWorkspaceLoading(false)
        if (isActive() && queued) {
          queued = false
          void load()
        }
      }
    }
    const scheduleLoad = () => {
      window.clearTimeout(debounceTimer)
      debounceTimer = window.setTimeout(() => void load(), 400)
    }
    void load()
    const events = new EventSource(
      `/api/video/projects/${encodeURIComponent(projectId)}/events?tail=1`,
    )
    const eventNames = [
      'build.queued', 'build.status', 'build.step_status', 'artifact.committed',
      'artifact.selected', 'project.version_committed', 'project.version_restored',
      'build.phase.started', 'build.phase.completed', 'build.checkpoint.waiting',
      'build.checkpoint.planning', 'build.checkpoint.resolved', 'build.checkpoint.failed',
      'video_spec.revised', 'plan.revised',
    ]
    eventNames.forEach((name) =>{  events.addEventListener(name, scheduleLoad) })
    return () => {
      active = false
      window.clearTimeout(debounceTimer)
      eventNames.forEach((name) =>{  events.removeEventListener(name, scheduleLoad) })
      events.close()
    }
  }, [projectId])

  const latestRuntimeBuild = runtimeWorkspace?.builds[0]
  const stepEntityNames = useMemo(
    () => buildStepEntityNames(runtimeWorkspace?.videoSpec),
    [runtimeWorkspace?.videoSpec],
  )
  useEffect(() => {
    if (!latestRuntimeBuild) {
      onRuntimeProgress?.(null)
      return
    }
    onRuntimeProgress?.({
      buildId: latestRuntimeBuild.buildId,
      status: latestRuntimeBuild.status,
      progress: latestRuntimeBuild.progress || 0,
      message: runtimeMessage(latestRuntimeBuild.message || latestRuntimeBuild.kind || '', t),
      error: latestRuntimeBuild.error,
      phase: runtimeWorkspace.currentBuildPhase,
      checkpoint: runtimeWorkspace.activeCheckpoint ? {
        status: runtimeWorkspace.activeCheckpoint.status,
        nextPhase: runtimeWorkspace.activeCheckpoint.next_phase,
        artifactCount: runtimeWorkspace.activeCheckpoint.artifact_summaries.length,
        unresolvedSections: runtimeWorkspace.activeCheckpoint.unresolved_sections,
      } : null,
      steps: latestRuntimeBuild.steps.map(step => ({
        id: step.id,
        name: planStepLabel(step.plan_step_id, t, stepEntityNames),
        status: step.status,
        error: step.error,
        skills: (step.resolved_skills || []).map(skill => skill.skill_id),
      })),
    })
  }, [
    latestRuntimeBuild,
    onRuntimeProgress,
    runtimeWorkspace?.activeCheckpoint,
    runtimeWorkspace?.currentBuildPhase,
    stepEntityNames,
    t,
  ])

  const selectedIds = useMemo(
    () => new Set([
      ...snapshot.selections.map(selection => selection.artifact_version_id),
      ...(runtimeWorkspace?.artifacts.filter(artifact => artifact.isSelected).map(artifact => artifact.id) || []),
    ]),
    [runtimeWorkspace?.artifacts, snapshot.selections],
  )
  const uploadedVideos = useMemo(
    () => (snapshot.run.input_files || []).filter(file =>
      file.type === 'video' && Boolean(file.url),
    ),
    [snapshot.run.input_files],
  )
  const uploadedImages = useMemo(
    () => (snapshot.run.input_files || []).filter(file =>
      file.type === 'image' && Boolean(file.url),
    ),
    [snapshot.run.input_files],
  )

  const handleExtractFrame = async (options: {
    key: string
    timestamp: number
    versionId?: string
    videoUrl?: string
  }) => {
    if (!onExtractFrame) {
      toast.error(t('da.workspace.frameExtractUnavailable'))
      return
    }
    setExtractingKey(options.key)
    try {
      await onExtractFrame({
        timestamp: options.timestamp,
        versionId: options.versionId,
        videoUrl: options.videoUrl,
      })
      toast.success(interpolate(t('da.workspace.frameSaved'), {
        time: formatTimestamp(options.timestamp),
      }))
    } catch {
      toast.error(t('da.workspace.frameExtractFailed'))
    } finally {
      setExtractingKey(null)
    }
  }

  // The Create workspace has one renderer. Every user-facing result, including
  // Video Runtime drafts, is classified by its Artifact type below.
  const visibleArtifacts = allArtifacts.filter(artifact => (
    !isInternalExecutionArtifact(artifact)
    && !containsInternalModelPayload(artifact)
  ))
  const videoCandidates = [...visibleArtifacts]
    .filter(artifact => isVideoArtifact(artifact) && Boolean(artifactMediaUri(artifact)))
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
  const latestVideoArtifact = videoCandidates[0]
  const selectedVideoArtifact = videoCandidates.find(artifact => selectedIds.has(artifact.id))
  const explicitFinalVideo = [...visibleArtifacts]
    .filter(artifact => isExplicitFinalVideoArtifact(artifact) && Boolean(artifactMediaUri(artifact)))
    .sort((left, right) => right.created_at.localeCompare(left.created_at))[0]
  const productionComplete = runtimeWorkspace
    ? latestRuntimeBuild?.status === 'completed'
    : snapshot.run.status === 'completed'
  const finalVideoArtifact = selectedVideoArtifact
    || explicitFinalVideo
    || (productionComplete ? latestVideoArtifact : undefined)
  const finalVideoUri = finalVideoArtifact
    ? artifactMediaUri(finalVideoArtifact)
    : undefined
  const finalVideoLogicalId = finalVideoArtifact
    ? displayValue(finalVideoArtifact.metadata?.logical_id) || finalVideoArtifact.artifact_id
    : undefined
  const finalVideoVersions = finalVideoLogicalId
    ? videoCandidates
      .filter(artifact => (
        displayValue(artifact.metadata?.logical_id) || artifact.artifact_id
      ) === finalVideoLogicalId)
      .sort((left, right) => (
        right.version - left.version || right.created_at.localeCompare(left.created_at)
      ))
    : []
  const finalVideoVersionIds = new Set(finalVideoVersions.map(artifact => artifact.id))
  const storyArtifacts = visibleArtifacts.filter(isStoryArtifact)
  const researchArtifacts = visibleArtifacts.filter(isResearchArtifact)
  const textArtifacts = visibleArtifacts.filter(artifact =>
    !isStoryArtifact(artifact)
    && !isResearchArtifact(artifact)
    && isReadableTextArtifact(artifact),
  )
  const imageArtifacts = visibleArtifacts.filter(artifact =>
    !isStoryArtifact(artifact)
    && !isResearchArtifact(artifact)
    && isImageArtifact(artifact),
  )
  const videoArtifacts = visibleArtifacts.filter(artifact =>
    !finalVideoVersionIds.has(artifact.id)
    && !isStoryArtifact(artifact)
    && !isResearchArtifact(artifact)
    && isVideoArtifact(artifact),
  )
  const videoAnalysisArtifacts = visibleArtifacts.filter(artifact =>
    !isStoryArtifact(artifact)
    && !isResearchArtifact(artifact)
    && isVideoAnalysisArtifact(artifact),
  )
  const audioArtifacts = visibleArtifacts.filter(artifact =>
    !isStoryArtifact(artifact)
    && !isResearchArtifact(artifact)
    && isAudioArtifact(artifact),
  )
  const analysisArtifacts = visibleArtifacts.filter(artifact =>
    !isStoryArtifact(artifact)
    && !isResearchArtifact(artifact)
    && isAudioAnalysisArtifact(artifact),
  )
  const otherArtifacts = visibleArtifacts.filter(artifact =>
    !isStoryArtifact(artifact)
    && !isResearchArtifact(artifact)
    && !isReadableTextArtifact(artifact)
    && !isImageArtifact(artifact)
    && !isVideoArtifact(artifact)
    && !isAudioArtifact(artifact)
    && !isAudioAnalysisArtifact(artifact)
    && !isVideoAnalysisArtifact(artifact),
  )
  // Runtime task objectives are execution labels; only legacy runs use them as document fallbacks.
  const segmentScripts = (runtimeWorkspace ? [] : [...snapshot.tasks])
    .filter(task =>
      /generate|seedance|video_gen|provider|ark_protocol|image\.|shot\.|keyframe\.|outline|scene|character/i
        .test(task.capability_id)
      && task.objective.trim().length > 20
      && !storyArtifacts.some(artifact => artifact.produced_by_task_id === task.id)
      && !researchArtifacts.some(artifact => artifact.produced_by_task_id === task.id),
    )
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
  const visibleTasks = runtimeWorkspace
    ? []
    : snapshot.tasks.filter(task =>
      task.status !== 'succeeded' ||
        !snapshot.artifacts.some(artifact => artifact.produced_by_task_id === task.id),
    )
  const processCount = runtimeWorkspace
    ? latestRuntimeBuild?.steps.length || 0
    : visibleTasks.length
  const assetCounts: Record<Exclude<AssetKind, 'all'>, number> = {
    image: uploadedImages.length + imageArtifacts.length,
    video: uploadedVideos.length + videoArtifacts.length + videoAnalysisArtifacts.length,
    audio: audioArtifacts.length + analysisArtifacts.length,
    text: textArtifacts.length + researchArtifacts.length,
    other: otherArtifacts.length,
  }
  const assetsCount = Object.values(assetCounts).reduce((total, count) => total + count, 0)
  const visibleAssetCount = assetKind === 'all' ? assetsCount : assetCounts[assetKind]
  const showImageAssets = assetKind === 'all' || assetKind === 'image'
  const showVideoAssets = assetKind === 'all' || assetKind === 'video'
  const showAudioAssets = assetKind === 'all' || assetKind === 'audio'
  const showTextAssets = assetKind === 'all' || assetKind === 'text'
  const showOtherAssets = assetKind === 'all' || assetKind === 'other'
  const scriptCount = storyArtifacts.length + textArtifacts.length
    + researchArtifacts.length + segmentScripts.length
  const handleSelectArtifact = async (artifact: DeepAgentArtifact) => {
    const runtimeArtifact = runtimeWorkspace?.artifacts.find(item => item.id === artifact.id)
    if (!runtimeArtifact || !runtimeWorkspace) {
      onSelectArtifact(artifact.id)
      return
    }
    if (runtimeArtifact.isSelected) return
    setSelectingArtifactId(artifact.id)
    try {
      await videoRuntimeClient.selectArtifact(
        projectId,
        runtimeArtifact.id,
        runtimeWorkspace.project.current_version_id,
      )
      setRuntimeWorkspace(await videoRuntimeClient.workspace(projectId))
      toast.success(t('da.workspace.artifactSwitched'))
    } catch (error) {
      toast.error(error instanceof Error ? runtimeMessage(error.message, t) : t('da.runtime.requestFailedGeneric'))
    } finally {
      setSelectingArtifactId(null)
    }
  }

  const refresh = async () => {
    setWorkspaceLoading(true)
    try {
      await onRefresh()
      if (projectId) {
        setRuntimeWorkspace(await videoRuntimeClient.workspace(projectId))
        setWorkspaceError(null)
      }
    } catch (error) {
      setWorkspaceError(error instanceof Error ? runtimeMessage(error.message, t) : t('da.runtime.requestFailedGeneric'))
    } finally {
      setWorkspaceLoading(false)
    }
  }

  useEffect(() => {
    if (activeTab !== 'final' || !finalVideoArtifact?.id) return
    latestResultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [activeTab, finalVideoArtifact?.id])

  return (
    <Tabs value={activeTab} onValueChange={value => setActiveTab(value as WorkspaceTab)} className="flex h-full min-h-0 flex-col bg-white dark:bg-black">
      <div className="flex items-center justify-between gap-3 border-b border-border/50 px-4 py-3">
        <TabsList className="h-10 min-w-0 justify-start gap-1 overflow-x-auto bg-transparent p-0">
          <TabsTrigger value="process" className="gap-2 rounded-lg px-3 data-[state=active]:bg-muted">
            <ListChecks className="h-4 w-4" />
            {t('da.workspace.tabProcess')}
            {processCount > 0 && <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">{processCount}</Badge>}
          </TabsTrigger>
          <TabsTrigger value="final" className="gap-2 rounded-lg px-3 data-[state=active]:bg-muted">
            <Film className="h-4 w-4" />
            {t('da.workspace.tabFinalVideo')}
            {finalVideoVersions.length > 0 && (
              <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                {finalVideoVersions.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="assets" className="gap-2 rounded-lg px-3 data-[state=active]:bg-muted">
            <Images className="h-4 w-4" />
            {t('da.workspace.tabAssets')}
            {assetsCount > 0 && <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">{assetsCount}</Badge>}
          </TabsTrigger>
          <TabsTrigger value="script" className="gap-2 rounded-lg px-3 data-[state=active]:bg-muted">
            <FileText className="h-4 w-4" />
            {t('da.workspace.tabScript')}
            {scriptCount > 0 && <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">{scriptCount}</Badge>}
          </TabsTrigger>
        </TabsList>
        <Button variant="ghost" size="sm" disabled={workspaceLoading} onClick={() => void refresh()}>
          <RefreshCw className={`h-4 w-4 ${workspaceLoading ? 'animate-spin' : ''}`} />
          <span className="sr-only">{t('da.workspace.refresh')}</span>
        </Button>
      </div>
      <ScrollArea
        className="min-h-0 min-w-0 flex-1"
        viewportClassName="overflow-x-hidden [&>div]:!block [&>div]:min-w-0 [&>div]:max-w-full"
      >
        <div className="w-full min-w-0 max-w-full space-y-5 overflow-x-hidden p-5">
          {activeTab === 'assets' && (
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t('da.workspace.assetFilters')}>
              {([
                ['all', t('da.workspace.assetAll'), assetsCount],
                ['image', t('da.workspace.assetImages'), assetCounts.image],
                ['video', t('da.workspace.assetVideos'), assetCounts.video],
                ['audio', t('da.workspace.assetAudio'), assetCounts.audio],
                ['text', t('da.workspace.assetText'), assetCounts.text],
                ['other', t('da.workspace.assetOther'), assetCounts.other],
              ] as const).map(([kind, label, count]) => (
                <Button
                  key={kind}
                  type="button"
                  size="sm"
                  variant={assetKind === kind ? 'secondary' : 'ghost'}
                  className="h-8 gap-1.5 rounded-full px-3 text-xs"
                  aria-pressed={assetKind === kind}
                  onClick={() => setAssetKind(kind)}
                >
                  {label}
                  <span className="text-[10px] text-muted-foreground">{count}</span>
                </Button>
              ))}
            </div>
          )}
          {workspaceError && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm text-amber-800 dark:text-amber-200">
              {interpolate(t('da.workspace.runtimeUnavailable'), {
                error: runtimeMessage(workspaceError, t),
              })}
            </div>
          )}

          {activeTab === 'process' && runtimeWorkspace && (
            <section className="space-y-4" data-testid="video-runtime-workspace">
              <Card className="border-accent-purple/30 bg-card/60">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between gap-3">
                    <CardTitle className="text-base">{runtimeWorkspace.project.title}</CardTitle>
                    <Badge variant="outline">
                      {interpolate(t('da.workspace.versionCount'), {
                        n: runtimeWorkspace.projectVersionCount
                          ?? runtimeWorkspace.projectVersions?.length
                          ?? 0,
                      })}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {runtimeWorkspace.builds.slice(0, 1).map(build => (
                    <div key={build.buildId} className="rounded-lg border border-border/60 p-3">
                      <div className="mb-2 flex items-center justify-between text-xs">
                        <span>{runtimeMessage(build.message || build.kind || '', t)}</span>
                        <Badge variant="secondary">{statusLabel(build.status, t)}</Badge>
                      </div>
                      <Progress value={(build.progress || 0) * 100} className="h-1.5" />
                      <div className="mt-3 grid gap-1 text-[11px] text-muted-foreground sm:grid-cols-2">
                        {build.steps.map(step => (
                          <span key={step.id}>{step.status === 'completed' ? '✓' : '○'} {planStepLabel(step.plan_step_id, t, stepEntityNames)}</span>
                        ))}
                      </div>
                      {build.error && (
                        <p className="mt-3 rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
                          {t('da.runtime.unknownFailure')}
                        </p>
                      )}
                    </div>
                  ))}

                </CardContent>
              </Card>
            </section>
          )}
          {activeTab === 'assets' && showImageAssets && uploadedImages.length > 0 && (
            <section className="space-y-3" data-testid="uploaded-image-references">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Image className="h-4 w-4" />
                {t('da.workspace.uploadedReferences')}
              </h3>
              <div className="grid min-w-0 max-w-full grid-cols-1 gap-3 sm:grid-cols-2">
                {uploadedImages.map((file, index) => (
                  <Card
                    key={`uploaded-image-${file.url}-${index}`}
                    className="min-w-0 max-w-full overflow-hidden border-border/60 bg-card/60"
                  >
                    <CardHeader className="pb-2">
                      <CardTitle className="flex min-w-0 items-center gap-2 text-sm">
                        <Image className="h-4 w-4 shrink-0" />
                        <span className="truncate">{file.filename || t('da.workspace.uploadedImage')}</span>
                        <Badge variant="outline">{t('da.workspace.uploadBadge')}</Badge>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="min-w-0 max-w-full space-y-3 overflow-hidden">
                      <img
                        src={file.url}
                        alt={file.filename || t('da.workspace.productReference')}
                        loading="lazy"
                        decoding="async"
                        className="mx-auto block h-auto max-h-[min(420px,calc(100dvh-14rem))] max-w-full rounded-lg object-contain"
                      />
                      <GenerationPrompt />
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          )}

          {activeTab === 'final' && finalVideoArtifact && finalVideoUri && (
            <section ref={latestResultRef} className="scroll-mt-4 space-y-3" data-testid="latest-media-result">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Film className="h-4 w-4" />
                {t('da.workspace.tabFinalVideo')}
              </h3>
              {finalVideoVersions.length > 1 && (
                <div className="flex flex-wrap gap-2" data-testid="final-video-versions">
                  {finalVideoVersions.map((artifact) => {
                    const active = artifact.id === finalVideoArtifact.id
                    const title = artifactTitle(artifact.title, artifact.type, t)
                    return (
                      <Button
                        key={artifact.id}
                        type="button"
                        size="sm"
                        variant={active ? 'secondary' : 'outline'}
                        className="h-auto min-w-0 gap-2 px-3 py-2"
                        aria-label={`${interpolate(t('da.workspace.versionCount'), { n: artifact.version })}: ${title}`}
                        aria-pressed={active}
                        disabled={active || selectingArtifactId === artifact.id}
                        onClick={() => void handleSelectArtifact(artifact)}
                      >
                        {selectingArtifactId === artifact.id && (
                          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
                        )}
                        <span className="font-medium">v{artifact.version}</span>
                        <span className="max-w-48 truncate text-xs text-muted-foreground">{title}</span>
                        {active && <Check className="h-3.5 w-3.5 shrink-0" />}
                      </Button>
                    )
                  })}
                </div>
              )}
              <Card className="min-w-0 max-w-full overflow-hidden border-accent-purple/40 bg-card/60">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between gap-3">
                    <CardTitle className="truncate text-base">
                      {artifactTitle(finalVideoArtifact.title, finalVideoArtifact.type, t)}
                    </CardTitle>
                    <div className="flex shrink-0 items-center gap-2">
                      <Badge variant="secondary">{t('da.workspace.ready')}</Badge>
                      {!selectedIds.has(finalVideoArtifact.id) && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={selectingArtifactId === finalVideoArtifact.id}
                          onClick={() => void handleSelectArtifact(finalVideoArtifact)}
                        >
                          {selectingArtifactId === finalVideoArtifact.id && (
                            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                          )}
                          {t('da.workspace.useVersion')}
                        </Button>
                      )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="min-w-0 max-w-full space-y-3 overflow-hidden">
                  <VideoFramePicker
                    mediaUri={finalVideoUri}
                    title={finalVideoArtifact.title || finalVideoArtifact.type}
                    eager
                    extracting={extractingKey === `latest-${finalVideoArtifact.id}`}
                    onExtract={timestamp => handleExtractFrame({
                      key: `latest-${finalVideoArtifact.id}`,
                      timestamp,
                      versionId: finalVideoArtifact.id,
                      videoUrl: finalVideoUri,
                    })}
                  />
                  {finalVideoArtifact.summary && (
                    <p className="text-xs text-muted-foreground">{finalVideoArtifact.summary}</p>
                  )}
                  <GenerationPrompt artifact={finalVideoArtifact} />
                </CardContent>
              </Card>
            </section>
          )}

          {activeTab === 'process' && visibleTasks.length > 0 && (
            <Card className="border-border/60 bg-card/60">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">{t('da.workspace.planProgress')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {visibleTasks.map((task) => {
                  const done = task.status === 'succeeded'
                  const active = task.status === 'running' || task.status === 'waiting_external'
                  const softFail = taskFailureIsSoft(task, snapshot)
                  const hardFail = task.status === 'failed' && !softFail
                  return (
                    <div
                      key={task.id}
                      className={
                        softFail
                          ? 'rounded-lg border border-amber-500/40 bg-amber-500/5 p-3'
                          : hardFail
                            ? 'rounded-lg border border-destructive/40 bg-destructive/5 p-3'
                            : 'rounded-lg border border-border/50 p-3'
                      }
                    >
                      <div className="flex items-start gap-3">
                        {done ? (
                          <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-500" />
                        ) : active ? (
                          <Loader2 className="mt-0.5 h-4 w-4 animate-spin text-accent-purple" />
                        ) : softFail ? (
                          <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-600" />
                        ) : hardFail ? (
                          <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
                        ) : (
                          <Circle className="mt-0.5 h-4 w-4 text-muted-foreground" />
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center justify-between gap-3">
                            <p className="truncate text-sm font-medium">{task.objective}</p>
                            <Badge
                              variant="outline"
                              className={
                                softFail
                                  ? 'shrink-0 border-amber-500/40 text-[10px] text-amber-700 dark:text-amber-300'
                                  : hardFail
                                    ? 'shrink-0 border-destructive/40 text-[10px] text-destructive'
                                    : 'shrink-0 text-[10px]'
                              }
                            >
                              {softFail ? t('da.workspace.retryable') : statusLabel(task.status, t)}
                            </Badge>
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">{capabilityLabel(task.capability_id, t)}</p>
                          {typeof task.progress === 'number' && (
                            <Progress value={task.progress} className="mt-2 h-1.5" />
                          )}
                          {task.progress_message && (
                            <p className="mt-1 text-xs text-muted-foreground">{runtimeMessage(task.progress_message, t)}</p>
                          )}
                          {task.error && softFail && (
                            <p className="mt-2 text-xs text-amber-800 dark:text-amber-200">
                              {interpolate(t('da.workspace.attemptFailed'), { error: t('da.runtime.unknownFailure') })}
                            </p>
                          )}
                          {task.error && hardFail && (
                            <p className="mt-2 text-xs text-destructive">{t('da.runtime.unknownFailure')}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </CardContent>
            </Card>
          )}

          {(activeTab === 'script' || (activeTab === 'assets' && showTextAssets)) && textArtifacts.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <FileText className="h-4 w-4" />
                  {activeTab === 'assets' ? t('da.workspace.assetText') : t('da.workspace.generatedDocuments')}
                </h3>
                <span className="text-xs text-muted-foreground">
                  {resultCountLabel(textArtifacts.length, t)}
                </span>
              </div>
              {textArtifacts.map((artifact) => {
                const selected = selectedIds.has(artifact.id)
                const body = storyBody(artifact)
                const title = readableTextTitle(artifact, body, t)
                return (
                  <Card key={artifact.id} className="overflow-hidden border-border/60 bg-card shadow-sm">
                    <CardHeader className="border-b border-border/50 bg-muted/20 px-5 py-4">
                      <div className="flex min-w-0 items-start justify-between gap-4">
                        <div className="min-w-0">
                          <CardTitle className="flex min-w-0 items-center gap-2 text-base leading-6">
                            <FileText className="h-4 w-4 shrink-0 text-primary" />
                            <span className="truncate">{title}</span>
                          </CardTitle>
                          <p className="mt-1 pl-6 text-xs text-muted-foreground">
                            {interpolate(t('da.workspace.textResultVersion'), { n: artifact.version })}
                          </p>
                        </div>
                        <Button
                          size="sm"
                          variant={selected ? 'secondary' : 'ghost'}
                          className="shrink-0"
                          disabled={selected || selectingArtifactId === artifact.id}
                          onClick={() => void handleSelectArtifact(artifact)}
                        >
                          {selectingArtifactId === artifact.id && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                          {selected && <Check className="mr-1 h-3.5 w-3.5" />}
                          {selected ? t('da.workspace.currentVersion') : t('da.workspace.useThisVersion')}
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4 px-5 py-5 sm:px-6">
                      {body ? (
                        <article className="prose prose-sm max-w-none break-words text-foreground prose-headings:scroll-mt-4 prose-headings:font-semibold prose-h1:text-xl prose-h2:mt-7 prose-h2:text-lg prose-h3:text-base prose-p:leading-7 prose-li:my-1 prose-li:leading-7 prose-table:block prose-table:max-w-full prose-table:overflow-x-auto dark:prose-invert">
                          <ArtifactDocument>{body}</ArtifactDocument>
                        </article>
                      ) : (
                        <p className="text-sm text-muted-foreground">
                          {t('da.workspace.documentPreparing')}
                        </p>
                      )}
                      <GenerationPrompt artifact={artifact} />
                    </CardContent>
                  </Card>
                )
              })}
            </section>
          )}

          {(activeTab === 'script' || (activeTab === 'assets' && showTextAssets)) && researchArtifacts.length > 0 && (
            <section className="space-y-3" data-testid="research-artifacts">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <BookOpen className="h-4 w-4" />
                {t('da.workspace.research')}
              </h3>
              {researchArtifacts.map((artifact) => {
                const selected = selectedIds.has(artifact.id)
                return (
                  <Card key={artifact.id} className="overflow-hidden border-border/60 bg-card/60">
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between gap-3">
                        <CardTitle className="flex min-w-0 items-center gap-2 text-base">
                          <BookOpen className="h-4 w-4" />
                          <span className="truncate">{artifact.title || t('da.workspace.researchTitle')}</span>
                          <Badge variant="outline">research</Badge>
                          <Badge variant="secondary">v{artifact.version}</Badge>
                        </CardTitle>
                        <Button
                          size="sm"
                          variant={selected ? 'secondary' : 'outline'}
                          disabled={selected || selectingArtifactId === artifact.id}
                          onClick={() => void handleSelectArtifact(artifact)}
                        >
                          {selectingArtifactId === artifact.id && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                          {selected && <Check className="mr-1 h-3.5 w-3.5" />}
                          {selected ? t('da.workspace.selected') : t('da.workspace.useVersion')}
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <ResearchDetails artifact={artifact} />
                      <GenerationPrompt artifact={artifact} />
                    </CardContent>
                  </Card>
                )
              })}
            </section>
          )}

          {activeTab === 'script' && (storyArtifacts.length > 0 || segmentScripts.length > 0) && (
            <section className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <FileText className="h-4 w-4" />
                {t('da.workspace.storyScripts')}
              </h3>
              {storyArtifacts.map((artifact) => {
                const selected = selectedIds.has(artifact.id)
                const body = storyBody(artifact)
                return (
                  <Card key={artifact.id} className="overflow-hidden border-border/60 bg-card/60">
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between gap-3">
                        <CardTitle className="flex min-w-0 items-center gap-2 text-base">
                          <FileText className="h-4 w-4" />
                          <span className="truncate">{artifactTitle(artifact.title, artifact.type, t) || t('da.workspace.storyScript')}</span>
                          <Badge variant="secondary">v{artifact.version}</Badge>
                        </CardTitle>
                        <Button
                          size="sm"
                          variant={selected ? 'secondary' : 'outline'}
                          disabled={selected || selectingArtifactId === artifact.id}
                          onClick={() => void handleSelectArtifact(artifact)}
                        >
                          {selectingArtifactId === artifact.id && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                          {selected && <Check className="mr-1 h-3.5 w-3.5" />}
                          {selected ? t('da.workspace.selected') : t('da.workspace.useVersion')}
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      {body ? (
                        <div className="prose prose-sm max-w-none whitespace-pre-wrap text-foreground dark:prose-invert">
                          <ArtifactDocument>{body}</ArtifactDocument>
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground">{t('da.workspace.scriptUnavailable')}</p>
                      )}
                      <GenerationPrompt artifact={artifact} />
                    </CardContent>
                  </Card>
                )
              })}
              {segmentScripts.map((task) => {
                const softFail = taskFailureIsSoft(task, snapshot)
                const hardFail = task.status === 'failed' && !softFail
                return (
                  <Card
                    key={`script-${task.id}`}
                    className={
                      softFail
                        ? 'overflow-hidden border-amber-500/30 bg-amber-500/5'
                        : hardFail
                          ? 'overflow-hidden border-destructive/30 bg-destructive/5'
                          : 'overflow-hidden border-border/60 bg-card/60'
                    }
                  >
                    <CardHeader className="pb-2">
                      <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
                        <FileText className="h-4 w-4" />
                        <span className="truncate">{capabilityLabel(task.capability_id, t)}</span>
                        <Badge
                          variant="outline"
                          className={
                            softFail
                              ? 'text-[10px] text-amber-700 dark:text-amber-300'
                              : hardFail
                                ? 'text-[10px] text-destructive'
                                : 'text-[10px]'
                          }
                        >
                          {softFail ? t('da.workspace.retryable') : statusLabel(task.status, t)}
                        </Badge>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="prose prose-sm max-w-none whitespace-pre-wrap text-foreground dark:prose-invert">
                        <ArtifactDocument>{task.objective}</ArtifactDocument>
                      </div>
                      <GenerationPrompt prompt={task.objective} />
                    </CardContent>
                  </Card>
                )
              })}
            </section>
          )}

          {activeTab === 'assets' && showImageAssets && imageArtifacts.length > 0 && (
            <section className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Image className="h-4 w-4" />
                {t('da.workspace.images')}
              </h3>
              <div className="grid min-w-0 max-w-full grid-cols-1 gap-3 sm:grid-cols-2">
                {imageArtifacts.map((artifact) => {
                  const selected = selectedIds.has(artifact.id)
                  const mediaUri = artifactMediaUri(artifact)
                  const title = artifactTitle(artifact.title, artifact.type, t)
                  return (
                    <Card key={artifact.id} className="min-w-0 max-w-full overflow-hidden border-border/60 bg-card/60">
                      <CardHeader className="pb-2">
                        <div className="flex items-center justify-between gap-2">
                          <CardTitle className="truncate text-sm">{title}</CardTitle>
                          <Button
                            size="sm"
                            variant={selected ? 'secondary' : 'outline'}
                            disabled={selected || selectingArtifactId === artifact.id}
                            onClick={() => void handleSelectArtifact(artifact)}
                          >
                            {selectingArtifactId === artifact.id && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                            {selected ? t('da.workspace.selected') : t('da.workspace.use')}
                          </Button>
                        </div>
                      </CardHeader>
                      <CardContent className="min-w-0 max-w-full space-y-2 overflow-hidden">
                        {mediaUri ? (
                          <img
                            src={mediaUri}
                            alt={title || t('da.workspace.generatedImage')}
                            loading="lazy"
                            decoding="async"
                            className="mx-auto block h-auto max-h-[min(360px,calc(100dvh-14rem))] max-w-full rounded-lg object-contain"
                          />
                        ) : (
                          <p className="text-xs text-muted-foreground">{t('da.workspace.imageMissing')}</p>
                        )}
                        {artifact.summary && (
                          <div className="prose prose-sm max-w-none text-foreground dark:prose-invert">
                            <ArtifactDocument>
                              {artifact.summary.replace(/!\[[^\]]*\]\([^)]+\)/g, '').trim()}
                            </ArtifactDocument>
                          </div>
                        )}
                        <GenerationPrompt artifact={artifact} />
                      </CardContent>
                    </Card>
                  )
                })}
              </div>
            </section>
          )}

          {activeTab === 'assets' && showVideoAssets && uploadedVideos.length > 0 && (
            <section className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Film className="h-4 w-4" />
                {t('da.workspace.uploadedVideos')}
              </h3>
              {uploadedVideos.map((file, index) => {
                const key = `upload-${file.url}-${index}`
                return (
                  <Card key={key} className="overflow-hidden border-border/60 bg-card/60">
                    <CardHeader className="pb-3">
                      <CardTitle className="flex min-w-0 items-center gap-2 text-base">
                        <Film className="h-4 w-4" />
                        <span className="truncate">{file.filename || t('da.workspace.uploadedVideo')}</span>
                        <Badge variant="outline">{t('da.workspace.uploadBadge')}</Badge>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <VideoFramePicker
                        mediaUri={file.url}
                        title={file.filename || t('da.workspace.uploadedVideo')}
                        extracting={extractingKey === key}
                        onExtract={timestamp => handleExtractFrame({
                          key,
                          timestamp,
                          videoUrl: file.url,
                        })}
                      />
                      <GenerationPrompt />
                    </CardContent>
                  </Card>
                )
              })}
            </section>
          )}

          {activeTab === 'assets' && showVideoAssets && videoArtifacts.length > 0 && (
            <section className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Film className="h-4 w-4" />
                {t('da.workspace.videos')}
              </h3>
              {videoArtifacts.map((artifact) => {
                const selected = selectedIds.has(artifact.id)
                const mediaUri = artifactMediaUri(artifact)
                const extractKey = `artifact-${artifact.id}`
                const title = artifactTitle(artifact.title, artifact.type, t)
                return (
                  <Card key={artifact.id} className="overflow-hidden border-border/60 bg-card/60">
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between gap-3">
                        <CardTitle className="flex min-w-0 items-center gap-2 text-base">
                          <Film className="h-4 w-4" />
                          <span className="truncate">{title}</span>
                          <Badge variant="secondary">v{artifact.version}</Badge>
                        </CardTitle>
                        <Button
                          size="sm"
                          variant={selected ? 'secondary' : 'outline'}
                          disabled={selected || selectingArtifactId === artifact.id}
                          onClick={() => void handleSelectArtifact(artifact)}
                        >
                          {selectingArtifactId === artifact.id && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                          {selected && <Check className="mr-1 h-3.5 w-3.5" />}
                          {selected ? t('da.workspace.selected') : t('da.workspace.useVersion')}
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {mediaUri ? (
                        <VideoFramePicker
                          mediaUri={mediaUri}
                          title={title}
                          extracting={extractingKey === extractKey}
                          onExtract={timestamp => handleExtractFrame({
                            key: extractKey,
                            timestamp,
                            versionId: artifact.id,
                            videoUrl: mediaUri,
                          })}
                        />
                      ) : (
                        <p className="text-xs text-muted-foreground">{t('da.workspace.videoMissing')}</p>
                      )}
                      {artifact.summary && (
                        <div className="prose prose-sm max-w-none text-foreground dark:prose-invert">
                          <ArtifactDocument>{artifact.summary}</ArtifactDocument>
                        </div>
                      )}
                      <GenerationPrompt artifact={artifact} />
                    </CardContent>
                  </Card>
                )
              })}
            </section>
          )}

          {activeTab === 'assets' && showVideoAssets && videoAnalysisArtifacts.length > 0 && (
            <section className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Scissors className="h-4 w-4" />
                {t('da.workspace.videoAnalysis')}
              </h3>
              {videoAnalysisArtifacts.map((artifact) => {
                const selected = selectedIds.has(artifact.id)
                const title = artifactTitle(artifact.title, artifact.type, t)
                return (
                  <Card key={artifact.id} className="overflow-hidden border-border/60 bg-card/60">
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between gap-3">
                        <CardTitle className="flex min-w-0 items-center gap-2 text-base">
                          <Scissors className="h-4 w-4" />
                          <span className="truncate">{title}</span>
                          <Badge variant="secondary">v{artifact.version}</Badge>
                        </CardTitle>
                        <Button
                          size="sm"
                          variant={selected ? 'secondary' : 'outline'}
                          disabled={selected || selectingArtifactId === artifact.id}
                          onClick={() => void handleSelectArtifact(artifact)}
                        >
                          {selectingArtifactId === artifact.id && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                          {selected && <Check className="mr-1 h-3.5 w-3.5" />}
                          {selected ? t('da.workspace.selected') : t('da.workspace.useVersion')}
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <VideoAnalysisDetails artifact={artifact} />
                    </CardContent>
                  </Card>
                )
              })}
            </section>
          )}

          {activeTab === 'assets' && showAudioAssets && audioArtifacts.length > 0 && (
            <section className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Music className="h-4 w-4" />
                {t('da.workspace.audio')}
              </h3>
              {audioArtifacts.map((artifact) => {
                const selected = selectedIds.has(artifact.id)
                const mediaUri = artifactMediaUri(artifact)
                const title = artifactTitle(artifact.title, artifact.type, t)
                return (
                  <Card key={artifact.id} className="overflow-hidden border-border/60 bg-card/60">
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between gap-3">
                        <CardTitle className="flex min-w-0 items-center gap-2 text-base">
                          <Music className="h-4 w-4" />
                          <span className="truncate">{title}</span>
                          <Badge variant="secondary">v{artifact.version}</Badge>
                        </CardTitle>
                        <Button
                          size="sm"
                          variant={selected ? 'secondary' : 'outline'}
                          disabled={selected || selectingArtifactId === artifact.id}
                          onClick={() => void handleSelectArtifact(artifact)}
                        >
                          {selectingArtifactId === artifact.id && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                          {selected && <Check className="mr-1 h-3.5 w-3.5" />}
                          {selected ? t('da.workspace.selected') : t('da.workspace.useVersion')}
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {mediaUri ? (
                        <audio src={mediaUri} controls preload="none" className="w-full" />
                      ) : (
                        <p className="text-xs text-muted-foreground">{t('da.workspace.audioMissing')}</p>
                      )}
                      <MusicArtifactDetails artifact={artifact} />
                      <GenerationPrompt artifact={artifact} />
                    </CardContent>
                  </Card>
                )
              })}
            </section>
          )}

          {activeTab === 'assets' && showAudioAssets && analysisArtifacts.length > 0 && (
            <section className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Scissors className="h-4 w-4" />
                {t('da.workspace.audioAnalysis')}
              </h3>
              {analysisArtifacts.map((artifact) => {
                const selected = selectedIds.has(artifact.id)
                const mediaUri = artifactMediaUri(artifact)
                const title = artifactTitle(artifact.title, artifact.type, t)
                return (
                  <Card key={artifact.id} className="overflow-hidden border-border/60 bg-card/60">
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between gap-3">
                        <CardTitle className="flex min-w-0 items-center gap-2 text-base">
                          <Scissors className="h-4 w-4" />
                          <span className="truncate">{title}</span>
                          <Badge variant="secondary">v{artifact.version}</Badge>
                        </CardTitle>
                        <Button
                          size="sm"
                          variant={selected ? 'secondary' : 'outline'}
                          disabled={selected || selectingArtifactId === artifact.id}
                          onClick={() => void handleSelectArtifact(artifact)}
                        >
                          {selectingArtifactId === artifact.id && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                          {selected && <Check className="mr-1 h-3.5 w-3.5" />}
                          {selected ? t('da.workspace.selected') : t('da.workspace.useVersion')}
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {mediaUri ? (
                        <audio src={mediaUri} controls preload="none" className="w-full" />
                      ) : null}
                      <AudioAnalysisDetails artifact={artifact} />
                      <GenerationPrompt artifact={artifact} />
                    </CardContent>
                  </Card>
                )
              })}
            </section>
          )}

          {activeTab === 'assets' && showOtherAssets && otherArtifacts.map((artifact) => {
            const selected = selectedIds.has(artifact.id)
            const mediaUri = artifactMediaUri(artifact)
            const body = storyBody(artifact)
            const title = artifactTitle(artifact.title, artifact.type, t)
            return (
              <Card key={artifact.id} className="overflow-hidden border-border/60 bg-card/60">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between gap-3">
                    <CardTitle className="flex min-w-0 items-center gap-2 text-base">
                      <FileText className="h-4 w-4" />
                      <span className="truncate">{title}</span>
                      <Badge variant="secondary">v{artifact.version}</Badge>
                    </CardTitle>
                    <Button
                      size="sm"
                      variant={selected ? 'secondary' : 'outline'}
                      disabled={selected || selectingArtifactId === artifact.id}
                      onClick={() => void handleSelectArtifact(artifact)}
                    >
                      {selectingArtifactId === artifact.id && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                      {selected && <Check className="mr-1 h-3.5 w-3.5" />}
                      {selected ? t('da.workspace.selected') : t('da.workspace.useVersion')}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {body && (
                    <div className="prose prose-sm max-w-none text-foreground dark:prose-invert">
                      <ArtifactDocument>{body}</ArtifactDocument>
                    </div>
                  )}
                  {mediaUri && (
                    <a href={mediaUri} target="_blank" rel="noreferrer" className="text-sm text-primary underline-offset-4 hover:underline">
                      {t('da.workspace.openArtifact')}
                    </a>
                  )}
                </CardContent>
              </Card>
            )
          })}

          {activeTab === 'process' && !runtimeWorkspace && visibleTasks.length === 0 && (
            <div className="flex min-h-[360px] flex-col items-center justify-center text-center text-muted-foreground">
              <ListChecks className="mb-4 h-12 w-12 opacity-30" />
              <p className="text-sm">{t('da.workspace.emptyProcess')}</p>
            </div>
          )}
          {activeTab === 'final' && !finalVideoArtifact && (
            <div className="flex min-h-[360px] flex-col items-center justify-center text-center text-muted-foreground">
              <Film className="mb-4 h-12 w-12 opacity-30" />
              <p className="text-sm">{t('da.workspace.emptyFinalVideo')}</p>
            </div>
          )}
          {activeTab === 'assets' && visibleAssetCount === 0 && (
            <div className="flex min-h-[360px] flex-col items-center justify-center text-center text-muted-foreground">
              <Images className="mb-4 h-12 w-12 opacity-30" />
              <p className="text-sm">{assetKind === 'all' ? t('da.workspace.emptyAssets') : t('da.workspace.emptyAssetCategory')}</p>
            </div>
          )}
          {activeTab === 'script' && scriptCount === 0 && (
            <div className="flex min-h-[360px] flex-col items-center justify-center text-center text-muted-foreground">
              <FileText className="mb-4 h-12 w-12 opacity-30" />
              <p className="text-sm">{t('da.workspace.emptyScript')}</p>
            </div>
          )}
        </div>
      </ScrollArea>
    </Tabs>
  )
}
