import { namedByRepository } from "@/app/titles";
import { UploadScreen } from "@/screens/upload";

import messages from "../../../../../messages/en.json";

export const generateMetadata = namedByRepository(messages.upload.titleTo);

export default function Page() {
  return <UploadScreen />;
}
