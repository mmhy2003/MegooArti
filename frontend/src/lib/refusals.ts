/**
 * What the API refused of a form, by the field it refused it at. No React here.
 *
 * A refusal of what was sent has the code `validation_error` and says, for each thing
 * that is wrong, where: `body.name` for the name in the body, `body.permissions.2` for
 * the third permission, or a plain `password` where the check is the server's own.
 */
import { isApiError } from "@/lib/api/client";

export type Refusals = {
  /** What is wrong, by the form's own name for the field. */
  at: Record<string, string>;
  /**
   * Whether something was refused that no field of the form can show: a failure of
   * another kind, or a detail about something the form does not have. It is then said
   * whole, where the form's button is.
   */
  elsewhere: boolean;
};

export const NOTHING_REFUSED: Refusals = { at: {}, elsewhere: false };

/** `fields` are the names the form has places for. A place takes what is under it too. */
export function refusalsOf(error: unknown, fields: readonly string[]): Refusals {
  if (error === null || error === undefined) return NOTHING_REFUSED;
  if (!isApiError(error) || error.code !== "validation_error" || error.details.length === 0) {
    return { at: {}, elsewhere: true };
  }
  const refused: Refusals = { at: {}, elsewhere: false };
  for (const detail of error.details) {
    const where = (detail.field ?? "").replace(/^body\./, "");
    const field = fields.find((name) => where === name || where.startsWith(`${name}.`));
    if (field === undefined) refused.elsewhere = true;
    // The first thing wrong with a field is the one that is said.
    else refused.at[field] ??= detail.message;
  }
  return refused;
}
