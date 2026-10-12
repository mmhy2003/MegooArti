import type { Metadata } from "next";

import { NewRepositoryScreen } from "@/screens/repository-settings";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.manage.newTitle };

export default function Page() {
  return <NewRepositoryScreen />;
}
