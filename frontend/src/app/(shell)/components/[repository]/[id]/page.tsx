import { namedByRepository } from "@/app/titles";
import { ComponentScreen } from "@/screens/component";

export const generateMetadata = namedByRepository();

export default function Page() {
  return <ComponentScreen />;
}
