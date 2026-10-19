"use client";

/**
 * The settings of each kind of sign-in source, as a form shows them: what it starts
 * with, what it checks before sending, what it sends, and its fields. A secret is
 * written, never read back: left empty, the stored one is kept.
 */
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { TextField } from "@/components/ui/field";
import { CheckboxField, ChoiceGroup } from "@/components/ui/inputs";
import type { SourceOut } from "@/lib/api/types";

export type KindName = "oidc" | "ldap";
export type Values = Record<string, string | boolean>;
type Translate = ReturnType<typeof useTranslations<"source">>;

export type FieldsProps = {
  values: Values;
  change: (changed: Values) => void;
  /** What is wrong with a setting, once the form was tried: the form's own word first. */
  at: (field: string, mine?: string) => string | undefined;
  own: Record<string, string | undefined>;
  hasSecret: boolean;
};

export type KindForm = {
  /** Its secret's name among its settings. */
  secret: string;
  /** The settings the server may refuse, each at its field. */
  fields: string[];
  initial: (source: SourceOut | null) => Values;
  own: (values: Values, t: Translate) => Record<string, string | undefined>;
  sent: (values: Values) => Record<string, unknown>;
  Fields: (props: FieldsProps) => ReactNode;
};

const text = (value: string | boolean | undefined) =>
  typeof value === "string" ? value.trim() : "";

function kept(source: SourceOut | null): Record<string, unknown> {
  return (source?.settings ?? {}) as Record<string, unknown>;
}

function stored(settings: Record<string, unknown>, name: string, otherwise = ""): string {
  return typeof settings[name] === "string" ? (settings[name] as string) : otherwise;
}

/** Left out, the stored secret is kept. */
function withSecret(values: Values, name: string): Record<string, unknown> {
  return values[name] === "" ? {} : { [name]: values[name] };
}

// --- OIDC (spec 5) ----------------------------------------------------------------------

const CLAIMS = ["username_claim", "name_claim", "email_claim", "groups_claim"] as const;
const DEFAULT_CLAIMS: Record<(typeof CLAIMS)[number], string> = {
  username_claim: "preferred_username",
  name_claim: "name",
  email_claim: "email",
  groups_claim: "groups",
};

function OidcFields({ values, change, at, own, hasSecret }: FieldsProps) {
  const t = useTranslations("source");
  const field = (name: string) => ({
    value: values[name] as string,
    onChange: (event: { target: { value: string } }) => change({ [name]: event.target.value }),
  });
  return (
    <>
      <TextField
        label={t("fields.issuer")}
        hint={t("hints.issuer")}
        required
        spellCheck={false}
        autoComplete="off"
        error={at("issuer", own.issuer)}
        {...field("issuer")}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label={t("fields.clientId")}
          required
          spellCheck={false}
          autoComplete="off"
          error={at("client_id", own.client_id)}
          {...field("client_id")}
        />
        <TextField
          label={t("fields.clientSecret")}
          hint={hasSecret ? t("hints.secretKept") : t("hints.secret")}
          type="password"
          autoComplete="new-password"
          error={at("client_secret")}
          {...field("client_secret")}
        />
      </div>
      <TextField
        label={t("fields.scopes")}
        hint={t("hints.scopes")}
        spellCheck={false}
        autoComplete="off"
        error={at("scopes")}
        {...field("scopes")}
      />
      <CheckboxField
        label={t("fields.verifiedEmail")}
        hint={t("hints.verifiedEmail")}
        checked={values.require_verified_email === true}
        onChange={(event) => change({ require_verified_email: event.target.checked })}
      />
      <h3 className="label-caps mt-2 text-fg-muted">{t("claimsTitle")}</h3>
      <p className="text-fg-muted">{t("claimsIntro")}</p>
      <div className="grid gap-4 sm:grid-cols-2">
        {CLAIMS.map((claim) => (
          <TextField
            key={claim}
            label={t(`fields.${claim}`)}
            spellCheck={false}
            autoComplete="off"
            error={at(claim)}
            {...field(claim)}
          />
        ))}
      </div>
    </>
  );
}

