import type { Metadata } from "next";

import { NewUserScreen } from "@/screens/user";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.users.newTitle };

export default function Page() {
  return <NewUserScreen />;
}
