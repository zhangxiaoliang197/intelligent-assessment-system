import * as React from "react"
import * as TogglePrimitive from "@radix-ui/react-toggle"
import type { VariantProps } from "class-variance-authority"
import { toggleVariants } from "./toggleVariants"

import { cn } from "@/lib/utils"


const Toggle = React.forwardRef<
  React.ElementRef<typeof TogglePrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof TogglePrimitive.Root> &
    VariantProps<typeof toggleVariants>
>(({ className, variant, size, ...props }, ref) => (
  <TogglePrimitive.Root
    ref={ref}
    className={cn(toggleVariants({ variant, size, className }))}
    {...props}
  />
))

Toggle.displayName = TogglePrimitive.Root.displayName

// toggleVariants is a re-exported cva() const (not declared here, so allowConstantExport
// does not cover it); the co-export with Toggle is the shadcn-ui convention.
// eslint-disable-next-line react-refresh/only-export-components
export { Toggle, toggleVariants }
