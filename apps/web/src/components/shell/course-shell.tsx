'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { AlertTriangle, Menu, PanelRight, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { Badge, Card, Skeleton } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Overlay } from '@/components/ui/overlay';
import { Logo } from '@/components/shell/site-header';
import { MentorRail } from '@/components/shell/mentor-rail';
import { OutlineRail } from '@/components/shell/outline-rail';
import { LAYERS, TopProgress, type CourseLayer } from '@/components/shell/top-progress';
import { CourseContext, defaultLessonForLayer, type AnchorTarget } from '@/components/shell/course-context';
import { PlayerProvider } from '@/components/player/player-provider';
import { SubtitleView } from '@/components/player/subtitle-view';
import { TransportBar } from '@/components/player/transport-bar';
import { useCourse, useCourseLessons, usePlayback, useRecap } from '@/lib/api/hooks';
import { useIdeStore } from '@/stores/ide';
import { usePlayerStore } from '@/stores/player';

function detectLayer(pathname: string): CourseLayer {
  if (pathname.endsWith('/walkthrough')) return 'walkthrough';
  if (pathname.endsWith('/deep-dive')) return 'deep-dive';
  if (pathname.endsWith('/recap')) return 'recap';
  return 'overview';
}

/**
 * Course workbench shell — spec §7.2.
 *
 * The player lives *here*, not in a page: switching tabs (overview → walkthrough
 * → deep-dive) must not unmount `<audio>` or reset the timeline (§7.3 rule 1).
 */
