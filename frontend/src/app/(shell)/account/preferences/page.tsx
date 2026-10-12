import type { Metadata } from "next";

import { PreferencesScreen } from "@/screens/preferences";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.preferences.title };

export default function Page() {
  return <PreferencesScreen />;
}
