"use client";

import { CircleAlert } from "lucide-react";
import { useId, type InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  label: string;
  /** Said under the field while nothing is wrong. */
  hint?: string;
  /** What is wrong with what was typed. It replaces the hint. */
  error?: string | null;
};

/** A labelled input. Its hint and its error are read out with it. */
export function TextField({ label, hint, error, className, ...input }: TextFieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const described = error ? errorId : hint ? hintId : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="label-caps text-fg-muted">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={described}
        className={cn(
          "min-h-10 rounded-sm border bg-field px-3 py-2 text-fg placeholder:text-fg-subtle",
          "transition-[border-color,box-shadow] focus:shadow-glow-sm",
          error ? "border-bad" : "border-line-strong hover:border-neon-cyan",
        )}
        {...input}
      />
      {error ? (
        <p id={errorId} className="flex items-start gap-1.5 text-sm text-ink-bad">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </p>
      ) : hint ? (
        <p id={hintId} className="text-sm text-fg-subtle">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
