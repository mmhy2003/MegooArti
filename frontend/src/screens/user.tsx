"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { NewPasswordField } from "@/components/new-password-field";
import { TokenList } from "@/components/token-list";
import { Alert } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { CopyButton } from "@/components/ui/copy-button";
import { Fact, Facts, Time } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { CheckboxField, CheckList, ChoiceGroup } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { isApiError } from "@/lib/api/client";
import type { UserOut } from "@/lib/api/types";
import { NEW_USER, parseUser, userHref, USERS } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import {
  useCreateUser,
  useDeleteUser,
  useEveryRole,
  useResetPassword,
  useRevokeUserToken,
  useUpdateUser,
  useUser,
  useUserTokens,
} from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

// The server's rules, said before the request is made. The server still decides.
const USERNAME = /^[A-Za-z0-9._@-]{1,64}$/;
const EMAIL = /^[^@\s]+@[^@\s]+$/;
const MIN_PASSWORD = 8;
const ANONYMOUS = "anonymous";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";

/** The keyboard goes to the first field that is wrong, whenever what is wrong changes. */
function useFocusOnWrong(changed: unknown) {
  const form = useRef<HTMLFormElement>(null);
  useEffect(() => {
    form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [changed]);
  return form;
}

/** The roles a user can be given, as ticks. Without the right to read roles: those they hold. */
function useRoleOptions(held: string[]) {
  const session = useSession();
  const mayRead = session.data !== undefined && allows(session.data, "admin:roles:read");
  const roles = useEveryRole(mayRead);
  const names = roles.data?.items.map((role) => role.name) ?? [];
  // A role that is held is one of the choices, though it be beyond what was fetched.
  const all = Array.from(new Set([...names, ...held])).sort();
  const described = new Map(roles.data?.items.map((role) => [role.name, role.description]));
  return {
    known: mayRead ? roles.data !== undefined : true,
    canChoose: mayRead,
    options: all.map((name) => ({
      value: name,
      label: name,
      hint: described.get(name) || undefined,
    })),
  };
}

// ============================== a new user ================================================

/** A user that was just made, with the password to pass on, which is not shown again. */
function Created({
  user,
  password,
  onAnother,
}: {
  user: UserOut;
  password: string;
  onAnother: () => void;
}) {
  const t = useTranslations("users");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  return (
    <Panel role="region" aria-labelledby="created-user" className="border-ok p-6">
      <h2
        id="created-user"
        ref={heading}
        tabIndex={-1}
        className="mb-2 text-lg font-semibold text-fg outline-none"
      >
        {t("createdTitle", { username: user.username })}
      </h2>
      <p className="mb-3 text-fg-muted">
        {user.must_change_password ? t("createdMustChange") : t("createdKeeps")}
      </p>
      <div className="flex items-start gap-2 rounded-sm border border-line bg-field p-3">
        <code className="min-w-0 flex-1 font-mono text-sm break-all text-fg">{password}</code>
        <CopyButton text={password} what={t("thePassword")} className="-my-1" />
      </div>
      <p className="mt-3 text-sm text-fg-muted">{t("createdOnce")}</p>
      <div className="mt-4 flex flex-wrap gap-3">
        <Button asChild variant="primary">
          <AppLink href={userHref(user.id)}>{t("open", { username: user.username })}</AppLink>
        </Button>
        <Button onClick={onAnother}>{t("another")}</Button>
      </div>
    </Panel>
  );
}

function NewUserForm({
  onCreated,
  again,
}: {
  onCreated: (user: UserOut, password: string) => void;
  /** It follows a user that was just made: the keyboard starts at its first field. */
  again: boolean;
}) {
  const t = useTranslations("users");
  const create = useCreateUser();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mustChange, setMustChange] = useState(true);
  const [roles, setRoles] = useState<string[]>([]);
  const [checked, setChecked] = useState(false);
  const choices = useRoleOptions(roles);

  const refused = refusalsOf(create.error, [
    "username",
    "display_name",
    "email",
    "password",
    "roles",
  ]);
  // A name another user has: said at the name.
  const taken =
    isApiError(create.error) && create.error.code === "conflict" ? create.error.message : null;
  const own = {
    username: USERNAME.test(username) ? undefined : t("usernameRule"),
    displayName: displayName.trim() === "" ? t("displayNameNeeded") : undefined,
    email: email.trim() === "" || EMAIL.test(email.trim()) ? undefined : t("emailRule"),
    password: password.length < MIN_PASSWORD ? t("passwordRule", { min: MIN_PASSWORD }) : undefined,
  };
  const problems = checked
    ? {
        username: own.username ?? taken ?? refused.at.username,
        displayName: own.displayName ?? refused.at.display_name,
        email: own.email ?? refused.at.email,
        password: own.password ?? refused.at.password,
      }
    : {};
  const form = useFocusOnWrong(`${checked}${String(create.error)}`);
  useEffect(() => {
    // The panel that said a user was made had the keyboard, and is gone.
    if (again) form.current?.querySelector("input")?.focus();
  }, [again, form]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setChecked(true);
    create.reset();
    if (Object.values(own).some(Boolean)) return;
    create.mutate(
      {
        username,
        display_name: displayName.trim(),
        email: email.trim() || null,
        password,
        must_change_password: mustChange,
        roles,
      },
      { onSuccess: (user) => onCreated(user, password) },
    );
  }

  return (
    <Panel className="p-6">
      <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("fields.username")}
            hint={t("hints.username")}
            required
            spellCheck={false}
            autoComplete="off"
            value={username}
            error={problems.username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <TextField
            label={t("fields.displayName")}
            required
            autoComplete="off"
            value={displayName}
            error={problems.displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </div>
        <TextField
          label={t("fields.email")}
          hint={t("hints.email")}
          type="email"
          autoComplete="off"
          value={email}
          error={problems.email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <NewPasswordField
          label={t("fields.password")}
          hint={t("hints.password", { min: MIN_PASSWORD })}
          value={password}
          error={problems.password}
          onChange={setPassword}
        />
        <CheckboxField
          label={t("fields.mustChange")}
          hint={t("hints.mustChange")}
          checked={mustChange}
          onChange={(event) => setMustChange(event.target.checked)}
        />
        {choices.canChoose ? (
          <CheckList
            legend={t("fields.roles")}
            options={choices.options}
            value={roles}
            onChange={setRoles}
            empty={t("noRoles")}
          />
        ) : (
          <p className="text-sm text-fg-subtle">{t("rolesNotReadable")}</p>
        )}
        {refused.at.roles ? <Alert tone="danger">{refused.at.roles}</Alert> : null}
        {create.isError && taken === null && refused.elsewhere ? (
          <ErrorState error={create.error} />
        ) : null}
        <div>
          <Button type="submit" variant="primary" busy={create.isPending}>
            {t("create")}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

/** A new user (A6): who they are, the password they start with, and their roles. */
export function NewUserScreen() {
  const t = useTranslations("users");
  const [created, setCreated] = useState<{ user: UserOut; password: string } | null>(null);
  const [again, setAgain] = useState(false);
  return (
    <div className="mx-auto max-w-3xl">
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: t("title"), href: USERS },
          { name: t("newTitle"), href: NEW_USER },
        ]}
      />
      <PageHeader title={t("newTitle")} />
      {created ? (
        <Created
          user={created.user}
          password={created.password}
          onAnother={() => {
            setAgain(true);
            setCreated(null);
          }}
        />
      ) : (
        <NewUserForm again={again} onCreated={(user, password) => setCreated({ user, password })} />
      )}
    </div>
  );
}

// ============================== one user ===================================================

function Details({
  user,
  mayWrite,
  isSelf,
}: {
  user: UserOut;
  mayWrite: boolean;
  isSelf: boolean;
}) {
  const t = useTranslations("users");
  const notify = useNotify();
  const update = useUpdateUser(user.id);
  const [displayName, setDisplayName] = useState(user.display_name);
  const [email, setEmail] = useState(user.email ?? "");
  const [roles, setRoles] = useState(user.roles);
  const [status, setStatus] = useState(user.status);
  const [checked, setChecked] = useState(false);
  const choices = useRoleOptions(user.roles);

  const refused = refusalsOf(update.error, ["display_name", "email", "roles", "status"]);
  const own = {
    displayName: displayName.trim() === "" ? t("displayNameNeeded") : undefined,
    email: email.trim() === "" || EMAIL.test(email.trim()) ? undefined : t("emailRule"),
  };
  const problems = checked
    ? {
        displayName: own.displayName ?? refused.at.display_name,
        email: own.email ?? refused.at.email,
      }
    : {};
  const form = useFocusOnWrong(`${checked}${String(update.error)}`);

  function submit(event: FormEvent) {
    event.preventDefault();
    setChecked(true);
    update.reset();
    if (Object.values(own).some(Boolean)) return;
    update.mutate(
      {
        display_name: displayName.trim(),
        email: email.trim() || null,
        // What could not be chosen is not sent, and so is not changed.
        ...(choices.canChoose ? { roles } : {}),
        ...(isSelf ? {} : { status: status as "active" | "disabled" }),
      },
      { onSuccess: () => notify(t("saved", { username: user.username })) },
    );
  }

  return (
    <Panel className="p-6">
      <h2 className={H2}>{t("details")}</h2>
      <Facts className="mb-5">
        <Fact name={t("fields.username")} copy={user.username} mono>
          {user.username}
        </Fact>
        <Fact name={t("facts.created")}>
          <Time value={user.created_at} />
        </Fact>
        <Fact name={t("facts.lastSignIn")}>
          <Time value={user.last_login_at} />
        </Fact>
      </Facts>
      <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <fieldset disabled={!mayWrite} className="flex min-w-0 flex-col gap-5 border-0 p-0">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label={t("fields.displayName")}
              required
              autoComplete="off"
              value={displayName}
              error={problems.displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
            <TextField
              label={t("fields.email")}
              type="email"
              autoComplete="off"
              value={email}
              error={problems.email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          {choices.canChoose ? (
            <CheckList
              legend={t("fields.roles")}
              options={choices.options}
              value={roles}
              onChange={setRoles}
              empty={t("noRoles")}
            />
          ) : (
            <Facts>
              <Fact name={t("fields.roles")} mono>
                {user.roles.join(", ") || t("noRolesHeld")}
              </Fact>
            </Facts>
          )}
          {refused.at.roles ? <Alert tone="danger">{refused.at.roles}</Alert> : null}
          {isSelf ? (
            <p className="text-sm text-fg-subtle">{t("selfState")}</p>
          ) : (
            <ChoiceGroup
              legend={t("fields.state")}
              value={status}
              onChange={setStatus}
              options={[
                { value: "active", label: t("active"), hint: t("hints.active") },
                { value: "disabled", label: t("disabled"), hint: t("hints.disabled") },
              ]}
            />
          )}
        </fieldset>
        {update.isError && refused.elsewhere ? <ErrorState error={update.error} /> : null}
        {mayWrite ? (
          <div>
            <Button type="submit" variant="primary" busy={update.isPending}>
              {t("save")}
            </Button>
          </div>
        ) : null}
      </form>
    </Panel>
  );
}

function Password({ user }: { user: UserOut }) {
  const t = useTranslations("users");
  const reset = useResetPassword(user.id);
  const [password, setPassword] = useState("");
  const [mustChange, setMustChange] = useState(true);
  const [checked, setChecked] = useState(false);
  const refused = refusalsOf(reset.error, ["password"]);
  const short = password.length < MIN_PASSWORD ? t("passwordRule", { min: MIN_PASSWORD }) : null;
  const problem = checked ? (short ?? refused.at.password) : undefined;
  const form = useFocusOnWrong(`${checked}${String(reset.error)}`);

  function submit(event: FormEvent) {
    event.preventDefault();
    setChecked(true);
    reset.reset();
    if (short) return;
    reset.mutate({ password, must_change_password: mustChange });
  }

  return (
    <Panel className="p-6">
      <h2 className={H2}>{t("passwordTitle")}</h2>
      <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <NewPasswordField
          label={t("fields.newPassword")}
          hint={t("hints.newPassword", { min: MIN_PASSWORD })}
          value={password}
          error={problem}
          onChange={(value) => {
            setPassword(value);
            reset.reset(); // what was set is not what is in the field any more
          }}
        />
        <CheckboxField
          label={t("fields.mustChange")}
          hint={t("hints.mustChange")}
          checked={mustChange}
          onChange={(event) => setMustChange(event.target.checked)}
        />
        {reset.isError && refused.elsewhere ? <ErrorState error={reset.error} /> : null}
        {reset.isSuccess ? (
          <Alert tone="success" title={t("passwordSet", { username: user.username })}>
            {t("passwordSetOnce")}
          </Alert>
        ) : null}
        <div>
          <Button type="submit" busy={reset.isPending}>
            {t("setPassword")}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

function Tokens({ user, mayRevoke }: { user: UserOut; mayRevoke: boolean }) {
  const t = useTranslations("users");
  const notify = useNotify();
  const tokens = useUserTokens(user.id, true);
  const revoke = useRevokeUserToken(user.id);
  return (
    <Panel>
      <h2 className="px-6 pt-6 text-lg font-semibold text-fg uppercase">{t("tokensTitle")}</h2>
      {tokens.isError ? (
        <ErrorState error={tokens.error} onRetry={() => void tokens.refetch()} className="m-6" />
      ) : !tokens.data ? (
        <LoadingState />
      ) : (
        <TokenList
          caption={t("tokensOf", { username: user.username })}
          tokens={tokens.data.items}
          empty={t("noTokens")}
          onRevoke={
            mayRevoke
              ? async (token) => {
                  await revoke.mutateAsync(token.id);
                  notify(t("tokenRevoked", { name: token.name, username: user.username }));
                }
              : undefined
          }
        />
      )}
    </Panel>
  );
}

function Delete({
  user,
  remove,
}: {
  user: UserOut;
  /** The screen's own: once it has succeeded, the screen stops asking for the user. */
  remove: ReturnType<typeof useDeleteUser>;
}) {
  const t = useTranslations("users");
  const router = useRouter();
  const notify = useNotify();
  const [asking, setAsking] = useState(false);
  return (
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
        title={t("deleteAsk", { username: user.username })}
        confirmLabel={t("delete")}
        mustType={user.username}
        busy={remove.isPending}
        onConfirm={() =>
          remove.mutate(user.id, {
            onSuccess: () => {
              notify(t("deleted", { username: user.username }));
              router.replace(USERS);
            },
            onSettled: () => setAsking(false),
          })
        }
      >
        {t("deleteBody")}
      </ConfirmDialog>
    </Panel>
  );
}

/** One user: who they are and what they hold, a new password, their tokens, and deleting them (A7, A8). */
export function UserScreen() {
  const t = useTranslations("users");
  const session = useSession();
  const where = parseUser(usePathname());
  const remove = useDeleteUser();
  // Once deleted, the user is not asked for again: the answer would be that there is
  // none, shown for the moment before the screen returns to the list.
  const user = useUser(remove.isSuccess ? null : (where?.id ?? null));

  if (where === null) return <NothingHere />;
  if (user.isError) return <ErrorState error={user.error} onRetry={() => void user.refetch()} />;
  if (!user.data || !session.data) return <LoadingState />;

  const found = user.data;
  const may = (permission: string) => allows(session.data, permission);
  const mayWrite = may("admin:users:write");
  const isSelf = session.data.user?.id === found.id;
  const isAnonymous = found.builtin && found.username === ANONYMOUS;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Breadcrumbs
          label={t("path")}
          crumbs={[
            { name: t("title"), href: USERS },
            { name: found.username, href: userHref(found.id) },
          ]}
        />
        <PageHeader named title={found.username} intro={found.display_name} />
        {found.builtin ? <Alert tone="info">{t("builtinNote")}</Alert> : null}
      </div>
      <Details user={found} mayWrite={mayWrite} isSelf={isSelf} />
      {mayWrite && !isAnonymous ? <Password user={found} /> : null}
      {may("admin:tokens:read") ? (
        <Tokens user={found} mayRevoke={may("admin:tokens:write")} />
      ) : null}
      {mayWrite ? (
        isSelf || found.builtin ? (
          <Panel className="p-6">
            <h2 className={H2}>{t("deleteTitle")}</h2>
            <p className="text-fg-muted">{isSelf ? t("selfDelete") : t("builtinDelete")}</p>
          </Panel>
        ) : (
          <Delete user={found} remove={remove} />
        )
      ) : null}
    </div>
  );
}
