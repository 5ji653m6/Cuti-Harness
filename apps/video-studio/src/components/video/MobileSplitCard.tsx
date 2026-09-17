import { asyncEvent } from '../../utils/asyncEvent'
import { Button } from '@/components/ui/button'
import { Loader2, Scissors, Download, Minus, Plus, ArrowLeft } from 'lucide-react'
import { type TileInfo } from '@/utils/collageSplitter'
import { downloadAllTiles } from '@/utils/collageSplitter'
import { useLanguage } from '@/i18n/LanguageContext'

interface GridPreset {
  label: string
  rows: number
  cols: number
}

interface MobileSplitCardProps {
  gridPresets: GridPreset[]
  splitRows: number
  splitCols: number
  onRowsChange: (rows: number) => void
  onColsChange: (cols: number) => void
  onPresetSelect: (rows: number, cols: number) => void
  onSplit: () => void
  isSplitting: boolean
  splitError?: string | null
  splitTiles: TileInfo[] | null
  onTileClick: (tile: TileInfo) => void
  imageTitle: string
  onBack: () => void
  /** 为 true 时不渲染卡片内的返回按钮（由父组件在顶部统一展示） */
  hideBackButton?: boolean
}

export const MobileSplitCard = ({
  gridPresets,
  splitRows,
  splitCols,
  onRowsChange,
  onColsChange,
  onPresetSelect,
  onSplit,
  isSplitting,
  splitError,
  splitTiles,
  onTileClick,
  imageTitle,
  onBack,
  hideBackButton = false,
}: MobileSplitCardProps) => {
  const { t } = useLanguage()

  if (splitTiles) {
    // 结果卡片
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {!hideBackButton && (
              <Button variant="ghost" size="icon" className="w-8 h-8 text-white hover:bg-white/10" onClick={onBack} aria-label={t('back') || 'Back'}>
                <ArrowLeft className="w-4 h-4" />
              </Button>
            )}
            <span className="text-sm text-white/70">{splitTiles.length} {t('imagesSplit')}</span>
          </div>
          <Button size="sm" className="bg-white/20 text-white border-white/30 hover:bg-white/30" onClick={asyncEvent(async () => { const base = imageTitle.replace(/\s+/g, '_'); await downloadAllTiles(splitTiles, base) })}>
            <Download className="w-4 h-4 mr-2" />{t('downloadAll')}
          </Button>
        </div>
        <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${splitCols}, 1fr)` }}>
          {splitTiles.map(tile => (
            <div key={tile.index} className="relative rounded-lg overflow-hidden border border-white/20 cursor-pointer hover:ring-2 hover:ring-white/50" onClick={() =>{  onTileClick(tile) }}>
              <img src={tile.dataUrl} alt={`${tile.index + 1}`} className="w-full h-auto object-contain" />
              <span className="absolute top-1 left-1 bg-black/60 text-white text-[10px] font-bold rounded-full w-5 h-5 flex items-center justify-center">{tile.index + 1}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // 裁切卡片
  return (
    <>
      <div className="space-y-4 p-4 rounded-lg border border-white/20 bg-white/5">
        <div className="flex items-center gap-2 mb-2">
          {!hideBackButton && (
            <Button variant="ghost" size="icon" className="w-8 h-8 text-white hover:bg-white/10 shrink-0" onClick={onBack} aria-label={t('back') || 'Back'}>
              <ArrowLeft className="w-4 h-4" />
            </Button>
          )}
          <label className="text-sm font-medium text-white">{t('gridPresets')}</label>
        </div>
        <div className="flex flex-wrap gap-2">
          {gridPresets.map(p => (
            <Button key={p.label} variant={splitRows === p.rows && splitCols === p.cols ? 'default' : 'outline'} size="sm" onClick={() =>{  onPresetSelect(p.rows, p.cols) }} className={splitRows === p.rows && splitCols === p.cols ? 'bg-white text-black hover:bg-white/90' : 'bg-white/90 dark:bg-gray-800/90 border-white/30 dark:border-gray-600 text-gray-900 dark:text-gray-100 hover:bg-white dark:hover:bg-gray-700'}>
              {p.label}
            </Button>
          ))}
        </div>
        <div className="flex gap-4 items-center flex-wrap">
          <span className="text-sm text-white/70">{t('rows')}</span>
          <Button variant="outline" size="icon" className="w-8 h-8 bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700" onClick={() =>{  onRowsChange(Math.max(1, splitRows - 1)) }} disabled={splitRows <= 1}><Minus className="w-3 h-3 text-gray-900 dark:text-gray-100" /></Button>
          <span className="w-6 text-center text-sm text-gray-900 dark:text-gray-100 bg-white dark:bg-gray-800 px-2 py-1 rounded">{splitRows}</span>
          <Button variant="outline" size="icon" className="w-8 h-8 bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700" onClick={() =>{  onRowsChange(Math.min(10, splitRows + 1)) }} disabled={splitRows >= 10}><Plus className="w-3 h-3 text-gray-900 dark:text-gray-100" /></Button>
          <span className="text-sm text-white/70 ml-2">{t('cols')}</span>
          <Button variant="outline" size="icon" className="w-8 h-8 bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700" onClick={() =>{  onColsChange(Math.max(1, splitCols - 1)) }} disabled={splitCols <= 1}><Minus className="w-3 h-3 text-gray-900 dark:text-gray-100" /></Button>
          <span className="w-6 text-center text-sm text-gray-900 dark:text-gray-100 bg-white dark:bg-gray-800 px-2 py-1 rounded">{splitCols}</span>
          <Button variant="outline" size="icon" className="w-8 h-8 bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700" onClick={() =>{  onColsChange(Math.min(10, splitCols + 1)) }} disabled={splitCols >= 10}><Plus className="w-3 h-3 text-gray-900 dark:text-gray-100" /></Button>
        </div>
        <Button className="w-full bg-white text-black hover:bg-white/90" onClick={onSplit} disabled={isSplitting}>
          {isSplitting ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />{t('splitting')}</> : <><Scissors className="w-4 h-4 mr-2" />{t('splitNow')}</>}
        </Button>
      </div>
      {splitError && <div className="text-sm text-red-400 bg-red-500/10 rounded-lg p-3">{splitError}</div>}
    </>
  )
}
