import type { Metadata } from "next";

import { BlobStoresScreen } from "@/screens/blob-stores";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.blobStores.title };

export default function Page() {
  return <BlobStoresScreen />;
}
