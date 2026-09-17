import * as React from 'react'
import * as SliderPrimitive from '@radix-ui/react-slider'
import { Clock } from 'lucide-react'

import { cn } from '@/lib/utils'

export type SliderThumbStyle = 'default' | 'minimal'

export interface SliderProps extends React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root> {
  thumbStyle?: SliderThumbStyle
}

const Slider = React.forwardRef<
  React.ElementRef<typeof SliderPrimitive.Root>,
  SliderProps
>(({ className, thumbStyle = 'default', ...props }, ref) => (
  <SliderPrimitive.Root
    ref={ref}
    className={cn(
      'relative flex w-full touch-none select-none items-center',
      thumbStyle === 'minimal' && '[&_.bg-secondary]:bg-neutral-200',
      className,
    )}
    {...props}
  >
    <SliderPrimitive.Track
      className={cn(
        'relative w-full grow overflow-hidden rounded-full bg-secondary',
        thumbStyle === 'minimal' ? 'h-1' : 'h-2',
      )}
    >
      <SliderPrimitive.Range className="absolute h-full bg-primary" />
    </SliderPrimitive.Track>
    <SliderPrimitive.Thumb
      className={cn(
        'flex items-center justify-center rounded-full transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50',
        thumbStyle === 'default' && 'h-6 w-6 border-2 border-primary bg-background',
        thumbStyle === 'minimal' &&
          'h-3.5 w-3.5 border border-violet-400 bg-white shadow-[0_0_0_1px_rgba(192,132,252,0.35)]',
      )}
    >
      {thumbStyle === 'default' ? <Clock className="h-3 w-3 text-primary" /> : null}
    </SliderPrimitive.Thumb>
  </SliderPrimitive.Root>
))
Slider.displayName = SliderPrimitive.Root.displayName

export { Slider }
