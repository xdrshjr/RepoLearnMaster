import type { Metadata } from 'next';

import { FeatureGrid } from '@/components/home/feature-grid';
import { HeroImport } from '@/components/home/hero-import';
import { HotCourses, RecentLearning } from '@/components/home/course-sections';
import { SiteHeader } from '@/components/shell/site-header';

export const metadata: Metadata = {
  title: 'RepoLearn · 把任何 GitHub 仓库变成一节可走读的课',
};

/**
 * P01 首页 — spec §7.2.
 *
 * RSC shell + client islands: the page itself renders on the server (zero JS for
 * the static thirds), while `HeroImport` / `HotCourses` / `RecentLearning` are
 * client components that talk to same-origin `/api/*`.
 */
export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="pb-10">
        <HeroImport />
        <FeatureGrid />
        <HotCourses />
        <RecentLearning />
      </main>
      <footer className="border-t border-border px-4 py-6 text-center text-[11px] text-text-dim">
        RepoLearn · 讲解优先给出可追溯的源码事实，无法确定的行为会明确标注为“教学模拟”
      </footer>
    </>
  );
}
