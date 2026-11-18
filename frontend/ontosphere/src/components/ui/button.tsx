import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import type { VariantProps } from "class-variance-authority"
import { buttonVariants } from "./buttonVariants"

import { cn } from "@/lib/utils"


export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

// buttonVariants is a re-exported cva() const (not declared here, so allowConstantExport
// does not cover it); the co-export with Button is the shadcn-ui convention.
// eslint-disable-next-line react-refresh/only-export-components
export { Button, buttonVariants }