export function CourseShell({ courseId, children }: { courseId: string; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const layer = detectLayer(pathname);

  const [outlineOpen, setOutlineOpen] = useState(false);
  const [mentorOpen, setMentorOpen] = useState(false);
  const [localCompleted, setLocalCompleted] = useState<Set<string>>(new Set());

  const course = useCourse(courseId);
  const lessonsQuery = useCourseLessons(courseId);
  const recap = useRecap(courseId);

  const sections = lessonsQuery.data?.sections ?? [];
  const paramLesson = searchParams.get('lesson');
  const defaultLesson = useMemo(
    () => defaultLessonForLayer(sections, layer),
    [sections, layer],
  );
  const lessonKey = layer === 'recap' ? null : (paramLesson ?? defaultLesson);

  const playback = usePlayback(courseId, lessonKey);
  const loadBundle = usePlayerStore((state) => state.loadBundle);
  const storedLessonKey = usePlayerStore((state) => state.lessonKey);
  const playerStatus = usePlayerStore((state) => state.status);
  const setIdeCourse = useIdeStore((state) => state.setCourse);
  const openFile = useIdeStore((state) => state.openFile);
  const setFocus = useIdeStore((state) => state.setFocus);

  // Load the bundle exactly once per (course, lesson) — a refetch must not
  // rewind the learner's position.
  useEffect(() => {
    const bundle = playback.data;
    if (!bundle) return;
    if (storedLessonKey === bundle.lesson.key && usePlayerStore.getState().courseId === courseId) {
      setIdeCourse(courseId, bundle.files ?? []);
      return;
    }
    loadBundle(bundle);
    setIdeCourse(courseId, bundle.files ?? []);
  }, [playback.data, storedLessonKey, courseId, loadBundle, setIdeCourse]);

  // Mark a lesson complete once its last step ends.
  useEffect(() => {
    if (playerStatus !== 'ended' || !lessonKey) return;
    setLocalCompleted((current) => {
      if (current.has(lessonKey)) return current;
      const next = new Set(current);
      next.add(lessonKey);
      return next;
    });
  }, [playerStatus, lessonKey]);

  // Deep link from another layer: `?file=…&line=…` opens the code pane there.
  useEffect(() => {
    const file = searchParams.get('file');
    const line = Number.parseInt(searchParams.get('line') ?? '', 10);
    if (!file || !Number.isFinite(line)) return;
    openFile(file, { file, lineStart: line, lineEnd: line });
  }, [searchParams, openFile]);

  const completedLessons = useMemo(() => {
    const allLessons = sections.flatMap((section) => section.lessons.map((lesson) => lesson.key));
    const percent = recap.data?.percent ?? 0;
    const doneCount = Math.floor((percent / 100) * allLessons.length);
    return new Set([...allLessons.slice(0, Math.max(0, doneCount)), ...localCompleted]);
  }, [sections, recap.data?.percent, localCompleted]);

  const openAnchor = useCallback(
    (target: AnchorTarget) => {
      setFocus({ file: target.file, lineStart: target.lineStart, lineEnd: target.lineEnd });
      if (layer === 'deep-dive') {
        openFile(target.file, { file: target.file, lineStart: target.lineStart, lineEnd: target.lineEnd });
        return;
      }
      // Cross-layer jump: carry the anchor in the URL so the deep-dive page can
      // open it after hydration (T-IDE-1), and keep the previous focus in the
      // ide store history for “返回原位置”.
      setOutlineOpen(false);
      router.push(
        `/course/${encodeURIComponent(courseId)}/deep-dive?file=${encodeURIComponent(target.file)}&line=${target.lineStart}`,
      );
    },
    [courseId, layer, openFile, router, setFocus],
  );

  const askAboutRange = useCallback(
    (target: AnchorTarget) => {
      openAnchor(target);
      setMentorOpen(true);
    },
    [openAnchor],
  );

  const layerMeta = LAYERS.find((item) => item.key === layer) ?? LAYERS[0]!;
  const title = course.data?.title || course.data?.repo.full_name || '课程';
  const commitSha = course.data?.commit?.sha ?? '';

  const contextValue = useMemo(
    () => ({
      courseId,
      layer,
      course: course.data,
      sections,
      lessonKey,
      playback: playback.data,
      playbackLoading: playback.isLoading,
      openAnchor,
      askAboutRange,
      completedLessons,
    }),
    [
      courseId,
      layer,
      course.data,
      sections,
      lessonKey,
      playback.data,
      playback.isLoading,
      openAnchor,
      askAboutRange,
      completedLessons,
    ],
  );

  return (
    <CourseContext.Provider value={contextValue}>
      <PlayerProvider courseId={courseId}>
        <div className="flex h-dvh flex-col overflow-hidden bg-bg">
          <header className="flex shrink-0 items-center gap-3 border-b border-border bg-bg px-3 py-2">
            <Link href="/" aria-label="回首页" className="shrink-0">
              <Logo />
            </Link>
            <Button
              variant="ghost"
              size="sm"
              className="lg:hidden"
              aria-label="打开大纲"
              onClick={() => setOutlineOpen(true)}
            >
              <Menu className="size-4" aria-hidden />
            </Button>

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h1 className="truncate text-xs font-semibold text-text">{title}</h1>
                <Badge tone="muted" className="hidden shrink-0 sm:inline-flex">
                  {layerMeta.label}
                </Badge>
                {course.data?.status && course.data.status !== 'ready' ? (
                  <Badge tone={course.data.status === 'partial' ? 'warn' : 'danger'}>
                    {course.data.status}
                  </Badge>
                ) : null}
              </div>
              <p className="truncate text-[10px] text-text-dim">
                {course.data?.repo.full_name}
                {commitSha ? ` @ ${commitSha.slice(0, 8)}` : ''}
                {course.data?.minutes ? ` · 约 ${course.data.minutes} 分钟` : ''}
              </p>
            </div>

            <div className="hidden md:block">
              <TopProgress
                courseId={courseId}
                active={layer}
                completed={{
                  overview: completedLessons.size > 0,
                  walkthrough: completedLessons.size > 1,
                  'deep-dive': completedLessons.size > 3,
                  recap: recap.data?.completed ?? false,
                }}
                percent={recap.data?.percent ?? 0}
              />
            </div>

            <Button
              variant="ghost"
              size="sm"
              className="xl:hidden"
              aria-label="打开 Momo"
              onClick={() => setMentorOpen(true)}
            >
              <PanelRight className="size-4" aria-hidden />
            </Button>
          </header>

          {course.isError ? (
            <div className="border-b border-danger/40 bg-danger/10 px-3 py-2 text-[11px] text-danger">
              课程数据加载失败：{course.error instanceof Error ? course.error.message : '未知错误'}
              <button type="button" onClick={() => void course.refetch()} className="ml-2 underline">
                重试
              </button>
            </div>
          ) : null}

          <div className="flex min-h-0 flex-1">
            <aside className="hidden w-[248px] shrink-0 border-r border-border bg-bg-elevated lg:block">
              {lessonsQuery.isLoading ? (
                <div className="space-y-2 p-3">
                  {Array.from({ length: 6 }).map((_, index) => (
                    <Skeleton key={index} className="h-4" />
                  ))}
                </div>
              ) : (
                <OutlineRail
                  courseId={courseId}
                  sections={sections}
                  layer={layer}
                  lessonKey={lessonKey}
                  completedLessons={completedLessons}
                  onSelect={() => setOutlineOpen(false)}
                />
              )}
            </aside>

            <main id="main" className="min-h-0 min-w-0 flex-1 overflow-y-auto">
              {/*
                加载态必须**独占**这块区域。之前是"骨架屏 + 页面同时渲染"，
                而页面拿到 `playback === undefined` 会渲染"这一课还没准备好"
                ——首屏的正确观感就成了"正在生成"，而用户其实只等了 300ms。
              */}
              {playback.isLoading && layer !== 'recap' ? (
                <div className="space-y-3 p-4" role="status" aria-live="polite">
                  <Skeleton className="h-8 w-1/2" />
                  <Skeleton className="h-64" />
                  <Skeleton className="h-24" />
                  <p className="text-[11px] text-text-dim">正在读取课时数据…</p>
                </div>
              ) : null}

              {playback.isError && layer !== 'recap' ? (
                <div className="p-4">
                  <Card className="border-warn/40 bg-warn/5">
                    <p className="flex items-center gap-1.5 text-xs text-warn">
                      <AlertTriangle className="size-3.5" aria-hidden />
                      这一课时的播放数据还没准备好
                    </p>
                    <p className="mt-1 text-[11px] text-text-muted">
                      课程可能仍在生成中（COURSE_NOT_READY）。已发布的课时可以直接切换大纲里的其它课时。
                    </p>
                    <div className="mt-2 flex gap-2">
                      <Button variant="outline" size="sm" onClick={() => void playback.refetch()} icon={<RotateCcw className="size-3" aria-hidden />}>
                        重试
                      </Button>
                      <Link
                        href={`/repo/${encodeURIComponent(course.data?.repo.full_name.split('/')[0] ?? '')}/${encodeURIComponent(course.data?.repo.full_name.split('/')[1] ?? '')}`}
                        className="inline-flex h-8 items-center text-[11px] text-accent underline underline-offset-2"
                      >
                        回到准备页
                      </Link>
                    </div>
                  </Card>
                </div>
              ) : playback.isLoading && layer !== 'recap' ? null : (
                children
              )}
            </main>

            <aside className="hidden w-[280px] shrink-0 xl:block">
              <MentorRail
                playback={playback.data}
                lessonTitle={playback.data?.lesson.title ?? title}
                onAsk={() => setMentorOpen(true)}
              />
            </aside>
          </div>

          <SubtitleView />
          <TransportBar />
        </div>

        <Overlay open={outlineOpen} onClose={() => setOutlineOpen(false)} title="课程大纲" variant="sheet">
          <OutlineRail
            courseId={courseId}
            sections={sections}
            layer={layer}
            lessonKey={lessonKey}
            completedLessons={completedLessons}
            onSelect={() => setOutlineOpen(false)}
          />
        </Overlay>

        <Overlay open={mentorOpen} onClose={() => setMentorOpen(false)} title="Momo · 领读" variant="bottom">
          <div className="h-[60vh]">
            <MentorRail
              playback={playback.data}
              lessonTitle={playback.data?.lesson.title ?? title}
              onAsk={() => setMentorOpen(false)}
              className="border-l-0"
            />
          </div>
        </Overlay>
      </PlayerProvider>
    </CourseContext.Provider>
  );
}
