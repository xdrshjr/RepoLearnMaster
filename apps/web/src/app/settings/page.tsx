import type { Metadata } from 'next';

import { SettingsView } from '@/components/settings/settings-view';

export const metadata: Metadata = {
  title: '设置',
};

// Settings reflect live server state; never cache the document.
export const dynamic = 'force-dynamic';

export default function SettingsPage() {
  return <SettingsView />;
}
