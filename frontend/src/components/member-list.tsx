"use client";

import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/inputs";
import { moved } from "@/lib/repository-form";

type Asked = { name: string; button: "up" | "down" } | { add: true };

/**
 * The members of a group, in the order they are tried (R5): the first that has what is
 * asked for answers, so the order is part of the setting. Each member can be moved up,
 * moved down and taken out by a button, which a keyboard can press where it could not
 * drag; one is added from the list of those that are not members yet.
 */
export function MemberList({
  legend,
  hint,
  members,
  onChange,
  candidates,
  error,
  disabled = false,
}: {
  legend: string;
  hint?: string;
  members: string[];
  onChange: (members: string[]) => void;
  /**
   * The repositories that could be added: of the group's format, the group itself left
   * out. Null while that is not known, which the screen says: nothing is then offered,
   * and nothing is said to be missing.
   */
  candidates: string[] | null;
  error?: string | null;
  disabled?: boolean;
}) {
  const t = useTranslations("members");
  const id = useId();
  const list = useRef<HTMLFieldSetElement>(null);
  const free = (candidates ?? []).filter((name) => !members.includes(name));
  // The one that the list to add from shows. It follows what there is to add.
  const [chosen, setChosen] = useState("");
  const adding = free.includes(chosen) ? chosen : (free[0] ?? "");
  // What was done last, for a screen reader, which does not see a row move.
  const [said, setSaid] = useState("");
  // Where the keyboard goes once the list is drawn again: a row that moved takes its
  // buttons with it, and a button that can do no more (at an end) cannot keep the
  // keyboard. Asked for by what was pressed, and done once, after the next drawing.
  const asked = useRef<Asked | null>(null);
  useEffect(() => {
    const wanted = asked.current;
    if (wanted === null) return;
    asked.current = null;
    const within = list.current;
    if ("add" in wanted) {
      // The list to add from is not there when nothing is left to add: then the last
      // member's own button, and with no member either, the members themselves.
      const rows = within?.querySelectorAll<HTMLElement>('[data-button="remove"]');
      const next =
        within?.querySelector<HTMLElement>("select, [data-add]") ?? rows?.[rows.length - 1];
      (next ?? within)?.focus();
      return;
    }
    const row = Array.from(within?.querySelectorAll<HTMLElement>("li") ?? []).find(
      (item) => item.dataset.member === wanted.name,
    );
    const same = row?.querySelector<HTMLButtonElement>(`[data-button="${wanted.button}"]`);
    const other = row?.querySelector<HTMLButtonElement>(
      `[data-button="${wanted.button === "up" ? "down" : "up"}"]`,
    );
    (same && !same.disabled ? same : other)?.focus();
  });

  function move(name: string, by: -1 | 1) {
    const next = moved(members, name, by);
    onChange(next);
    setSaid(t("nowAt", { name, place: next.indexOf(name) + 1, of: next.length }));
    asked.current = { name, button: by < 0 ? "up" : "down" };
  }

  return (
    <fieldset
      ref={list}
      // Not a stop of its own: it takes the keyboard only when nothing in it can.
      tabIndex={-1}
      disabled={disabled}
      aria-describedby={hint ? `${id}-hint` : undefined}
      className="flex min-w-0 flex-col gap-3 border-0 p-0"
    >
      <legend className="label-caps mb-1 p-0 text-fg-muted">{legend}</legend>
      {hint ? (
        <p id={`${id}-hint`} className="text-sm text-fg-subtle">
          {hint}
        </p>
      ) : null}
      <div className="flex flex-col gap-3">
        {members.length === 0 ? <p className="text-sm text-fg-subtle">{t("none")}</p> : null}
        <ol className="flex flex-col gap-2">
          {members.map((name, index) => (
            <li
              key={name}
              data-member={name}
              className="flex items-center gap-2 rounded-sm border border-line bg-field px-3 py-1.5"
            >
              <span aria-hidden="true" className="w-6 shrink-0 font-mono text-sm text-fg-subtle">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 font-mono text-sm break-all text-fg">{name}</span>
              <Button
                size="sm"
                variant="ghost"
                data-button="up"
                disabled={index === 0}
                aria-label={t("up", { name })}
                onClick={() => move(name, -1)}
              >
                <ArrowUp aria-hidden="true" className="size-4" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                data-button="down"
                disabled={index === members.length - 1}
                aria-label={t("down", { name })}
                onClick={() => move(name, 1)}
              >
                <ArrowDown aria-hidden="true" className="size-4" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                data-button="remove"
                aria-label={t("remove", { name })}
                onClick={() => {
                  onChange(members.filter((member) => member !== name));
                  setSaid(t("removed", { name }));
                  asked.current = { add: true };
                }}
              >
                <X aria-hidden="true" className="size-4" />
              </Button>
            </li>
          ))}
        </ol>
        {candidates === null ? null : free.length === 0 ? (
          <p className="text-sm text-fg-subtle">{t("nothingToAdd")}</p>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <SelectField
              label={t("candidate")}
              value={adding}
              onChange={(event) => setChosen(event.target.value)}
              choices={free.map((name) => ({ value: name, label: name }))}
            />
            <Button
              data-add
              onClick={() => {
                onChange([...members, adding]);
                setSaid(t("added", { name: adding, place: members.length + 1 }));
                asked.current = { add: true };
              }}
            >
              <Plus aria-hidden="true" className="size-4" />
              {t("add")}
            </Button>
          </div>
        )}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-ink-bad">
          {error}
        </p>
      ) : null}
      <p role="status" className="sr-only">
        {said}
      </p>
    </fieldset>
  );
}
