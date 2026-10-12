import type { Metadata } from "next";

import { HomeScreen } from "@/screens/home";

import messages from "../../../messages/en.json";

export const metadata: Metadata = { title: messages.home.title };

export default function HomePage() {
  return <HomeScreen />;
}
