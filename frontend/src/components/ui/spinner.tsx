import { LoaderCircle } from "lucide-react";

import { cn } from "@/lib/cn";

/** Something is under way. It is decoration: what is under way is said in words beside it. */
export function Spinner({ className }: { className?: string }) {
  return (
    <LoaderCircle
      aria-hidden="true"
      className={cn("size-4 shrink-0 motion-safe:animate-spin", className)}
    />
  );
}
