/** A password an administrator gives to someone, who then chooses their own. No React here. */

// Letters and digits that are not taken for one another when read aloud or copied by
// hand: no 0 and O, no 1, l and I.
export const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
export const GENERATED_LENGTH = 20;

/**
 * A password of `length` characters, each as likely as any other, from the browser's
 * own source of randomness. A byte that would favour the first letters of the alphabet
 * is thrown away and drawn again.
 */
export function generatePassword(length: number = GENERATED_LENGTH): string {
  const fair = 256 - (256 % ALPHABET.length);
  const drawn: string[] = [];
  while (drawn.length < length) {
    for (const byte of crypto.getRandomValues(new Uint8Array(length))) {
      if (byte < fair && drawn.length < length) drawn.push(ALPHABET[byte % ALPHABET.length] ?? "");
    }
  }
  return drawn.join("");
}
