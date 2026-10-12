import { namedByRepository } from "@/app/titles";
import { BrowseScreen } from "@/screens/browse";

export const generateMetadata = namedByRepository();

export default function Page() {
  return <BrowseScreen />;
}
