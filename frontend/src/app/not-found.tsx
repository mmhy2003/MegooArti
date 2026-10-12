import type { Metadata } from "next";

import { NotFoundScreen } from "@/screens/not-found";

import messages from "../../messages/en.json";

export const metadata: Metadata = { title: messages.notFound.title };

export default function NotFound() {
  return <NotFoundScreen />;
}
