import type { Metadata } from "next";

import { UsersScreen } from "@/screens/users";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.users.title };

export default function Page() {
  return <UsersScreen />;
}
