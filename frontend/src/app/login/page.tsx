import { SessionGate } from "@/components/session-gate";
import { SignInScreen } from "@/screens/sign-in";

export default function SignInPage() {
  return (
    <SessionGate shell={false}>
      <SignInScreen />
    </SessionGate>
  );
}
