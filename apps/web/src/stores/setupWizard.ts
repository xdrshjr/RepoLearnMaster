'use client';

/**
 * Setup wizard draft — spec §3.6.2.
 *
 * Persisted to `sessionStorage` so "back a step never loses input" (T-SETUP-3)
 * survives both in-wizard navigation and an accidental reload, but does not
 * outlive the tab (an API key must not sit in localStorage forever).
 */

import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

import type {
  LlmProbeResponse,
  LlmProtocol,
  ModelItem,
  RoleName,
  TtsProbeResponse,
} from '@/lib/api/types';
import { ROLE_NAMES } from '@/lib/api/types';

export type ProviderKey =
  | 'anthropic'
  | 'openai'
  | 'google'
  | 'custom-openai'
  | 'custom-anthropic'
  | 'custom-gemini';

export interface ProviderOption {
  key: ProviderKey;
  name: string;
  protocol: LlmProtocol;
  vendor: 'anthropic' | 'openai' | 'google' | 'custom';
  blurb: string;
  needsBaseUrl: boolean;
  baseUrlPlaceholder?: string;
  keyHint: string;
}

export const PROVIDERS: ProviderOption[] = [
  {
    key: 'anthropic',
    name: 'Anthropic',
    protocol: 'anthropic_messages',
    vendor: 'anthropic',
    blurb: 'Claude 系列。讲解质量与长文本最稳，推荐作为 writer。',
    needsBaseUrl: false,
    keyHint: 'sk-ant-...',
  },
  {
    key: 'openai',
    name: 'OpenAI',
    protocol: 'openai_chat',
    vendor: 'openai',
    blurb: 'GPT 系列。生态最全，json_mode 与工具调用支持好。',
    needsBaseUrl: false,
    keyHint: 'sk-...',
  },
  {
    key: 'google',
    name: 'Google Gemini',
    protocol: 'google_generate',
    vendor: 'google',
    blurb: 'Gemini 系列。上下文窗口大，读大文件更省钱。',
    needsBaseUrl: false,
    keyHint: 'AIza...',
  },
  {
    key: 'custom-openai',
    name: '自定义（OpenAI 兼容）',
    protocol: 'openai_compatible',
    vendor: 'custom',
    blurb: '任何 /v1/chat/completions 兼容网关（含 Azure、vLLM、本地模型）。',
    needsBaseUrl: true,
    baseUrlPlaceholder: 'https://your-gateway.example.com/v1',
    keyHint: '网关下发的 Key',
  },
  {
    key: 'custom-anthropic',
    name: '自定义（Anthropic 兼容）',
    protocol: 'anthropic_compatible',
    vendor: 'custom',
    blurb: '兼容 /v1/messages 的网关，system 独立字段、max_tokens 必填。',
    needsBaseUrl: true,
    baseUrlPlaceholder: 'https://your-gateway.example.com',
    keyHint: '网关下发的 Key',
  },
  {
    key: 'custom-gemini',
    name: '自定义（Gemini 兼容）',
    protocol: 'gemini_compatible',
    vendor: 'custom',
    blurb: '兼容 generateContent 的网关，图片走 inline_data。',
    needsBaseUrl: true,
    baseUrlPlaceholder: 'https://your-gateway.example.com/v1beta',
    keyHint: '网关下发的 Key',
  },
];

export function providerOption(key: ProviderKey | null): ProviderOption | null {
  if (!key) return null;
  return PROVIDERS.find((option) => option.key === key) ?? null;
}

export interface TtsDraft {
  app_id: string;
  access_token: string;
  cluster: string;
  voice_type: string;
}

export interface SetupDraftState {
  step: number;
  maxStepReached: number;
  provider: ProviderKey | null;
  protocol: LlmProtocol | null;
  baseUrl: string;
  apiKey: string;
  org: string;
  label: string;
  modelId: string | null;
  probe: LlmProbeResponse | null;
  probeErrorAt: number | null;
  ttsEnabled: boolean;
  tts: TtsDraft;
  ttsProbe: TtsProbeResponse | null;
  roles: Record<RoleName, string>;
  committed: { profile_id: string; revision: number } | null;

  setStep: (step: number) => void;
  next: () => void;
  back: () => void;
  selectProvider: (key: ProviderKey) => void;
  patch: (patch: Partial<Pick<SetupDraftState, 'baseUrl' | 'apiKey' | 'org' | 'label' | 'modelId'>>) => void;
  setProbe: (probe: LlmProbeResponse | null) => void;
  setTtsEnabled: (enabled: boolean) => void;
  patchTts: (patch: Partial<TtsDraft>) => void;
  setTtsProbe: (probe: TtsProbeResponse | null) => void;
  setRole: (role: RoleName, modelId: string) => void;
  applyAutoAssign: () => string[];
  setCommitted: (value: { profile_id: string; revision: number } | null) => void;
  reset: () => void;
}

const emptyRoles: Record<RoleName, string> = {
  planner: '',
  writer: '',
  critic: '',
  vision: '',
  quiz: '',
  embed: '',
};

const defaults = {
  step: 1,
  maxStepReached: 1,
  provider: null as ProviderKey | null,
  protocol: null as LlmProtocol | null,
  baseUrl: '',
  apiKey: '',
  org: '',
  label: '',
  modelId: null as string | null,
  probe: null as LlmProbeResponse | null,
  probeErrorAt: null as number | null,
  ttsEnabled: false,
  tts: {
    app_id: '',
    access_token: '',
    cluster: 'volcano_tts',
    voice_type: 'zh_female_wanwanxiaohe_moon_bigtts',
  } as TtsDraft,
  ttsProbe: null as TtsProbeResponse | null,
  roles: { ...emptyRoles },
  committed: null as { profile_id: string; revision: number } | null,
};

