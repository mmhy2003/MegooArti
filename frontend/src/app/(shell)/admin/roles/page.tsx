import type { Metadata } from "next";

import { RolesScreen } from "@/screens/roles";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.roles.title };

export default function Page() {
  return <RolesScreen />;
}
