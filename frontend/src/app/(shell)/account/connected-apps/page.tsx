import type { Metadata } from "next";

import { ConnectedAppsScreen } from "@/screens/connected-apps";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.connectedApps.title };

export default function Page() {
  return <ConnectedAppsScreen />;
}
