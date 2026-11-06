import type { Metadata } from 'next';

import { FeatureGrid } from '@/components/home/feature-grid';
import { HeroImport } from '@/components/home/hero-import';
import { CourseSearch } from '@/components/home/course-search';
import { HotCourses, RecentLearning } from '@/components/home/course-sections';
import { SiteHeader } from '@/components/shell/site-header';

export const metadata: Metadata = {
  title: 'RepoLearn · 把任何 GitHub 仓库变成一节可走读的课',
};

/**
 * P01 首页 — spec §7.2.
 *
 * RSC shell + client islands: the page itself renders on the server (zero JS for
 * the static thirds), while `HeroImport` / `CourseSearch` / `HotCourses` /
 * `RecentLearning` are client components that talk to same-origin `/api/*`.
 *
 * `CourseSearch` 挂在 HeroImport 与 HotCourses 之间（§4.3 #50）：搜的是"已生成
 * 的课程"，所以它必须在这份列表的**上方**，否则用户会先读到一份与关键词无关的
 * 热门列表再看到自己的结果。
 */
export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="pb-10">
        <HeroImport />
        <CourseSearch />
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