/**
 * Capability-based auto assignment (§3.6.2 S4).
 *
 * Rules, in priority order:
 *  - vision → a model with `capabilities.vision` (else left empty + warning);
 *  - quiz    → a model with `json_mode` (structured output), else writer;
 *  - planner/writer → the largest context window (they read the most code);
 *  - critic  → the cheapest usable text model (it only reviews);
 *  - embed   → only filled by an embedding-capable model: chat models are not
 *              silently misused for embeddings.
 */
export function autoAssign(models: ModelItem[]): { roles: Record<RoleName, string>; notes: string[] } {
  const notes: string[] = [];
  const textModels = models.filter((model) => model.capabilities.text !== false);
  if (textModels.length === 0) {
    return { roles: { ...emptyRoles }, notes: ['没有可用模型，先完成连通性测试。'] };
  }

  const byContext = [...textModels].sort(
    (a, b) => (b.context_window || b.capabilities.context_window) - (a.context_window || a.capabilities.context_window),
  );
  const primary = byContext[0]!;
  const cheap = [...textModels].sort(
    (a, b) => (a.capabilities.price_out || a.price) - (b.capabilities.price_out || b.price),
  )[0]!;
  const vision = textModels.find((model) => model.capabilities.vision);
  const jsonCapable = textModels.find((model) => model.capabilities.json_mode) ?? primary;

  const roles: Record<RoleName, string> = {
    planner: primary.id,
    writer: primary.id,
    critic: cheap.id,
    vision: vision?.id ?? '',
    quiz: jsonCapable.id,
    embed: '',
  };

  if (!vision) notes.push('没有支持图片输入的模型：vision 角色将退化为文本启发式（跳过 README 图表理解）。');
  notes.push(`planner/writer 使用上下文最大的 ${primary.display_name || primary.id}。`);
  notes.push(`critic 使用单价最低的 ${cheap.display_name || cheap.id}。`);

  return { roles, notes };
}

export const useSetupWizard = create<SetupDraftState>()(
  persist(
    (set, get) => ({
      ...defaults,

      setStep: (step) =>
        set((state) => ({
          step: Math.min(5, Math.max(1, step)),
          maxStepReached: Math.max(state.maxStepReached, Math.min(5, Math.max(1, step))),
        })),

      next: () => get().setStep(get().step + 1),
      back: () => get().setStep(get().step - 1),

      selectProvider: (key) => {
        const option = providerOption(key);
        set({
          provider: key,
          protocol: option?.protocol ?? null,
          // Switching between providers must not carry a stale probe result.
          probe: null,
          modelId: null,
          baseUrl: option?.needsBaseUrl ? get().baseUrl : '',
        });
      },

      patch: (patch) => set(patch),

      setProbe: (probe) =>
        set(() => {
          if (!probe || !probe.ok || probe.models.length === 0) {
            return { probe, probeErrorAt: probe ? Date.now() : null };
          }
          const existing = get().modelId;
          const stillThere = existing && probe.models.some((model) => model.id === existing);
          return {
            probe,
            probeErrorAt: null,
            modelId: stillThere ? existing : (probe.models[0]?.id ?? null),
          };
        }),

      setTtsEnabled: (enabled) => set({ ttsEnabled: enabled }),
      patchTts: (patch) => set((state) => ({ tts: { ...state.tts, ...patch } })),
      setTtsProbe: (probe) => set({ ttsProbe: probe }),

      setRole: (role, modelId) => set((state) => ({ roles: { ...state.roles, [role]: modelId } })),

      applyAutoAssign: () => {
        const models = get().probe?.models ?? [];
        const { roles, notes } = autoAssign(models);
        set({ roles });
        return notes;
      },

      setCommitted: (value) => set({ committed: value }),

      reset: () => set({ ...defaults, roles: { ...emptyRoles }, tts: { ...defaults.tts } }),
    }),
    {
      name: 'rl_setup_draft',
      storage: createJSONStorage(() => sessionStorage),
      // The draft is intentionally versioned: a shape change must not hydrate a
      // half-valid wizard state.
      version: 2,
      migrate: () => ({ ...defaults, roles: { ...emptyRoles } }) as unknown as SetupDraftState,
      partialize: (state) => ({
        step: state.step,
        maxStepReached: state.maxStepReached,
        provider: state.provider,
        protocol: state.protocol,
        baseUrl: state.baseUrl,
        apiKey: state.apiKey,
        org: state.org,
        label: state.label,
        modelId: state.modelId,
        probe: state.probe,
        ttsEnabled: state.ttsEnabled,
        tts: state.tts,
        ttsProbe: state.ttsProbe,
        roles: state.roles,
      }),
    },
  ),
);

export const ROLE_LABELS: Record<RoleName, { name: string; description: string }> = {
  planner: { name: 'planner · 规划', description: '读仓库结构，规划 4 章 12 课时的骨架。' },
  writer: { name: 'writer · 讲解', description: '写讲解文案、板书与代码注释，输出量最大。' },
  critic: { name: 'critic · 校验', description: '复核锚点与事实，只读不改，适合用便宜模型。' },
  vision: { name: 'vision · 看图', description: '理解 README 里的架构图（无多模态模型时退化为文本启发式）。' },
  quiz: { name: 'quiz · 出题', description: '生成预测题与解释，需要 json_mode 才能稳定出结构。' },
  embed: { name: 'embed · 向量', description: '可选。没有 embedding 模型时留空，搜索走全文扫描。' },
};

export const ROLE_ORDER: RoleName[] = [...ROLE_NAMES];
