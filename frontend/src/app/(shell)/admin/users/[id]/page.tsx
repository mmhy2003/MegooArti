import type { Metadata } from "next";

import { UserScreen } from "@/screens/user";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.users.oneTitle };

export default function Page() {
  return <UserScreen />;
}
