import { namedByRepository } from "@/app/titles";
import { RepositorySettingsScreen } from "@/screens/repository-settings";

import messages from "../../../../../../messages/en.json";

export const generateMetadata = namedByRepository(messages.manage.titleOf);

export default function Page() {
  return <RepositorySettingsScreen />;
}
