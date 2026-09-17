import { toast } from 'sonner'

/** Adapt asynchronous UI actions to React event handlers and surface uncaught failures. */
export function asyncEvent<Args extends unknown[]>(handler: (...args: Args) => Promise<unknown>): (...args: Args) => void {
  return (...args) => {
    void handler(...args).catch((error: unknown) => {
      console.error('UI action failed:', error)
      toast.error(error instanceof Error && error.message
        ? error.message
        : localStorage.getItem('language') === 'zh' ? '操作失败，请重试。' : 'Action failed. Please try again.')
    })
  }
}
