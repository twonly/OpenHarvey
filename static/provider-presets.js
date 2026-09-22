export const PROVIDER_PRESETS = [
  {
    id: "deepseek",
    label: "DeepSeek",
    kind: "openai",
    baseUrl: "https://api.deepseek.com/v1",
    exampleModels: ["deepseek-chat", "deepseek-reasoner"],
  },
  {
    id: "moonshot",
    label: "Kimi 月之暗面",
    kind: "openai",
    baseUrl: "https://api.moonshot.cn/v1",
    exampleModels: ["kimi-k2-turbo-preview", "kimi-latest"],
  },
  {
    id: "zhipu",
    label: "智谱 GLM",
    kind: "openai",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    exampleModels: ["glm-4.6", "glm-4-flash"],
  },
  {
    id: "qwen",
    label: "通义千问",
    kind: "openai",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    exampleModels: ["qwen-plus", "qwen-max", "qwen-turbo"],
  },
  {
    id: "doubao",
    label: "豆包 / 火山方舟",
    kind: "openai",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    exampleModels: ["doubao-seed-1-6-250615"],
    note: "模型一栏填推理接入点 ID 或模型版本号",
  },
  {
    id: "stepfun",
    label: "阶跃星辰",
    kind: "openai",
    baseUrl: "https://api.stepfun.com/v1",
    exampleModels: ["step-3", "step-2-mini"],
  },
  {
    id: "minimax",
    label: "MiniMax",
    kind: "anthropic",
    baseUrl: "https://api.minimaxi.com/anthropic",
    exampleModels: ["MiniMax-M3", "MiniMax-M2"],
    extraBody: '{"thinking":{"type":"enabled"}}',
    note: "默认走原生 Anthropic 协议，思考会单独输出（已默认开启思考）。也提供 OpenAI 兼容接口 https://api.minimaxi.com/v1，但该接口会把思考混在正文里",
  },
  {
    id: "xiaomi",
    label: "小米 MiMo",
    kind: "openai",
    baseUrl: "https://api.xiaomimimo.com/v1",
    exampleModels: ["mimo-v2-pro", "mimo-v2-flash"],
    note: "也提供 Anthropic 兼容接口 https://api.xiaomimimo.com/anthropic（用 Claude 协议时选它）",
  },
  {
    id: "siliconflow",
    label: "硅基流动",
    kind: "openai",
    baseUrl: "https://api.siliconflow.cn/v1",
    exampleModels: ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen3-32B"],
  },
  {
    id: "openai",
    label: "OpenAI",
    kind: "openai",
    baseUrl: "https://api.openai.com/v1",
    exampleModels: ["gpt-4o-mini", "gpt-4.1"],
  },
  {
    id: "anthropic",
    label: "Anthropic Claude",
    kind: "anthropic",
    baseUrl: "https://api.anthropic.com",
    exampleModels: ["claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-8"],
  },
  {
    id: "gemini",
    label: "Google Gemini",
    kind: "openai",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    exampleModels: ["gemini-2.5-flash", "gemini-2.5-pro"],
    note: "使用 Gemini 的 OpenAI 兼容接口",
  },
  {
    id: "xai",
    label: "xAI Grok",
    kind: "openai",
    baseUrl: "https://api.x.ai/v1",
    exampleModels: ["grok-4", "grok-3-mini"],
  },
  {
    id: "groq",
    label: "Groq",
    kind: "openai",
    baseUrl: "https://api.groq.com/openai/v1",
    exampleModels: ["llama-3.3-70b-versatile"],
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    kind: "openai",
    baseUrl: "https://openrouter.ai/api/v1",
    exampleModels: ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4.6"],
  },
  {
    id: "orcarouter",
    label: "OrcaRouter",
    kind: "openai",
    baseUrl: "https://api.orcarouter.ai/v1",
    exampleModels: [
      "orcarouter/auto",
      "openai/gpt-4o-mini",
      "anthropic/claude-sonnet-4.6",
      "deepseek/deepseek-chat",
    ],
    note: "支持一键授权或手动粘贴 sk-orca-… Key。Auto 会按请求动态选模型；做可复现测速时请选择固定模型 ID。",
  },
  {
    id: "ollama",
    label: "Ollama 本地",
    kind: "openai",
    baseUrl: "http://localhost:11434/v1",
    exampleModels: ["qwen3:8b", "llama3.1"],
    note: "本地部署可使用此地址；云端沙箱不能访问你电脑的 localhost，请填写可访问的服务地址",
  },
  {
    id: "custom",
    label: "自定义（OpenAI 兼容）",
    kind: "openai",
    baseUrl: "https://",
    exampleModels: [],
    note: "任何兼容 /chat/completions 流式接口的服务",
  },
];


export const EXTRA_PRESETS = [
 ['开思考 · Qwen', {enable_thinking:true}], ['关思考 · Qwen', {enable_thinking:false}],
 ['开思考 · GLM / 豆包', {thinking:{type:'enabled'}}], ['关思考 · GLM / 豆包', {thinking:{type:'disabled'}}],
 ['关思考 · vLLM / 硅基流动', {chat_template_kwargs:{enable_thinking:false}}],
 ['开思考 · Anthropic', {thinking:{type:'enabled',budget_tokens:8192},max_tokens:16384}],
 ['自适应思考 · Claude', {thinking:{type:'adaptive'}}], ['清空', {}],
];
export function parseExtraBody(value){
 const result=value.trim()?JSON.parse(value):{};
 if(!result || typeof result!=='object' || Array.isArray(result))throw Error('额外请求参数必须是 JSON 对象');
 if(Object.keys(result).some(k=>['model','messages','stream','tools','tool_choice','system'].includes(k)))throw Error('额外请求参数不能覆盖 model、messages、stream、tools、tool_choice 或 system');
 return result;
}
