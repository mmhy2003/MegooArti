import type { Metadata } from "next";

import { ChangePasswordScreen } from "@/screens/change-password";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.password.title };

export default function ChangePasswordPage() {
  return <ChangePasswordScreen />;
}
