import type { Metadata } from "next";

import { CertificatesScreen } from "@/screens/certificates";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.certificates.title };

export default function Page() {
  return <CertificatesScreen />;
}
