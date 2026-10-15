"use client";

import { CircleAlert } from "lucide-react";
import { useId, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/** What a field says under it, and the ids it is read out by. */
type Said = {
  /** Said under the field while nothing is wrong. */
  hint?: string;
  /** What is wrong with what was typed. It replaces the hint. */
  error?: string | null;
};

export type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> &
  Said & {
    label: string;
    /** The label has a name in it that must be read exactly: it is not put in capitals. */
    plainLabel?: boolean;
  };

export type TextAreaFieldProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "id"> &
  Said & { label: string };

/** The ids of a field, its hint and its error, and which of those it is described by. */
function useIds({ hint, error }: Said) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  return { id, hintId, errorId, described: error ? errorId : hint ? hintId : undefined };
}

function Under({ hint, error, hintId, errorId }: Said & { hintId: string; errorId: string }) {
  return error ? (
    <p id={errorId} className="flex items-start gap-1.5 text-sm text-ink-bad">
      <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{error}</span>
    </p>
  ) : hint ? (
    <p id={hintId} className="text-sm text-fg-subtle">
      {hint}
    </p>
  ) : null;
}

const BOX = "rounded-sm border bg-field px-3 py-2 text-fg placeholder:text-fg-subtle";
const FOCUS = "transition-[border-color,box-shadow] focus:shadow-glow-sm";
const edge = (error: string | null | undefined) =>
  error ? "border-bad" : "border-line-strong hover:border-neon-cyan";

/** A labelled input. Its hint and its error are read out with it. */
export function TextField({
  label,
  hint,
  error,
  plainLabel = false,
  className,
  ...input
}: TextFieldProps) {
  const { id, hintId, errorId, described } = useIds({ hint, error });
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label
        htmlFor={id}
        className={cn("text-fg-muted", plainLabel ? "text-sm font-medium" : "label-caps")}
      >
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={described}
        className={cn("min-h-10", BOX, FOCUS, edge(error))}
        {...input}
      />
      <Under hint={hint} error={error} hintId={hintId} errorId={errorId} />
    </div>
  );
}

/** A labelled field of several lines, for what is pasted whole: a key. */
export function TextAreaField({ label, hint, error, className, ...area }: TextAreaFieldProps) {
  const { id, hintId, errorId, described } = useIds({ hint, error });
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="label-caps text-fg-muted">
        {label}
      </label>
      <textarea
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={described}
        rows={6}
        spellCheck={false}
        className={cn("font-mono text-xs leading-5", BOX, FOCUS, edge(error))}
        {...area}
      />
      <Under hint={hint} error={error} hintId={hintId} errorId={errorId} />
    </div>
  );
}
