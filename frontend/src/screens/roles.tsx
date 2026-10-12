"use client";

import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { PermissionList, PermissionRows, patternsAreValid } from "@/components/permission-rows";
import { Alert, StatusTag } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Pager } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { CheckList } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { isApiError } from "@/lib/api/client";
import type { RoleOut } from "@/lib/api/types";
import { useRepositories } from "@/lib/content";
import { useAttempts, usePageFocus, useWithinPages } from "@/lib/focus";
import { isAddressable, NEW_ROLE, pageHref, pageOf, parseRole, roleHref, ROLES } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import {
  AT_ONCE,
  useCreateRole,
  useDeleteRole,
  useEveryRole,
  useRole,
  useRoles,
  useUpdateRole,
} from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

// The server's rule for a role's name, said before the request is made.
const NAME = /^[A-Za-z0-9_.-]{1,64}$/;
const ADMIN = "admin";
const H2 = "mb-4 text-lg font-semibold text-fg uppercase";

function useMayWrite(): boolean {
  const session = useSession();
  return session.data !== undefined && allows(session.data, "admin:roles:write");
}

/** The roles there are (A13): what each is called, and what it holds. */
export function RolesScreen() {
  const t = useTranslations("roles");
  const page = pageOf(useSearchParams());
  const roles = useRoles(page);
  const mayWrite = useMayWrite();
  const pages = roles.data === undefined ? undefined : Math.ceil(roles.data.total / AT_ONCE);
  const hrefFor = (target: number) => pageHref(ROLES, target);
  const top = usePageFocus<HTMLDivElement>(page, roles.data !== undefined);
  const beyond = useWithinPages(page, pages, hrefFor);

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")}>
        {mayWrite ? (
          <Button asChild variant="primary" size="sm">
            <AppLink href={NEW_ROLE}>
              <Plus aria-hidden="true" className="size-4" />
              {t("new")}
            </AppLink>
          </Button>
        ) : null}
      </PageHeader>
      {roles.isError ? (
        <ErrorState error={roles.error} onRetry={() => void roles.refetch()} />
      ) : !roles.data || beyond ? (
        <Panel>
          <LoadingState />
        </Panel>
      ) : (
        <Panel>
          {/* Named, and able to take the keyboard: it is put here when a page is turned. */}
          <div
            ref={top}
            tabIndex={-1}
            role="group"
            aria-label={t("title")}
            className="outline-none"
          >
            <Table caption={t("title")}>
              <thead>
                <tr>
                  <Th>{t("columns.name")}</Th>
                  <Th>{t("columns.description")}</Th>
                  <Th>{t("columns.permissions")}</Th>
                  <Th>{t("columns.contains")}</Th>
                </tr>
              </thead>
              <tbody>
                {roles.data.items.map((role) => (
                  <tr key={role.name} className="hover:bg-raised">
                    <Td>
                      <div className="flex flex-wrap items-center gap-2">
                        {isAddressable(role.name) ? (
                          <AppLink
                            href={roleHref(role.name)}
                            className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                          >
                            {role.name}
                          </AppLink>
                        ) : (
                          // Made through the API with a name no page can have.
                          <span className="font-mono font-medium text-fg">{role.name}</span>
                        )}
                        {role.builtin ? <StatusTag tone="info">{t("builtin")}</StatusTag> : null}
                      </div>
                    </Td>
                    <Td className="break-words text-fg-muted">{role.description}</Td>
                    <Td className="font-mono text-xs break-all">{role.permissions.join(", ")}</Td>
                    <Td className="font-mono text-xs break-all">{role.roles.join(", ")}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          <Pager page={page} pages={pages ?? 1} hrefFor={hrefFor} />
        </Panel>
      )}
    </>
  );
}

type Content = { name: string; description: string; permissions: string[]; roles: string[] };

/**
 * The form of a role, new or not: its description, its permissions as rows (A2), and
 * the roles it contains. `onSave` is given what the form holds once it can be sent.
 */
function RoleForm({
  role,
  saving,
  error,
  onSave,
  saveLabel,
}: {
  /** The role as it is, or null for one that is not there yet, which also has a name. */
  role: RoleOut | null;
  saving: boolean;
  error: unknown;
  onSave: (content: Content) => void;
  saveLabel: string;
}) {
  const t = useTranslations("roles");
  const repositories = useRepositories();
  const others = useEveryRole();
  const [name, setName] = useState("");
  const [description, setDescription] = useState(role?.description ?? "");
  const [permissions, setPermissions] = useState(role?.permissions ?? []);
  const [contained, setContained] = useState(role?.roles ?? []);
  const { form, tried: checked, attempt } = useAttempts(error);

  const refused = refusalsOf(error, ["name", "description", "permissions", "roles"]);
  // A name another role has: said at the name.
  const taken = isApiError(error) && error.code === "conflict" ? error.message : null;
  const ownName =
    role !== null
      ? undefined
      : !NAME.test(name)
        ? t("nameRule")
        : isAddressable(name)
          ? undefined
          : t("nameDots");
  const nameProblem = checked ? (ownName ?? taken ?? refused.at.name) : undefined;

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    if (ownName || !patternsAreValid(permissions)) return;
    onSave({ name, description: description.trim(), permissions, roles: contained });
  }

  // A role does not contain itself, and what it contains is one of the choices though
  // it be beyond what was fetched.
  const names = Array.from(
    new Set([...(others.data?.items.map((other) => other.name) ?? []), ...contained]),
  )
    .filter((other) => other !== role?.name)
    .sort();
  const described = new Map(others.data?.items.map((other) => [other.name, other.description]));
  return (
    <form ref={form} onSubmit={submit} className="flex flex-col gap-6" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        {role === null ? (
          <TextField
            label={t("fields.name")}
            hint={t("hints.name")}
            required
            spellCheck={false}
            autoComplete="off"
            value={name}
            error={nameProblem}
            onChange={(event) => setName(event.target.value)}
          />
        ) : null}
        <TextField
          label={t("fields.description")}
          maxLength={255}
          value={description}
          error={checked ? refused.at.description : undefined}
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>
      <PermissionRows
        legend={t("fields.permissions")}
        initial={permissions}
        onChange={setPermissions}
        repositories={repositories.data?.items ?? []}
        checked={checked}
      />
      {refused.at.permissions ? <Alert tone="danger">{refused.at.permissions}</Alert> : null}
      <CheckList
        legend={t("fields.contains")}
        options={names.map((other) => ({
          value: other,
          label: other,
          hint: described.get(other) || undefined,
        }))}
        value={contained}
        onChange={setContained}
        empty={t("noOtherRoles")}
      />
      {refused.at.roles ? <Alert tone="danger">{refused.at.roles}</Alert> : null}
      {error && taken === null && refused.elsewhere ? <ErrorState error={error} /> : null}
      <div>
        <Button type="submit" variant="primary" busy={saving}>
          {saveLabel}
        </Button>
      </div>
    </form>
  );
}

/** A new role. */
export function NewRoleScreen() {
  const t = useTranslations("roles");
  const router = useRouter();
  const notify = useNotify();
  const create = useCreateRole();
  const mayCreate = useMayWrite();
  return (
    <div className="mx-auto max-w-4xl">
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: t("title"), href: ROLES },
          { name: t("newTitle"), href: NEW_ROLE },
        ]}
      />
      <PageHeader title={t("newTitle")} />
      {mayCreate ? null : <Alert tone="warning">{t("mayNotCreate")}</Alert>}
      <Panel className="p-6" hidden={!mayCreate}>
        <RoleForm
          role={null}
          saving={create.isPending}
          error={create.error}
          saveLabel={t("create")}
          onSave={(content) =>
            create.mutate(content, {
              onSuccess: (role) => {
                notify(t("created", { name: role.name }));
                router.push(roleHref(role.name));
              },
            })
          }
        />
      </Panel>
    </div>
  );
}

