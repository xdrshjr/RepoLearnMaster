import { describe, expect, it } from 'vitest';

import { autoAssign, PROVIDERS, providerOption } from '@/stores/setupWizard';
import type { ModelItem } from '@/lib/api/types';

function model(
  id: string,
  options: Partial<ModelItem['capabilities']> = {},
  contextWindow = 100_000,
  price = 1,
): ModelItem {
  return {
    id,
    display_name: id,
    context_window: contextWindow,
    price,
    capabilities: {
      text: true,
      vision: false,
      audio_in: false,
      audio_out: false,
      tools: true,
      json_mode: false,
      streaming: true,
      thinking: false,
      context_window: contextWindow,
      price_in: price,
      price_out: price,
      ...options,
    },
  };
}

describe('provider catalogue (spec §3.6.2 S1)', () => {
  it('offers the six protocols the spec requires', () => {
    expect(PROVIDERS.map((provider) => provider.key)).toEqual([
      'anthropic',
      'openai',
      'google',
      'custom-openai',
      'custom-anthropic',
      'custom-gemini',
    ]);
  });

  it('only exposes base_url for custom protocols', () => {
    expect(providerOption('anthropic')?.needsBaseUrl).toBe(false);
    expect(providerOption('openai')?.needsBaseUrl).toBe(false);
    expect(providerOption('google')?.needsBaseUrl).toBe(false);
    expect(providerOption('custom-openai')?.needsBaseUrl).toBe(true);
    expect(providerOption('custom-anthropic')?.protocol).toBe('anthropic_compatible');
    expect(providerOption('custom-gemini')?.protocol).toBe('gemini_compatible');
    expect(providerOption(null)).toBeNull();
  });
});

describe('auto-assign by capability (spec §3.6.2 S4)', () => {
  it('picks the largest context window for planner/writer', () => {
    const models = [
      model('small', {}, 32_000, 3),
      model('large', {}, 200_000, 5),
      model('cheap', {}, 100_000, 0.2),
    ];
    const { roles } = autoAssign(models);
    expect(roles.planner).toBe('large');
    expect(roles.writer).toBe('large');
    // critic only reviews, so the cheapest text model wins
    expect(roles.critic).toBe('cheap');
  });

  it('assigns a vision model when one exists and warns when it does not', () => {
    const withVision = autoAssign([model('a'), model('vision-model', { vision: true })]);
    expect(withVision.roles.vision).toBe('vision-model');

    const withoutVision = autoAssign([model('a')]);
    expect(withoutVision.roles.vision).toBe('');
    expect(withoutVision.notes.join(' ')).toContain('vision');
  });

  it('prefers a json_mode model for quiz and never invents an embed model', () => {
    const models = [model('big', {}, 200_000), model('json', { json_mode: true }, 16_000)];
    const { roles } = autoAssign(models);
    expect(roles.quiz).toBe('json');
    expect(roles.embed).toBe('');
  });

  it('returns an empty assignment (not a crash) when probing found nothing', () => {
    const { roles, notes } = autoAssign([]);
    expect(roles.planner).toBe('');
    expect(notes).toHaveLength(1);
  });
});
