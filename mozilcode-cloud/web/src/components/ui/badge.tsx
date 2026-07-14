import { cn } from '@/lib/utils'

function Badge({
  className,
  variant = 'default',
  ...props
}: React.ComponentProps<'span'> & {
  variant?: 'default' | 'secondary' | 'outline' | 'success' | 'warning' | 'danger'
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold',
        variant === 'default' && 'bg-primary text-primary-foreground',
        variant === 'secondary' && 'bg-secondary text-secondary-foreground',
        variant === 'outline' && 'border border-border text-muted-foreground',
        variant === 'success' && 'bg-emerald-500/12 text-emerald-600 dark:text-emerald-400',
        variant === 'warning' && 'bg-amber-500/12 text-amber-600 dark:text-amber-400',
        variant === 'danger' && 'bg-red-500/12 text-red-600 dark:text-red-400',
        className,
      )}
      {...props}
    />
  )
}

export { Badge }