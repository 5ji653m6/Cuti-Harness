import { arrayItem } from './arrayItem'
import { DEFAULT_VIDEO_OPTIONS } from '@/constants/defaults'
import { isAudioFile } from '@/utils/fileUploadUtils'

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

const encodeWavFromAudioBuffer = (buffer: AudioBuffer): Blob => {
  const numberOfChannels = buffer.numberOfChannels
  const sampleRate = buffer.sampleRate
  const bitsPerSample = 16
  const bytesPerSample = bitsPerSample / 8
  const dataLength = buffer.length * numberOfChannels * bytesPerSample
  const output = new ArrayBuffer(44 + dataLength)
  const view = new DataView(output)

  let offset = 0
  const writeString = (text: string) => {
    for (let i = 0; i < text.length; i++) {
      view.setUint8(offset++, text.charCodeAt(i))
    }
  }

  writeString('RIFF')
  view.setUint32(offset, 36 + dataLength, true)
  offset += 4
  writeString('WAVE')
  writeString('fmt ')
  view.setUint32(offset, 16, true)
  offset += 4
  view.setUint16(offset, 1, true)
  offset += 2
  view.setUint16(offset, numberOfChannels, true)
  offset += 2
  view.setUint32(offset, sampleRate, true)
  offset += 4
  view.setUint32(offset, sampleRate * numberOfChannels * bytesPerSample, true)
  offset += 4
  view.setUint16(offset, numberOfChannels * bytesPerSample, true)
  offset += 2
  view.setUint16(offset, bitsPerSample, true)
  offset += 2
  writeString('data')
  view.setUint32(offset, dataLength, true)
  offset += 4

  const channels: Float32Array[] = []
  for (let channel = 0; channel < numberOfChannels; channel++) {
    channels.push(buffer.getChannelData(channel))
  }

  for (let i = 0; i < buffer.length; i++) {
    for (let channel = 0; channel < numberOfChannels; channel++) {
      const sample = clamp(arrayItem(arrayItem(channels, channel), i), -1, 1)
      const intSample = sample < 0 ? sample * 0x8000 : sample * 0x7fff
      view.setInt16(offset, intSample, true)
      offset += 2
    }
  }

  return new Blob([output], { type: 'audio/wav' })
}

export const decodeAudioFile = async (file: File): Promise<AudioBuffer> => {
  const arrayBuffer = await file.arrayBuffer()
  const audioContext = new AudioContext()
  try {
    const decoded = await audioContext.decodeAudioData(arrayBuffer.slice(0))
    return decoded
  } finally {
    await audioContext.close()
  }
}

export const createWaveformPeaks = (audioBuffer: AudioBuffer, bins = 180): number[] => {
  const channelData = audioBuffer.getChannelData(0)
  const blockSize = Math.max(1, Math.floor(channelData.length / bins))
  const peaks: number[] = []

  for (let i = 0; i < bins; i++) {
    const start = i * blockSize
    const end = Math.min(channelData.length, start + blockSize)
    let peak = 0
    for (let j = start; j < end; j++) {
      const value = Math.abs(arrayItem(channelData, j))
      if (value > peak) peak = value
    }
    peaks.push(peak)
  }

  const maxPeak = Math.max(...peaks, 0.001)
  return peaks.map(value => value / maxPeak)
}

