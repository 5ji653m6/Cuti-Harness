import { useCallback, useMemo, useRef, useState } from 'react'
import { deepAgentV2Client, DeepAgentApiError } from './client'
import type { DeepAgentInputFile } from './types'

export type AttachmentUploadPhase = 'uploading' | 'saving' | 'ready' | 'error'

export type ComposerAttachment = {
  id: string
  file: File
  percent: number
  phase: AttachmentUploadPhase
  result?: DeepAgentInputFile
  error?: string
}

export type FileUploadState = {
  percent: number
  phase: AttachmentUploadPhase
}

const isAbortError = (error: unknown): boolean => (
  (error instanceof DOMException && error.name === 'AbortError')
  || (error instanceof Error && error.name === 'AbortError')
)

const newId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `att-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/**
 * Upload chat attachments as soon as they are selected, with per-file progress.
 * Sending a message only waits for these transfers; it does not start a second hop.
 */
export function useComposerAttachments() {
  const itemsRef = useRef<ComposerAttachment[]>([])
  const controllersRef = useRef(new Map<string, AbortController>())
  const pendingRef = useRef(new Map<string, Promise<DeepAgentInputFile>>())
  const [items, setItems] = useState<ComposerAttachment[]>([])

  const sync = useCallback((next: ComposerAttachment[]) => {
    itemsRef.current = next
    setItems(next)
  }, [])

  const patch = useCallback((id: string, partial: Partial<ComposerAttachment>) => {
    sync(itemsRef.current.map(item => (item.id === id ? { ...item, ...partial } : item)))
  }, [sync])

  const abortOne = useCallback((id: string) => {
    controllersRef.current.get(id)?.abort()
    controllersRef.current.delete(id)
    pendingRef.current.delete(id)
  }, [])

  const startUpload = useCallback((id: string, file: File) => {
    abortOne(id)
    const controller = new AbortController()
    controllersRef.current.set(id, controller)
    const pending = deepAgentV2Client.uploadFiles([file], {
      signal: controller.signal,
      onUploadProgress: (loaded, total) => {
        const percent = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : 0
        patch(id, {
          percent,
          phase: percent >= 100 ? 'saving' : 'uploading',
        })
      },
    }).then((uploaded) => {
      const result = uploaded[0]
      if (!result) throw new Error('Upload returned no file')
      patch(id, { percent: 100, phase: 'ready', result, error: undefined })
      return result
    }).catch((error: unknown) => {
      if (controller.signal.aborted || isAbortError(error)) {
        throw error
      }
      const message = error instanceof DeepAgentApiError || error instanceof Error
        ? error.message
        : String(error)
      patch(id, { phase: 'error', error: message })
      throw error
    }).finally(() => {
      controllersRef.current.delete(id)
    })
    pendingRef.current.set(id, pending)
    return pending
  }, [abortOne, patch])

  const addFiles = useCallback((files: File[]) => {
    if (files.length === 0) return itemsRef.current.length
    const startIndex = itemsRef.current.length
    const created: ComposerAttachment[] = files.map(file => ({
      id: newId(),
      file,
      percent: 0,
      phase: 'uploading',
    }))
    sync([...itemsRef.current, ...created])
    created.forEach(item => { startUpload(item.id, item.file) })
    return startIndex
  }, [startUpload, sync])

  const hydrateReady = useCallback((files: File[], results: DeepAgentInputFile[]) => {
    itemsRef.current.forEach(item => abortOne(item.id))
    sync(files.map((file, index) => ({
      id: newId(),
      file,
      percent: 100,
      phase: 'ready' as const,
      result: results[index],
    })))
  }, [abortOne, sync])

  const removeAt = useCallback((index: number) => {
    const target = itemsRef.current[index]
    if (target) abortOne(target.id)
    sync(itemsRef.current.filter((_, itemIndex) => itemIndex !== index))
  }, [abortOne, sync])

  const removeWhere = useCallback((predicate: (file: File, index: number) => boolean) => {
    const kept: ComposerAttachment[] = []
    itemsRef.current.forEach((item, index) => {
      if (predicate(item.file, index)) abortOne(item.id)
      else kept.push(item)
    })
    sync(kept)
  }, [abortOne, sync])

  const replaceAt = useCallback((index: number, file: File) => {
    const current = itemsRef.current[index]
    if (!current) {
      addFiles([file])
      return
    }
    abortOne(current.id)
    const next: ComposerAttachment = {
      id: newId(),
      file,
      percent: 0,
      phase: 'uploading',
    }
    sync(itemsRef.current.map((item, itemIndex) => (itemIndex === index ? next : item)))
    startUpload(next.id, file)
  }, [abortOne, addFiles, startUpload, sync])

  const clear = useCallback(() => {
    itemsRef.current.forEach(item => abortOne(item.id))
    sync([])
  }, [abortOne, sync])

  const waitUntilReady = useCallback(async (): Promise<DeepAgentInputFile[]> => {
    const snapshot = itemsRef.current
    if (snapshot.length === 0) return []
    const failed = snapshot.find(item => item.phase === 'error')
    if (failed) {
      throw new Error(failed.error || 'Attachment upload failed')
    }
    const results: DeepAgentInputFile[] = []
    for (const item of snapshot) {
      if (item.result) {
        results.push(item.result)
        continue
      }
      const pending = pendingRef.current.get(item.id)
      if (!pending) {
        throw new Error('Attachment upload did not start')
      }
      results.push(await pending)
    }
    if (results.length !== snapshot.length) {
      throw new Error('Some attachments failed to upload. Please try again.')
    }
    return results
  }, [])

  const files = useMemo(() => items.map(item => item.file), [items])
  const uploadStates = useMemo(
    (): FileUploadState[] => items.map(item => ({ percent: item.percent, phase: item.phase })),
    [items],
  )
  const hasUnfinished = items.some(item => item.phase === 'uploading' || item.phase === 'saving')
  const totalBytes = items.reduce((sum, item) => sum + item.file.size, 0)
  const overallPercent = totalBytes <= 0
    ? (items.length === 0 ? 0 : Math.round(items.reduce((sum, item) => sum + item.percent, 0) / items.length))
    : Math.round(items.reduce((sum, item) => sum + (item.file.size * item.percent), 0) / totalBytes)
  const overallPhase: AttachmentUploadPhase = items.some(item => item.phase === 'error')
    ? 'error'
    : items.some(item => item.phase === 'uploading')
      ? 'uploading'
      : items.some(item => item.phase === 'saving')
        ? 'saving'
        : 'ready'

  return {
    items,
    files,
    uploadStates,
    addFiles,
    hydrateReady,
    removeAt,
    removeWhere,
    replaceAt,
    clear,
    waitUntilReady,
    hasUnfinished,
    overallPercent,
    overallPhase,
  }
}
