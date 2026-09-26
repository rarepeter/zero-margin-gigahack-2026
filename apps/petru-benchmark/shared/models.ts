// Explicit allowlist: a catalog listing alone does not establish open weights.
// Sources and licenses were checked on 2026-09-25. Availability is checked live.
const hostedModels = [
  { id: 'openai/whisper-large-v3', name: 'Whisper large-v3', maker: 'OpenAI', size: '1.55B', license: 'Apache-2.0', weights: 'https://huggingface.co/openai/whisper-large-v3', primary: true, family: 'whisper', note: 'Accuracy baseline. Supports Romanian, Russian, and English.' },
  { id: 'openai/whisper-large-v3-turbo', name: 'Whisper large-v3 Turbo', maker: 'OpenAI', size: '809M', license: 'MIT', weights: 'https://huggingface.co/openai/whisper-large-v3-turbo', primary: true, family: 'whisper', note: 'Faster Whisper variant. Compare missed words and language switches.' },
  { id: 'nvidia/parakeet-tdt-0.6b-v3', name: 'Parakeet TDT v3', maker: 'NVIDIA', size: '600M', license: 'CC-BY-4.0', weights: 'https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3', primary: true, family: 'parakeet', note: 'Supports all three languages. No verified vocabulary-hint option here.' },
  { id: 'qwen/qwen3-asr-1.7b', name: 'Qwen3-ASR 1.7B', maker: 'Qwen', size: '1.7B', license: 'Apache-2.0', weights: 'https://huggingface.co/Qwen/Qwen3-ASR-1.7B', primary: true, family: 'qwen', note: 'Supports all three languages. Romanian accuracy needs careful comparison.' },
  { id: 'qwen/qwen3-asr-0.6b', name: 'Qwen3-ASR 0.6B', maker: 'Qwen', size: '600M', license: 'Apache-2.0', weights: 'https://huggingface.co/Qwen/Qwen3-ASR-0.6B', primary: true, family: 'qwen', note: 'Compact alternative. Compare against the 1.7B model on the same recording.' },
  { id: 'mistralai/voxtral-mini-3b-2507', name: 'Voxtral Mini 3B', maker: 'Mistral', size: '3B', license: 'Apache-2.0', weights: 'https://huggingface.co/mistralai/Voxtral-Mini-3B-2507', primary: false, family: 'voxtral', note: 'Exploratory. The model card does not list Romanian or Russian among supported languages.' },
  { id: 'mistralai/voxtral-small-24b-2507-stt', name: 'Voxtral Small 24B', maker: 'Mistral', size: '24B', license: 'Apache-2.0', weights: 'https://huggingface.co/mistralai/Voxtral-Small-24B-2507', primary: false, family: 'voxtral', note: 'Exploratory, larger model. Romanian and Russian are not listed in its supported languages.' },
] as const;

export const OPENROUTER_MODELS = hostedModels.map(model => ({ ...model, provider: 'openrouter' as const }));
export type OpenRouterModelId = (typeof OPENROUTER_MODELS)[number]['id'];
export const LOCAL_WHISPER_MODEL = {
  id: 'local/FraPiz/whisper-large-v3-turbo-moldovan-romanian',
  name: 'Moldovan Romanian Whisper', maker: 'FraPiz', size: '809M', license: 'Apache-2.0',
  weights: 'https://huggingface.co/FraPiz/whisper-large-v3-turbo-moldovan-romanian',
  primary: false, family: 'whisper', provider: 'local',
  note: 'Runs on this computer. Fine-tuned on Moldovan Romanian educational speech.',
} as const;
export const MODELS = [...OPENROUTER_MODELS, LOCAL_WHISPER_MODEL] as const;
export type Model = (typeof MODELS)[number];
export type ModelId = Model['id'];
export const modelIds: [ModelId, ...ModelId[]] = [MODELS[0].id, ...MODELS.slice(1).map(m => m.id)];
export const unavailableModels = [
  { name: 'VibeVoice-ASR', reason: 'Open weights, but not listed on OpenRouter.', weights: 'https://huggingface.co/microsoft/VibeVoice-ASR' },
  { name: 'Canary-1B-v2', reason: 'Open weights, but not listed on OpenRouter.', weights: 'https://huggingface.co/nvidia/canary-1b-v2' },
];
