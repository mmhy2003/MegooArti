import type { Metadata } from "next";

import { ConnectScreen } from "@/screens/connect";

import messages from "../../../../messages/en.json";

export const metadata: Metadata = { title: messages.connect.title };

export default function Page() {
  return <ConnectScreen />;
}
