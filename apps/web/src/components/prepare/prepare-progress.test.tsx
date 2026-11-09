import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { PrepareProgress } from '@/components/prepare/prepare-progress';
import { initialPrepareState, type PrepareState } from '@/lib/jobs/prepare-state';

/**
 * 真实故障（浏览器实测，2026-11-09）：`GET /repo/sherlock-project/sherlock` 上课程
 * 早已 ready，页头写着"课程可学习"，但「生成进度」卡片永远停在
 *
 *     0 / 4 段完成 · 正在启动生成流程        ● 连接中
 *
 * 因为"没有正在进行的任务"这件事**没有任何渲染分支**：`state.completed` 只在收到
 * `job.completed` 事件时为真，而命中缓存/直接打开页面时根本不会有事件流。
 * 用户看到的是"卡住了"，实际上什么都没在跑——这比"慢"严重得多。
 *
 * 渲染成静态 HTML 来断言，理由与 markdown.test.tsx 相同：不依赖 act() 与测试渲染器
 * 的版本细节，断言的就是浏览器拿到的文本。
 */

function render(state: PrepareState, props: Partial<Parameters<typeof PrepareProgress>[0]> = {}): string {
  return renderToStaticMarkup(
    <PrepareProgress state={state} sseStatus="idle" jobStatus="ready" {...props} />,
  );
}

describe('PrepareProgress 不说谎', () => {
  it('课程已发布且没有任务在跑时，不再显示"正在启动生成流程 / 连接中"', () => {
    const html = render(initialPrepareState, {
      live: false,
      finished: true,
      publishedSections: 4,
    });

    expect(html).not.toContain('正在启动生成流程');
    expect(html).not.toContain('连接中');
    expect(html).toContain('四段全部完成，可以开始学习了。');
    expect(html).toContain('已完成');
  });

  it('部分发布的课程只把已发布章节标成已完成', () => {
    const html = render(initialPrepareState, {
      live: false,
      finished: true,
      publishedSections: 3,
    });

    expect(html).toContain('课程已生成（3 / 4 段已发布）');
    expect(html).not.toContain('四段全部完成');
    expect(html.split('已完成').length - 1).toBe(4); // 3 段 + 1 个连接徽标
  });

  it('没有任务也没有课程时明确说"没有正在进行的生成任务"', () => {
    const html = render(initialPrepareState, { live: false, finished: false });

    expect(html).toContain('没有正在进行的生成任务。');
    expect(html).toContain('无进行中任务');
    expect(html).not.toContain('连接中');
  });

  it('真正在生成时仍然显示进度与实时连接（不能把正常的"生成中"也改没了）', () => {
    const state: PrepareState = {
      ...initialPrepareState,
      sections: ['done', 'active', 'pending', 'pending'],
      message: 'plan_curriculum',
    };
    const html = render(state, { live: true, finished: false });

    expect(html).toContain('1 / 4 段完成 · plan_curriculum');
    expect(html).toContain('连接中'); // sseStatus='idle' + live → 仍如实说"连接中"
  });
});
