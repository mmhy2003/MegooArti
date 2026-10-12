import type { Metadata } from "next";

import { AnonymousAccessScreen } from "@/screens/anonymous-access";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.anonymous.title };

export default function Page() {
  return <AnonymousAccessScreen />;
}
