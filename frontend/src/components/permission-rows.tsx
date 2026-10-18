"use client";

import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { SelectField, type Choice } from "@/components/ui/inputs";
import {
  ADMIN_ACTIONS,
  ADMIN_AREAS,
  ANY,
  fromPattern,
  isValidPattern,
  REPOSITORY_ACTIONS,
  startOf,
  toPattern,
  type Row,
  type RowKind,
} from "@/lib/patterns";

const KINDS: readonly RowKind[] = ["repository", "admin", "all", "typed"];
// The formats there are, whether or not a repository of each exists yet.
const FORMATS = ["raw", "maven", "npm", "pypi", "docker", "apt", "yum", "apk", "nuget"];

/** A repository, as far as a permission is concerned: what it is called and its format. */
export type Held = { name: string; format: string };

/** Whether patterns can be saved as they are: each is one, and none is empty. */
export function patternsAreValid(patterns: string[]): boolean {
  return patterns.every((pattern) => pattern !== "" && isValidPattern(pattern));
}

/** What a pattern grants, in words. Null for what is not a pattern. */
export function usePatternWords(): (pattern: string) => string | null {
  const t = useTranslations("permissions");
  return (pattern) => {
    if (pattern === "" || !isValidPattern(pattern)) return null;
    const row = fromPattern(pattern);
    switch (row.kind) {
      case "all":
        return t("grants.all");
      case "repository": {
        const { format, name } = row;
        const where =
          format === ANY && name === ANY
            ? t("grants.everyRepository")
            : name === ANY
              ? t("grants.everyOfFormat", { format })
              : format === ANY
                ? t("grants.everyNamed", { name })
                : t("grants.oneRepository", { format, name });
        const action = row.action === ANY ? "any" : (row.action as "read");
        return t("grants.repository", { action: t(`grants.doing.${action}`), where });
      }
      case "admin": {
        const action = row.action === ANY ? "any" : (row.action as "read");
        const area = row.area === ANY ? "any" : (row.area as "users");
        return t("grants.admin", {
          action: t(`grants.administering.${action}`),
          area: t(`grants.areas.${area}`),
        });
      }
      case "typed":
        return t("grants.other");
    }
  };
}

/** Patterns as they stand, for whoever may read them and not change them. */
export function PermissionList({ patterns, empty }: { patterns: string[]; empty: string }) {
  const words = usePatternWords();
  if (patterns.length === 0) return <p className="text-sm text-fg-subtle">{empty}</p>;
  return (
    <ul className="flex flex-col gap-2">
      {patterns.map((pattern) => (
        <li key={pattern} className="rounded-sm border border-line bg-field px-3 py-2">
          <code className="font-mono text-sm break-all text-fg">{pattern}</code>
          <p className="text-sm text-fg-muted">{words(pattern)}</p>
        </li>
      ))}
    </ul>
  );
}

type Kept = { id: number; row: Row };

/**
 * Permissions as rows (A2). A row says what it is about, and the lists that follow
 * make its pattern, which is shown beside it with what it grants. Anything the lists
 * cannot say is typed by hand: nothing a role holds is lost by opening it here.
 *
 * It starts from `initial` and then keeps its own rows: `onChange` is told the
 * patterns as they stand, some of which may not be patterns yet.
 */
