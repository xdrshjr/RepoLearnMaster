import type { Metadata } from 'next';

import { PdfPreview } from '@/components/book/pdf-preview';

export const metadata: Metadata = {
  title: 'PDF 预览',
};

/** P10 PDF 预览/下载 — spec §7.2. */
export default async function BookPdfPage({ params }: { params: Promise<{ bookId: string }> }) {
  const { bookId } = await params;
  return <PdfPreview bookId={bookId} />;
}
