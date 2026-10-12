import type messages from "../messages/en.json";

// A message that does not exist is then a type error where it is asked for.
declare module "next-intl" {
  interface AppConfig {
    Locale: "en";
    Messages: typeof messages;
  }
}