export function PermissionRows({
  legend,
  initial,
  onChange,
  repositories,
  checked = false,
}: {
  legend: string;
  initial: string[];
  onChange: (patterns: string[]) => void;
  repositories: Held[];
  /** Saving was tried: a row that is still empty is now said to be wrong. */
  checked?: boolean;
}) {
  const t = useTranslations("permissions");
  const words = usePatternWords();
  const next = useRef(initial.length);
  const [rows, setRows] = useState<Kept[]>(() =>
    initial.map((pattern, id) => ({ id, row: fromPattern(pattern) })),
  );
  const list = useRef<HTMLOListElement>(null);
  const adder = useRef<HTMLDivElement>(null);
  // The row to give the keyboard to once it is on the screen: the one just added.
  const [added, setAdded] = useState<number | null>(null);
  useEffect(() => {
    if (added === null) return;
    list.current?.querySelector<HTMLElement>(`[data-row="${added}"] select`)?.focus();
  }, [added]);

  function change(to: Kept[]) {
    setRows(to);
    onChange(to.map((kept) => toPattern(kept.row)));
  }
  const set = (id: number, row: Row) =>
    change(rows.map((kept) => (kept.id === id ? { id, row } : kept)));

  const any: Choice = { value: ANY, label: t("any") };
  const listed = (values: readonly string[], held: string, label: (value: string) => string) => [
    any,
    // What a row holds is always one of its choices, though it be a repository that is
    // gone or a format this list does not know.
    ...(held !== ANY && !values.includes(held) ? [held, ...values] : values).map((value) => ({
      value,
      label: label(value),
    })),
  ];
  const plain = (value: string) => value;
  const formats = Array.from(
    new Set([...FORMATS, ...repositories.map((held) => held.format)]),
  ).sort();

  return (
    <fieldset className="flex min-w-0 flex-col gap-3 border-0 p-0">
      <legend className="label-caps mb-1 p-0 text-fg-muted">{legend}</legend>
      {rows.length === 0 ? <p className="text-sm text-fg-subtle">{t("none")}</p> : null}
      <ol ref={list} className="flex flex-col gap-3">
        {rows.map(({ id, row }, index) => {
          const number = index + 1;
          const pattern = toPattern(row);
          const said = words(pattern);
          const wrong =
            row.kind === "typed" && said === null && (pattern !== "" || checked)
              ? t("notAPattern")
              : null;
          return (
            <li key={id} data-row={id}>
              <fieldset className="flex min-w-0 flex-col gap-3 rounded-sm border border-line p-3">
                <legend className="sr-only">{t("row", { number })}</legend>
                <div className="flex flex-wrap items-end gap-3">
                  <SelectField
                    label={t("about")}
                    value={row.kind}
                    onChange={(event) => set(id, startOf(event.target.value as RowKind))}
                    choices={KINDS.map((kind) => ({ value: kind, label: t(`kinds.${kind}`) }))}
                  />
                  {row.kind === "repository" ? (
                    <>
                      <SelectField
                        label={t("format")}
                        value={row.format}
                        // The repository stays as it was chosen, though it is one of
                        // another format: set to "any", the row would grant its action
                        // in every repository of the new format, by a side effect.
                        onChange={(event) => set(id, { ...row, format: event.target.value })}
                        choices={listed(formats, row.format, plain)}
                      />
                      <SelectField
                        label={t("repository")}
                        value={row.name}
                        onChange={(event) => set(id, { ...row, name: event.target.value })}
                        choices={listed(
                          repositories
                            .filter((held) => row.format === ANY || held.format === row.format)
                            .map((held) => held.name),
                          row.name,
                          plain,
                        )}
                      />
                      <SelectField
                        label={t("action")}
                        value={row.action}
                        onChange={(event) => set(id, { ...row, action: event.target.value })}
                        choices={listed(REPOSITORY_ACTIONS, row.action, (action) =>
                          t(`actions.${action as "read"}`),
                        )}
                      />
                    </>
                  ) : null}
                  {row.kind === "admin" ? (
                    <>
                      <SelectField
                        label={t("area")}
                        value={row.area}
                        onChange={(event) => set(id, { ...row, area: event.target.value })}
                        choices={listed(ADMIN_AREAS, row.area, (area) =>
                          t(`areas.${area as "users"}`),
                        )}
                      />
                      <SelectField
                        label={t("action")}
                        value={row.action}
                        onChange={(event) => set(id, { ...row, action: event.target.value })}
                        choices={listed(ADMIN_ACTIONS, row.action, (action) =>
                          t(`actions.${action as "read"}`),
                        )}
                      />
                    </>
                  ) : null}
                  {row.kind === "typed" ? (
                    <TextField
                      className="min-w-48 flex-1"
                      label={t("pattern")}
                      spellCheck={false}
                      autoComplete="off"
                      value={row.text}
                      error={wrong}
                      onChange={(event) => set(id, { kind: "typed", text: event.target.value })}
                    />
                  ) : null}
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto"
                    aria-label={t("remove", { number })}
                    onClick={() => {
                      change(rows.filter((kept) => kept.id !== id));
                      // This button goes with its row: the keyboard goes to the one that adds.
                      adder.current?.querySelector("button")?.focus();
                    }}
                  >
                    <X aria-hidden="true" className="size-4" />
                  </Button>
                </div>
                {said === null ? null : (
                  <p className="text-sm text-fg-muted">
                    <code className="mr-2 font-mono break-all text-fg">{pattern}</code>
                    {said}
                  </p>
                )}
              </fieldset>
            </li>
          );
        })}
      </ol>
      <div ref={adder}>
        <Button
          size="sm"
          onClick={() => {
            const id = next.current++;
            change([...rows, { id, row: startOf("repository") }]);
            setAdded(id);
          }}
        >
          <Plus aria-hidden="true" className="size-4" />
          {t("add")}
        </Button>
      </div>
    </fieldset>
  );
}
