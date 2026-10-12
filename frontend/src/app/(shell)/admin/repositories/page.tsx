import type { Metadata } from "next";

import { ManageRepositoriesScreen } from "@/screens/manage-repositories";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.manage.title };

export default function Page() {
  return <ManageRepositoriesScreen />;
}