export const cropAudioFile = async (
  file: File,
  startSec: number,
  endSec: number,
): Promise<File> => {
  const sourceBuffer = await decodeAudioFile(file)
  const start = clamp(startSec, 0, sourceBuffer.duration)
  const end = clamp(endSec, start + 0.05, sourceBuffer.duration)
  const sampleRate = sourceBuffer.sampleRate
  const startSample = Math.floor(start * sampleRate)
  const endSample = Math.floor(end * sampleRate)
  const frameCount = Math.max(1, endSample - startSample)

  const targetContext = new OfflineAudioContext(
    sourceBuffer.numberOfChannels,
    frameCount,
    sampleRate,
  )
  const targetBuffer = targetContext.createBuffer(
    sourceBuffer.numberOfChannels,
    frameCount,
    sampleRate,
  )

  for (let channel = 0; channel < sourceBuffer.numberOfChannels; channel++) {
    const from = sourceBuffer.getChannelData(channel).subarray(startSample, endSample)
    targetBuffer.copyToChannel(from, channel, 0)
  }

  const wavBlob = encodeWavFromAudioBuffer(targetBuffer)
  const dot = file.name.lastIndexOf('.')
  const baseName = dot > 0 ? file.name.slice(0, dot) : file.name
  const safeStart = start.toFixed(2).replace('.', '_')
  const safeEnd = end.toFixed(2).replace('.', '_')
  const nextName = `${baseName}_crop_${safeStart}-${safeEnd}.wav`

  return new File([wavBlob], nextName, {
    type: 'audio/wav',
    lastModified: Date.now(),
  })
}

export const clampVideoTargetDurationSec = (durationSec: number): number => {
  if (!Number.isFinite(durationSec) || durationSec <= 0) {
    return DEFAULT_VIDEO_OPTIONS.duration
  }
  return Math.max(5, Math.min(600, Math.round(durationSec)))
}

export const getAudioFileDurationSec = async (file: File): Promise<number> => {
  const buffer = await decodeAudioFile(file)
  return clampVideoTargetDurationSec(buffer.duration)
}

export const autoCropAudioFileToDuration = async (
  file: File,
  targetDurationSec: number,
): Promise<{ file: File; cropped: boolean; sourceDurationSec?: number }> => {
  if (!isAudioFile(file)) {
    return { file, cropped: false }
  }
  if (!Number.isFinite(targetDurationSec) || targetDurationSec <= 0) {
    return { file, cropped: false }
  }

  const sourceBuffer = await decodeAudioFile(file)
  const sourceDurationSec = sourceBuffer.duration
  if (!Number.isFinite(sourceDurationSec) || sourceDurationSec <= targetDurationSec + 0.05) {
    return { file, cropped: false, sourceDurationSec }
  }

  const croppedFile = await cropAudioFile(file, 0, targetDurationSec)
  return { file: croppedFile, cropped: true, sourceDurationSec }
}

const SMART_CROP_RECOMMEND_GAP_SEC = 1

export const smartCropAudioFileToTargetDuration = async (
  file: File,
  targetDurationSec: number,
): Promise<{ file: File; cropped: boolean; sourceDurationSec?: number }> => {
  if (!isAudioFile(file)) {
    return { file, cropped: false }
  }
  if (!Number.isFinite(targetDurationSec) || targetDurationSec <= 0) {
    return { file, cropped: false }
  }

  const sourceBuffer = await decodeAudioFile(file)
  const sourceDurationSec = sourceBuffer.duration
  if (
    !Number.isFinite(sourceDurationSec)
    || sourceDurationSec <= targetDurationSec + SMART_CROP_RECOMMEND_GAP_SEC
  ) {
    return { file, cropped: false, sourceDurationSec }
  }

  const startSec = 0
  const endSec = targetDurationSec

  const croppedFile = await cropAudioFile(file, startSec, endSec)
  return { file: croppedFile, cropped: true, sourceDurationSec }
}

export const smartCropUploadedAudioFiles = async (
  files: File[],
  targetDurationSec?: number | null,
): Promise<File[]> => {
  if (targetDurationSec == null || !Number.isFinite(targetDurationSec) || targetDurationSec <= 0) {
    return files
  }
  return Promise.all(
    files.map(async (file) => {
      if (!isAudioFile(file)) return file
      try {
        const result = await smartCropAudioFileToTargetDuration(file, targetDurationSec)
        return result.file
      } catch (error) {
        console.warn('Smart crop uploaded audio failed, keeping original file:', error)
        return file
      }
    }),
  )
}
