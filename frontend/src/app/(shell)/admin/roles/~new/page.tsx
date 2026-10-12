import type { Metadata } from "next";

import { NewRoleScreen } from "@/screens/roles";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.roles.newTitle };

export default function Page() {
  return <NewRoleScreen />;
}
