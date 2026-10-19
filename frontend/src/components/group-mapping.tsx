"use client";

import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/field";
import { SelectField } from "@/components/ui/inputs";

/** One row: the members of a group are given a role. */
export type Grant = { group: string; role: string };
export type Mapping = { group: string; roles: string[] }[];

/** A source's mapping as rows, one a group and a role. */
export function toGrants(mapping: Mapping): Grant[] {
  return mapping.flatMap(({ group, roles }) => roles.map((role) => ({ group, role })));
}

/** Rows as the API keeps them: each group once, with its roles. A row half filled is left out. */
export function toMapping(grants: Grant[]): Mapping {
  const byGroup = new Map<string, string[]>();
  for (const { group, role } of grants) {
    const named = group.trim();
    if (named === "" || role === "") continue;
    const roles = byGroup.get(named) ?? [];
    if (!roles.includes(role)) roles.push(role);
    byGroup.set(named, roles);
  }
  return Array.from(byGroup, ([group, roles]) => ({ group, roles }));
}

/**
 * The roles a source's groups give (E4): a row says that the members of a group are given
 * a role. They are given it at each sign-in, and it is taken back when they are no longer.
 */
export function GroupMapping({
  grants,
  roles,
  onChange,
  error,
}: {
  grants: Grant[];
  /** The roles there are, to choose from. */
  roles: string[];
  onChange: (grants: Grant[]) => void;
  error?: string;
}) {
  const t = useTranslations("source");
  // A role a row has is offered, whether or not the roles there are came yet, or can be seen.
  const offered = Array.from(new Set([...roles, ...grants.map((grant) => grant.role)]))
    .filter(Boolean)
    .sort();
  const set = (index: number, changed: Partial<Grant>) =>
    onChange(grants.map((grant, at) => (at === index ? { ...grant, ...changed } : grant)));
  return (
    <fieldset className="flex min-w-0 flex-col gap-3 border-0 p-0">
      <legend className="label-caps mb-2 text-fg-muted">{t("mapping")}</legend>
      <p className="text-sm text-fg-subtle">{t("mappingHint")}</p>
      {grants.length === 0 ? <p className="text-fg-muted">{t("noMapping")}</p> : null}
      <ol className="flex flex-col gap-3">
        {grants.map((grant, index) => (
          <li key={index} className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto]">
            <TextField
              label={t("group", { number: index + 1 })}
              spellCheck={false}
              autoComplete="off"
              value={grant.group}
              onChange={(event) => set(index, { group: event.target.value })}
            />
            <SelectField
              label={t("role", { number: index + 1 })}
              value={grant.role}
              onChange={(event) => set(index, { role: event.target.value })}
              choices={[
                { value: "", label: t("chooseRole") },
                ...offered.map((role) => ({ value: role, label: role })),
              ]}
            />
            <Button
              size="sm"
              aria-label={t("removeGrant", { number: index + 1 })}
              onClick={() => onChange(grants.filter((_, at) => at !== index))}
            >
              <X aria-hidden="true" className="size-4" />
            </Button>
          </li>
        ))}
      </ol>
      {error ? (
        <p role="alert" className="text-sm text-ink-bad">
          {error}
        </p>
      ) : null}
      <div>
        <Button size="sm" onClick={() => onChange([...grants, { group: "", role: "" }])}>
          <Plus aria-hidden="true" className="size-4" />
          {t("addGrant")}
        </Button>
      </div>
    </fieldset>
  );
}