const OIDC: KindForm = {
  secret: "client_secret",
  fields: ["issuer", "client_id", "client_secret", "scopes", ...CLAIMS],
  initial: (source) => {
    const settings = kept(source);
    return {
      issuer: stored(settings, "issuer"),
      client_id: stored(settings, "client_id"),
      client_secret: "",
      scopes: Array.isArray(settings.scopes)
        ? (settings.scopes as string[]).join(" ")
        : "openid profile email",
      require_verified_email: settings.require_verified_email === true,
      ...Object.fromEntries(
        CLAIMS.map((claim) => [claim, stored(settings, claim, DEFAULT_CLAIMS[claim])]),
      ),
    };
  },
  own: (values, t) => ({
    issuer: /^https?:\/\/[^/]+/.test(text(values.issuer)) ? undefined : t("issuerRule"),
    client_id: text(values.client_id) === "" ? t("clientIdNeeded") : undefined,
  }),
  sent: (values) => ({
    issuer: text(values.issuer),
    client_id: text(values.client_id),
    scopes: text(values.scopes).split(/\s+/).filter(Boolean),
    require_verified_email: values.require_verified_email === true,
    ...Object.fromEntries(CLAIMS.map((claim) => [claim, text(values[claim])])),
    ...withSecret(values, "client_secret"),
  }),
  Fields: OidcFields,
};

// --- LDAP (spec 7) ----------------------------------------------------------------------

const LDAP_DEFAULTS: Record<string, string> = {
  user_filter: "(uid={username})",
  username_attribute: "uid",
  name_attribute: "cn",
  email_attribute: "mail",
  groups: "member_of",
  member_of_attribute: "memberOf",
  group_filter: "(member={dn})",
  group_name_attribute: "cn",
};

function LdapFields({ values, change, at, own, hasSecret }: FieldsProps) {
  const t = useTranslations("source");
  const field = (name: string) => ({
    value: values[name] as string,
    onChange: (event: { target: { value: string } }) => change({ [name]: event.target.value }),
  });
  return (
    <>
      <TextField
        label={t("ldap.url")}
        hint={t("ldap.hints.url")}
        required
        spellCheck={false}
        autoComplete="off"
        error={at("url", own.url)}
        {...field("url")}
      />
      <CheckboxField
        label={t("ldap.starttls")}
        hint={t("ldap.hints.starttls")}
        checked={values.starttls === true}
        onChange={(event) => change({ starttls: event.target.checked })}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label={t("ldap.bindDn")}
          hint={t("ldap.hints.bindDn")}
          spellCheck={false}
          autoComplete="off"
          error={at("bind_dn")}
          {...field("bind_dn")}
        />
        <TextField
          label={t("ldap.bindPassword")}
          hint={hasSecret ? t("hints.secretKept") : t("hints.secret")}
          type="password"
          autoComplete="new-password"
          error={at("bind_password")}
          {...field("bind_password")}
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label={t("ldap.userBase")}
          required
          spellCheck={false}
          autoComplete="off"
          error={at("user_base", own.user_base)}
          {...field("user_base")}
        />
        <TextField
          label={t("ldap.userFilter")}
          hint={t("ldap.hints.userFilter")}
          spellCheck={false}
          autoComplete="off"
          error={at("user_filter", own.user_filter)}
          {...field("user_filter")}
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <TextField
          label={t("ldap.usernameAttribute")}
          spellCheck={false}
          autoComplete="off"
          error={at("username_attribute")}
          {...field("username_attribute")}
        />
        <TextField
          label={t("ldap.nameAttribute")}
          spellCheck={false}
          autoComplete="off"
          error={at("name_attribute")}
          {...field("name_attribute")}
        />
        <TextField
          label={t("ldap.emailAttribute")}
          spellCheck={false}
          autoComplete="off"
          error={at("email_attribute")}
          {...field("email_attribute")}
        />
      </div>
      <ChoiceGroup
        legend={t("ldap.groups")}
        value={values.groups as string}
        onChange={(groups) => change({ groups })}
        options={[
          { value: "member_of", label: t("ldap.memberOf"), hint: t("ldap.hints.memberOf") },
          { value: "search", label: t("ldap.search"), hint: t("ldap.hints.search") },
          { value: "none", label: t("ldap.noGroups"), hint: t("ldap.hints.noGroups") },
        ]}
      />
      {values.groups === "member_of" ? (
        <TextField
          label={t("ldap.memberOfAttribute")}
          spellCheck={false}
          autoComplete="off"
          error={at("member_of_attribute")}
          {...field("member_of_attribute")}
        />
      ) : null}
      {values.groups === "search" ? (
        <div className="grid gap-4 sm:grid-cols-3">
          <TextField
            label={t("ldap.groupBase")}
            required
            spellCheck={false}
            autoComplete="off"
            error={at("group_base", own.group_base)}
            {...field("group_base")}
          />
          <TextField
            label={t("ldap.groupFilter")}
            hint={t("ldap.hints.groupFilter")}
            spellCheck={false}
            autoComplete="off"
            error={at("group_filter")}
            {...field("group_filter")}
          />
          <TextField
            label={t("ldap.groupNameAttribute")}
            spellCheck={false}
            autoComplete="off"
            error={at("group_name_attribute")}
            {...field("group_name_attribute")}
          />
        </div>
      ) : null}
    </>
  );
}

