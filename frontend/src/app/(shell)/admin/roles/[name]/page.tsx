import type { Metadata } from "next";

import { RoleScreen } from "@/screens/roles";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.roles.oneTitle };

export default function Page() {
  return <RoleScreen />;
}
