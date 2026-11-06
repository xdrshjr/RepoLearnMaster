/**
 * Markdown sanitisation allowlist — spec §7.6 / T-SEC-4.
 *
 * Every AI-generated markdown (lesson narration, quiz explanations, Momo
 * answers, book chapters) is rendered through `react-markdown` +
 * `rehype-sanitize` with this schema. Raw HTML is never injected with
 * `dangerouslySetInnerHTML`.
 *
 * We start from `defaultSchema` (which already whitelists tags and locks the
 * `href`/`src` protocols to http/https/mailto/tel/relative) and add only what
 * GFM needs: tables, strikethrough, task-list checkboxes.
 */

import { defaultSchema } from 'rehype-sanitize';

type Schema = typeof defaultSchema;

const TAGS = [
  ...(defaultSchema.tagNames ?? []),
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
  'del',
  'img',
  'figure',
  'figcaption',
  'details',
  'summary',
  'kbd',
  'sup',
  'sub',
];

export const markdownSanitizeSchema: Schema = {
  ...defaultSchema,
  tagNames: Array.from(new Set(TAGS)),
  attributes: {
    ...defaultSchema.attributes,
    a: [...(defaultSchema.attributes?.a ?? []), 'href', 'title', 'rel', 'target'],
    img: [...(defaultSchema.attributes?.img ?? []), 'src', 'alt', 'title', 'width', 'height'],
    code: [...(defaultSchema.attributes?.code ?? []), 'className'],
    span: [...(defaultSchema.attributes?.span ?? []), 'className'],
    div: [...(defaultSchema.attributes?.div ?? []), 'className'],
    pre: [...(defaultSchema.attributes?.pre ?? []), 'className'],
    td: ['align', 'colSpan', 'rowSpan'],
    th: ['align', 'colSpan', 'rowSpan', 'scope'],
    table: ['className'],
    ol: ['start'],
    input: [
      ['type', 'checkbox'],
      'checked',
      'disabled',
    ],
    details: ['open'],
  },
  // No inline event handlers, no <script>, no style attributes — ever.
  protocols: {
    ...defaultSchema.protocols,
    href: ['http', 'https', 'mailto', 'tel'],
    src: ['http', 'https'],
  },
  clobberPrefix: 'rl-',
  strip: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'link', 'meta'],
};

export const SAFE_LINK_REL = 'noopener noreferrer nofollow';