const LDAP_TEXT = [
  "url",
  "bind_dn",
  "user_base",
  "user_filter",
  "username_attribute",
  "name_attribute",
  "email_attribute",
  "member_of_attribute",
  "group_base",
  "group_filter",
  "group_name_attribute",
];

const LDAP: KindForm = {
  secret: "bind_password",
  fields: [...LDAP_TEXT, "bind_password", "starttls", "groups"],
  initial: (source) => {
    const settings = kept(source);
    return {
      ...Object.fromEntries(
        LDAP_TEXT.map((name) => [name, stored(settings, name, LDAP_DEFAULTS[name] ?? "")]),
      ),
      groups: stored(settings, "groups", "member_of"),
      starttls: settings.starttls === true,
      bind_password: "",
    };
  },
  own: (values, t) => ({
    url: /^ldaps?:\/\/[^/]+$/.test(text(values.url)) ? undefined : t("ldap.urlRule"),
    user_base: text(values.user_base) === "" ? t("ldap.baseNeeded") : undefined,
    user_filter: text(values.user_filter).includes("{username}") ? undefined : t("ldap.filterRule"),
    group_base:
      values.groups === "search" && text(values.group_base) === ""
        ? t("ldap.baseNeeded")
        : undefined,
  }),
  sent: (values) => ({
    url: text(values.url),
    starttls: values.starttls === true,
    bind_dn: text(values.bind_dn) || null,
    user_base: text(values.user_base),
    user_filter: text(values.user_filter),
    username_attribute: text(values.username_attribute),
    name_attribute: text(values.name_attribute),
    email_attribute: text(values.email_attribute),
    groups: values.groups,
    ...(values.groups === "member_of"
      ? { member_of_attribute: text(values.member_of_attribute) }
      : {}),
    ...(values.groups === "search"
      ? {
          group_base: text(values.group_base),
          group_filter: text(values.group_filter),
          group_name_attribute: text(values.group_name_attribute),
        }
      : {}),
    ...withSecret(values, "bind_password"),
  }),
  Fields: LdapFields,
};

export const SOURCE_KINDS: Record<KindName, KindForm> = { oidc: OIDC, ldap: LDAP };

export function isKindName(kind: string): kind is KindName {
  return kind in SOURCE_KINDS;
}
