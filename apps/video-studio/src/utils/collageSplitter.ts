import { arrayItem } from './arrayItem'
/**
 * 组图裁切工具
 * 使用 HTML5 Canvas API 将一张组图（collage）裁切为多张独立图片
 */

export interface WatermarkOptions {
  /** 水印图片 URL（放在 public 目录下，如 /watermark.png） */
  url: string
  /** 水印相对于裁切图短边的缩放比例，默认 0.25（即短边的 25%，符合常见推荐） */
  scale?: number
  /** 距右下角的边距（像素），默认 10 */
  margin?: number
  /** 水印透明度 0~1，默认 0.8 */
  opacity?: number
}

export interface SplitOptions {
  rows: number
  cols: number
  padding?: number
  /**
   * 自定义网格：行分割线位置 0~1，长度 rows-1。不传则用均匀网格+offset。
   */
  rowDividers?: number[]
  /**
   * 自定义网格：列分割线位置 0~1，长度 cols-1。不传则用均匀网格+offset。
   */
  colDividers?: number[]
  /**
   * 1×1 时可选：裁切区域 0~1（left, top, right, bottom）。不传则整图。
   */
  cropRect?: { left: number; top: number; right: number; bottom: number }
  /** 水印配置，不传则不添加水印 */
  watermark?: WatermarkOptions
}

export interface TileInfo {
  index: number
  row: number
  col: number
  blob: Blob
  dataUrl: string
}

/**
 * 加载远程图片到 HTMLImageElement（需要 CORS 支持）
 */
function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () =>{  resolve(img) }
    img.onerror = () =>{
      reject(new Error('Failed to load image. The image may not support cross-origin access.')) }
    img.src = url
  })
}

function canvasContext(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas 2D rendering is unavailable')
  return context
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new Error('Failed to encode canvas as PNG'))
    }, 'image/png')
  })
}

/**
 * 在 Canvas 右下角绘制水印图片
 */
function drawWatermark(
  ctx: CanvasRenderingContext2D,
  watermarkImg: HTMLImageElement,
  canvasW: number,
  canvasH: number,
  options: WatermarkOptions,
) {
  const { scale = 0.25, margin = 10, opacity = 0.8 } = options

  // 以短边为基准计算水印尺寸
  const shortSide = Math.min(canvasW, canvasH)
  const wmTargetW = shortSide * scale
  const wmAspect = watermarkImg.width / watermarkImg.height
  const wmW = wmTargetW
  const wmH = wmTargetW / wmAspect

  // 右下角定位
  const wmX = canvasW - wmW - margin
  const wmY = canvasH - wmH - margin

  ctx.save()
  ctx.globalAlpha = opacity
  // 添加阴影效果，让 logo 在浅色/深色背景上都清晰可辨
  ctx.shadowColor = 'rgba(0, 0, 0, 0.5)'
  ctx.shadowBlur = 8
  ctx.shadowOffsetX = 2
  ctx.shadowOffsetY = 2
  ctx.drawImage(watermarkImg, wmX, wmY, wmW, wmH)
  ctx.restore()
}

/**
 * 将一张组图裁切为 rows × cols 张独立图片
 *
 * @param imageUrl  组图的 URL（需支持 CORS）
 * @param options   裁切参数：rows, cols, padding, watermark
 * @returns         每张小图的 TileInfo 数组（包含 blob 和 dataUrl）
 */
