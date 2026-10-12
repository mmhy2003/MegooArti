import type { Metadata } from "next";

import { SessionGate } from "@/components/session-gate";
import { SignInScreen } from "@/screens/sign-in";

import messages from "../../../messages/en.json";

export const metadata: Metadata = { title: messages.signIn.title };

export default function SignInPage() {
  return (
    <SessionGate shell={false}>
      <SignInScreen />
    </SessionGate>
  );
}
