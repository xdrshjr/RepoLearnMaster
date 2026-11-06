/**
 * 首页 hero 输入的解析器：纯函数，但**直接决定课程 cache_key**，
 * 因此每一条分支都值得钉住（尤其"非法字符不能让页面崩"）。
 */
import { describe, expect, it } from 'vitest';

import { courseRoute, parseRepoUrl, repoRoute } from './parseRepoUrl';

describe('parseRepoUrl', () => {
  it('parses a canonical https URL', () => {
    const r = parseRepoUrl('https://github.com/facebook/react');
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.repo.fullName).toBe('facebook/react');
      expect(r.repo.url).toBe('https://github.com/facebook/react');
      expect(r.repo.ref).toBeNull();
      expect(r.warning).toBeNull();
    }
  });

  it('accepts the shorthand forms people actually paste', () => {
    for (const input of ['github.com/facebook/react', 'git@github.com:facebook/react.git', 'facebook/react']) {
      const r = parseRepoUrl(input);
      expect(r.ok, input).toBe(true);
      if (r.ok) expect(r.repo.fullName).toBe('facebook/react');
    }
  });

  it('extracts the ref from a /tree/ link', () => {
    const r = parseRepoUrl('https://github.com/facebook/react/tree/main/packages');
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.repo.ref).toBe('main/packages');
      expect(r.warning).toContain('main/packages');
    }
  });

  it('keeps a malformed ref from throwing (page used to white-screen)', () => {
    const r = parseRepoUrl('https://github.com/facebook/react/tree/100%');
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.warning).toContain('100%');
  });

  it('rejects non-github hosts and reserved owners', () => {
    expect(parseRepoUrl('https://gitlab.com/a/b').ok).toBe(false);
    expect(parseRepoUrl('https://github.com/orgs/nodejs').ok).toBe(false);
  });

  it('rejects empty input and spaces', () => {
    expect(parseRepoUrl('   ').ok).toBe(false);
    expect(parseRepoUrl('facebook / react').ok).toBe(false);
  });

  it('builds encoded routes', () => {
    expect(repoRoute({ owner: 'a b', name: 'c' })).toBe('/repo/a%20b/c');
    expect(courseRoute('cv_1', 'recap')).toBe('/course/cv_1/recap');
  });
});