export async function splitCollage(
  imageUrl: string,
  options: SplitOptions,
): Promise<TileInfo[]> {
  const { rows, cols, padding = 0, rowDividers, colDividers, cropRect, watermark } = options

  const img = await loadImage(imageUrl)
  const imgW = img.width
  const imgH = img.height

  // 预加载水印图片（如果配置了水印）
  let watermarkImg: HTMLImageElement | null = null
  if (watermark?.url) {
    watermarkImg = await loadImage(watermark.url)
  }

  const tiles: TileInfo[] = []

  // 1×1 且指定 cropRect：只输出一块
  if (rows === 1 && cols === 1 && cropRect) {
    const left = Math.max(0, Math.min(1, cropRect.left))
    const top = Math.max(0, Math.min(1, cropRect.top))
    const right = Math.max(left, Math.min(1, cropRect.right))
    const bottom = Math.max(top, Math.min(1, cropRect.bottom))
    const sx = Math.round(left * imgW)
    const sy = Math.round(top * imgH)
    const w = Math.max(1, Math.round((right - left) * imgW))
    const h = Math.max(1, Math.round((bottom - top) * imgH))
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvasContext(canvas)
    ctx.drawImage(img, sx, sy, w, h, 0, 0, w, h)
    if (watermarkImg && watermark) {
      drawWatermark(ctx, watermarkImg, w, h, watermark)
    }
    const blob = await canvasBlob(canvas)
    tiles.push({
      index: 0,
      row: 0,
      col: 0,
      blob,
      dataUrl: canvas.toDataURL('image/png'),
    })
    return tiles
  }

  // 自定义分割线
  if (rowDividers && colDividers && rowDividers.length === rows - 1 && colDividers.length === cols - 1) {
    const rowBounds = [0, ...rowDividers.sort((a, b) => a - b), 1]
    const colBounds = [0, ...colDividers.sort((a, b) => a - b), 1]
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x0 = arrayItem(colBounds, c)
        const x1 = arrayItem(colBounds, c + 1)
        const y0 = arrayItem(rowBounds, r)
        const y1 = arrayItem(rowBounds, r + 1)
        const sx = Math.round(x0 * imgW)
        const sy = Math.round(y0 * imgH)
        const w = Math.max(1, Math.round((x1 - x0) * imgW))
        const h = Math.max(1, Math.round((y1 - y0) * imgH))
        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        const ctx = canvasContext(canvas)
        ctx.drawImage(img, sx, sy, w, h, 0, 0, w, h)
        if (watermarkImg && watermark) {
          drawWatermark(ctx, watermarkImg, w, h, watermark)
        }
        const blob = await canvasBlob(canvas)
        tiles.push({
          index: r * cols + c,
          row: r,
          col: c,
          blob,
          dataUrl: canvas.toDataURL('image/png'),
        })
      }
    }
    return tiles
  }

  // 默认：均匀网格 + offset
  const tileW = Math.floor((imgW - padding * (cols - 1)) / cols)
  const tileH = Math.floor((imgH - padding * (rows - 1)) / rows)
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const sx = Math.round(c * (tileW + padding))
      const sy = Math.round(r * (tileH + padding))

      const canvas = document.createElement('canvas')
      canvas.width = tileW
      canvas.height = tileH
      const ctx = canvasContext(canvas)

      ctx.drawImage(img, sx, sy, tileW, tileH, 0, 0, tileW, tileH)
      if (watermarkImg && watermark) {
        drawWatermark(ctx, watermarkImg, tileW, tileH, watermark)
      }
      const blob = await canvasBlob(canvas)

      const dataUrl = canvas.toDataURL('image/png')

      tiles.push({
        index: r * cols + c,
        row: r,
        col: c,
        blob,
        dataUrl,
      })
    }
  }

  return tiles
}

/**
 * 给图片添加右下角 logo 水印，返回带水印的 blob 和 dataUrl
 *
 * @param imageUrl      原图 URL（需支持 CORS）
 * @param watermarkOpts 水印参数，不传则使用默认值（watermark.png, scale 0.2, margin 10, opacity 0.8）
 */
export async function addLogoToImage(
  imageUrl: string,
  watermarkOpts?: Partial<WatermarkOptions>,
): Promise<{ blob: Blob; dataUrl: string }> {
  const defaults: WatermarkOptions = {
    url: 'watermark.png',
    scale: 0.25,
    margin: 10,
    opacity: 0.8,
  }
  const opts: WatermarkOptions = { ...defaults, ...watermarkOpts }

  const img = await loadImage(imageUrl)
  const watermarkImg = await loadImage(opts.url)

  const canvas = document.createElement('canvas')
  canvas.width = img.width
  canvas.height = img.height
  const ctx = canvasContext(canvas)
  ctx.drawImage(img, 0, 0)
  drawWatermark(ctx, watermarkImg, img.width, img.height, opts)

  const blob = await canvasBlob(canvas)
  return { blob, dataUrl: canvas.toDataURL('image/png') }
}

/**
 * 给 Blob/dataUrl 图片添加右下角 logo 水印（适用于已经裁剪过的 tile blob）
 */
export async function addLogoToBlob(
  dataUrl: string,
  watermarkOpts?: Partial<WatermarkOptions>,
): Promise<{ blob: Blob; dataUrl: string }> {
  return addLogoToImage(dataUrl, watermarkOpts)
}

/**
 * 下载单个 Blob 文件
 */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  URL.revokeObjectURL(url)
  document.body.removeChild(a)
}

/**
 * 批量下载所有裁切小图
 */
export async function downloadAllTiles(tiles: TileInfo[], baseFilename: string) {
  for (const tile of tiles) {
    downloadBlob(tile.blob, `${baseFilename}_${tile.index + 1}.png`)
    // 每次下载间隔 300ms，防止浏览器拦截连续下载
    await new Promise(resolve => setTimeout(resolve, 300))
  }
}
