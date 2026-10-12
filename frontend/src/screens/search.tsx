"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Pager, Time } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { SelectField } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { PageHeader, Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { RESULTS_AT_ONCE, useRepositories, useSearch, type Wanted } from "@/lib/content";
import { readChecksum } from "@/lib/format";
import { browseHref, componentHref, searchHref } from "@/lib/paths";

// What the address carries. A checksum is one field: its length says which it is.
const FIELDS = ["q", "format", "repository", "namespace", "name", "version", "checksum"] as const;
type Field = (typeof FIELDS)[number];
type Values = Record<Field, string>;

function valuesOf(search: URLSearchParams): Values {
  return Object.fromEntries(FIELDS.map((field) => [field, search.get(field) ?? ""])) as Values;
}

/** The API's parameters for what was typed, or null if the checksum is not one. */
function wantedOf(values: Values): Wanted | null {
  const wanted: Wanted = {};
  for (const field of ["q", "format", "repository", "namespace", "name", "version"] as const) {
    const value = values[field].trim();
    if (value) wanted[field] = value;
  }
  if (values.checksum.trim()) {
    const checksum = readChecksum(values.checksum);
    if (checksum === null) return null;
    wanted[checksum.kind] = checksum.value;
  }
  return wanted;
}

function Results({ wanted, page, values }: { wanted: Wanted; page: number; values: Values }) {
  const t = useTranslations("search");
  const results = useSearch(wanted, page);
  // Another page replaces the link that led to it while it loads, and what had the
  // keyboard is gone. It is given to the line above the results, which says what they are.
  const top = useRef<HTMLParagraphElement>(null);
  const shown = useRef(page);
  const arrived = results.data !== undefined;
  useEffect(() => {
    if (!arrived || shown.current === page) return;
    shown.current = page;
    top.current?.focus();
  }, [page, arrived]);
  if (results.isError) {
    return <ErrorState error={results.error} onRetry={() => void results.refetch()} />;
  }
  if (!results.data) {
    return (
      <Panel>
        <LoadingState />
      </Panel>
    );
  }
  const { items, total } = results.data;
  if (total === 0) {
    return (
      <Panel>
        <EmptyState title={t("noneTitle")}>{t("none")}</EmptyState>
      </Panel>
    );
  }
  return (
    <Panel>
      <p ref={top} tabIndex={-1} role="status" className="px-4 pt-4 text-sm text-fg-muted">
        {t("found", { total })}
      </p>
      <Table caption={t("results")}>
        <thead>
          <tr>
            <Th>{t("columns.name")}</Th>
            <Th>{t("columns.namespace")}</Th>
            <Th>{t("columns.version")}</Th>
            <Th>{t("columns.repository")}</Th>
            <Th>{t("columns.format")}</Th>
            <Th>{t("columns.modified")}</Th>
          </tr>
        </thead>
        <tbody>
          {items.map((found) => (
            <tr key={`${found.repository}:${found.id}`} className="hover:bg-raised">
              <Td>
                <AppLink
                  href={componentHref(found.repository, found.id)}
                  className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                >
                  {found.name}
                </AppLink>
              </Td>
              <Td className="font-mono break-all text-fg-muted">{found.namespace}</Td>
              <Td className="font-mono break-all">{found.version}</Td>
              <Td>
                <AppLink
                  href={browseHref(found.repository)}
                  className="font-mono break-all underline-offset-4 hover:underline"
                >
                  {found.repository}
                </AppLink>
              </Td>
              <Td>{found.format}</Td>
              <Td className="whitespace-nowrap text-fg-muted">
                <Time value={found.modified} />
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <Pager
        page={page}
        pages={Math.ceil(total / RESULTS_AT_ONCE)}
        hrefFor={(target) =>
          searchHref({ ...values, page: target > 1 ? String(target) : undefined })
        }
      />
    </Panel>
  );
}

/**
 * Finding components. What is searched for is in the address, so a search can be
 * shared and the back button returns to the one before.
 */
export function SearchScreen() {
  const t = useTranslations("search");
  const router = useRouter();
  const search = useSearchParams();
  const asked = valuesOf(search);
  // The form starts from the address, and is its own until it is sent.
  const [values, setValues] = useState<Values>(asked);
  const [seen, setSeen] = useState(search.toString());
  if (seen !== search.toString()) {
    setSeen(search.toString());
    setValues(asked);
  }
  const repositories = useRepositories();
  const page = Math.max(1, Number.parseInt(search.get("page") ?? "1", 10) || 1);
  const wanted = wantedOf(asked);
  const typedChecksum = values.checksum.trim() !== "" && readChecksum(values.checksum) === null;

  const set = (field: Field) => (event: { target: { value: string } }) =>
    setValues((was) => ({ ...was, [field]: event.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    if (typedChecksum) return;
    router.push(
      searchHref(Object.fromEntries(FIELDS.map((field) => [field, values[field].trim()]))),
    );
  }

  const held = repositories.data?.items ?? [];
  const formats = Array.from(new Set(held.map((repository) => repository.format))).sort();
  const searched = held
    .filter((repository) => repository.type !== "group")
    .map((repository) => repository.name);
  const any = { value: "", label: t("any") };
  // What the form holds is always one of its choices, though it be none of the usual
  // ones (an address that names a group, or a format nothing here has): the filter that
  // is at work is then the one that is shown, and not "Any".
  const choices = (usual: string[], held: string) => [
    any,
    ...(held && !usual.includes(held) ? [held] : []).concat(usual).map((value) => ({
      value,
      label: value,
    })),
  ];
  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel className="mb-6 p-5">
        <form
          role="search"
          aria-label={t("title")}
          onSubmit={submit}
          className="flex flex-col gap-4"
          noValidate
        >
          <TextField
            label={t("fields.q")}
            hint={t("hints.q")}
            type="search"
            value={values.q}
            onChange={set("q")}
          />
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <SelectField
              label={t("fields.format")}
              value={values.format}
              onChange={set("format")}
              choices={choices(formats, values.format)}
            />
            <SelectField
              label={t("fields.repository")}
              value={values.repository}
              onChange={set("repository")}
              choices={choices(searched, values.repository)}
            />
            <TextField
              label={t("fields.namespace")}
              value={values.namespace}
              onChange={set("namespace")}
            />
            <TextField label={t("fields.name")} value={values.name} onChange={set("name")} />
            <TextField
              label={t("fields.version")}
              value={values.version}
              onChange={set("version")}
            />
            <TextField
              label={t("fields.checksum")}
              hint={t("hints.checksum")}
              error={typedChecksum ? t("notAChecksum") : null}
              spellCheck={false}
              value={values.checksum}
              onChange={set("checksum")}
            />
          </div>
          <div>
            <Button type="submit" variant="primary">
              <Search aria-hidden="true" className="size-4" />
              {t("submit")}
            </Button>
          </div>
        </form>
      </Panel>
      {wanted === null ? (
        <Alert tone="warning">{t("notAChecksum")}</Alert>
      ) : (
        <Results wanted={wanted} page={page} values={asked} />
      )}
    </>
  );
}