function Edit({ role }: { role: RoleOut }) {
  const t = useTranslations("roles");
  const notify = useNotify();
  const update = useUpdateRole(role.name);
  return (
    <Panel className="p-6">
      <RoleForm
        role={role}
        saving={update.isPending}
        error={update.error}
        saveLabel={t("save")}
        onSave={({ description, permissions, roles }) =>
          update.mutate(
            { description, permissions, roles },
            { onSuccess: () => notify(t("saved", { name: role.name })) },
          )
        }
      />
    </Panel>
  );
}

/** A role as it is, for whoever may not change it, and for the one role nobody may. */
function Shown({ role }: { role: RoleOut }) {
  const t = useTranslations("roles");
  return (
    <Panel className="flex flex-col gap-6 p-6">
      <Facts>
        <Fact name={t("fields.description")}>{role.description}</Fact>
        <Fact name={t("fields.contains")} mono>
          {role.roles.join(", ") || t("containsNone")}
        </Fact>
      </Facts>
      <div>
        <h2 className={H2}>{t("fields.permissions")}</h2>
        <PermissionList patterns={role.permissions} empty={t("noPermissions")} />
      </div>
    </Panel>
  );
}

/** One role: what it grants and contains, and deleting it (A7, A8). */
export function RoleScreen() {
  const t = useTranslations("roles");
  const router = useRouter();
  const notify = useNotify();
  const where = parseRole(usePathname());
  const mayWrite = useMayWrite();
  const remove = useDeleteRole();
  // Once deleted, the role is not asked for again: there is none to answer with.
  const role = useRole(remove.isSuccess ? null : (where?.name ?? null));
  const [asking, setAsking] = useState(false);

  if (where === null) return <NothingHere />;
  if (role.isError) return <ErrorState error={role.error} onRetry={() => void role.refetch()} />;
  // As for a user: the rows are filled once, from an answer that came after the page
  // was opened. Saved from an older one, a permission that was taken away would be back.
  if (!role.data || !role.isFetchedAfterMount) return <LoadingState />;

  const found = role.data;
  // The server lets nobody change the role that makes an administrator.
  const fixed = found.builtin && found.name === ADMIN;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Breadcrumbs
          label={t("path")}
          crumbs={[
            { name: t("title"), href: ROLES },
            { name: found.name, href: roleHref(found.name) },
          ]}
        />
        <PageHeader named title={found.name} />
        {fixed ? (
          <Alert tone="info">{t("adminFixed")}</Alert>
        ) : found.builtin ? (
          <Alert tone="info">{t("builtinNote")}</Alert>
        ) : null}
      </div>
      {mayWrite && !fixed ? <Edit role={found} /> : <Shown role={found} />}
      {mayWrite && !found.builtin ? (
        <Panel className="p-6">
          <h2 className={H2}>{t("deleteTitle")}</h2>
          <p className="mb-4 text-fg-muted">{t("deleteIntro")}</p>
          {remove.isError ? <ErrorState error={remove.error} className="mb-4" /> : null}
          <Button
            variant="danger"
            onClick={() => {
              remove.reset();
              setAsking(true);
            }}
          >
            <Trash2 aria-hidden="true" className="size-4" />
            {t("delete")}
          </Button>
          <ConfirmDialog
            open={asking}
            onOpenChange={setAsking}
            title={t("deleteAsk", { name: found.name })}
            confirmLabel={t("delete")}
            busy={remove.isPending}
            onConfirm={() =>
              remove.mutate(found.name, {
                onSuccess: () => {
                  notify(t("deleted", { name: found.name }));
                  router.replace(ROLES);
                },
                onSettled: () => setAsking(false),
              })
            }
          >
            {t("deleteBody")}
          </ConfirmDialog>
        </Panel>
      ) : null}
    </div>
  );
}
