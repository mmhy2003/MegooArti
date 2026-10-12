"use client";

import { FileUp, X } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useId,
  useState,
  type DragEvent,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
} from "react";

import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";

/** The inputs a form has besides a line of text: a choice, a tick, and files. */

export type Choice = { value: string; label: string };

/** One of several, as the browser's own list: it works with every keyboard and reader. */
export function SelectField({
  label,
  choices,
  className,
  ...select
}: Omit<SelectHTMLAttributes<HTMLSelectElement>, "id"> & { label: string; choices: Choice[] }) {
  const id = useId();
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="label-caps text-fg-muted">
        {label}
      </label>
      <select
        id={id}
        className="min-h-10 rounded-sm border border-line-strong bg-field px-3 py-2 text-fg hover:border-neon-cyan focus:shadow-glow-sm"
        {...select}
      >
        {choices.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Yes or no, with what it means beside it. */
export function CheckboxField({
  label,
  hint,
  className,
  ...input
}: Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "type"> & { label: string; hint?: string }) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className={cn("flex items-start gap-3", className)}>
      <input
        id={id}
        type="checkbox"
        aria-describedby={hint ? hintId : undefined}
        className="mt-1 size-4 shrink-0 accent-primary"
        {...input}
      />
      <div className="min-w-0">
        <label htmlFor={id} className="text-fg">
          {label}
        </label>
        {hint ? (
          <p id={hintId} className="text-sm text-fg-subtle">
            {hint}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export type FilePickerProps = {
  label: string;
  hint?: string;
  error?: string | null;
  /** Several files, or one. With one, choosing again replaces it. */
  multiple?: boolean;
  /** What the browser's own dialog offers first: `.tgz`, `.whl,.tar.gz,.zip`. */
  accept?: string;
  files: File[];
  onChange: (files: File[]) => void;
};

/**
 * Files to send: chosen with the browser's own dialog, or dropped here. The input is the
 * real one, so the keyboard and a screen reader use it as any file input; what was
 * chosen is listed under it, each with a way to take it out again.
 */
export function FilePicker({
  label,
  hint,
  error,
  multiple = false,
  accept,
  files,
  onChange,
}: FilePickerProps) {
  const t = useTranslations("files");
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  const [over, setOver] = useState(false);

  function take(taken: FileList | null) {
    const added = Array.from(taken ?? []);
    if (added.length === 0) return;
    onChange(multiple ? [...files, ...added] : added.slice(0, 1));
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setOver(false);
    take(event.dataTransfer.files);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="label-caps text-fg-muted">
        {label}
      </label>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={cn(
          "flex flex-wrap items-center gap-3 rounded-sm border border-dashed bg-field px-4 py-4",
          "focus-within:shadow-glow-sm",
          error ? "border-bad" : over ? "border-neon-cyan bg-raised" : "border-line-strong",
        )}
      >
        <FileUp aria-hidden="true" className="size-6 shrink-0 text-neon-cyan" />
        <input
          id={id}
          type="file"
          multiple={multiple}
          accept={accept}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          // The same file can be chosen again after it was taken out. The input is so
          // always empty, and the browser's own "No file chosen" beside it would deny the
          // list below: its text is not shown, only its button.
          value=""
          onChange={(event) => take(event.target.files)}
          className="min-w-0 flex-1 text-sm text-transparent file:mr-3 file:rounded-sm file:border file:border-line-strong file:bg-panel file:px-3 file:py-1.5 file:text-fg"
        />
        <span className="text-sm text-fg-subtle">{t("orDrop")}</span>
      </div>
      {error ? (
        <p id={`${id}-error`} className="text-sm text-ink-bad">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-sm text-fg-subtle">
          {hint}
        </p>
      ) : null}
      {files.length > 0 ? (
        <ul aria-label={t("chosen", { label })} className="flex flex-col gap-1">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${index}`}
              className="flex items-center gap-2 rounded-sm bg-raised px-3 py-1.5 text-sm"
            >
              <span className="min-w-0 flex-1 font-mono break-all text-fg">{file.name}</span>
              <span className="shrink-0 text-fg-muted">{formatBytes(file.size)}</span>
              <button
                type="button"
                aria-label={t("remove", { name: file.name })}
                onClick={() => onChange(files.filter((_, at) => at !== index))}
                className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm text-fg-muted hover:text-ink-bad"
              >
                <X aria-hidden="true" className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
