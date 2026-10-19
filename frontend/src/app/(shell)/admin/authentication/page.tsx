import type { Metadata } from "next";

import { AuthenticationScreen } from "@/screens/authentication";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.authentication.title };

export default function Page() {
  return <AuthenticationScreen />;
}
