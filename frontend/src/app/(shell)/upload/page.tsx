import type { Metadata } from "next";

import { UploadChooserScreen } from "@/screens/upload";

import messages from "../../../../messages/en.json";

export const metadata: Metadata = { title: messages.upload.title };

export default function Page() {
  return <UploadChooserScreen />;
}
