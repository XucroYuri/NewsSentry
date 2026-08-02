export type ContainerEnvInput = {
  GEMINI_API_KEY?: string;
  OPENROUTER_API_KEY?: string;
  OPENROUTER_API_KEY_2?: string;
  NVIDIA_API_KEY?: string;
  NVIDIA_API_KEY_2?: string;
  OPENCODE_API_KEY?: string;
  OPENCODE_API_KEY_2?: string;
  REKA_API_KEY?: string;
  AGNES_API_KEY?: string;
  AGNES_API_KEY_2?: string;
  DEEPSEEK_API_KEY?: string;
  GROQ_API_KEY?: string;
  CLOUDFLARE_ACCOUNT_ID?: string;
  CLOUDFLARE_API_TOKEN?: string;
};

function definedEnv(vars: Record<string, string | undefined>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(vars).filter((entry): entry is [string, string] => Boolean(entry[1])),
  );
}

export function containerEnvVars(env: ContainerEnvInput): Record<string, string> {
  return definedEnv({
    NEWSSENTRY_DEPLOYMENT_ENV: "cloudflare-container",
    NEWSSENTRY_PROFILE: "cloudflare",
    NEWSSENTRY_AUTO_COLLECT: "0",
    NEWSSENTRY_COLLECT_STAGE: "all",
    NEWSSENTRY_PUBLIC_TRANSLATION: "1",
    NEWSSENTRY_FETCH_FULL_ARTICLE: "0",
    NEWSSENTRY_LOG_LEVEL: "INFO",
    GEMINI_API_KEY: env.GEMINI_API_KEY,
    OPENROUTER_API_KEY: env.OPENROUTER_API_KEY,
    OPENROUTER_API_KEY_2: env.OPENROUTER_API_KEY_2,
    NVIDIA_API_KEY: env.NVIDIA_API_KEY,
    NVIDIA_API_KEY_2: env.NVIDIA_API_KEY_2,
    OPENCODE_API_KEY: env.OPENCODE_API_KEY,
    OPENCODE_API_KEY_2: env.OPENCODE_API_KEY_2,
    REKA_API_KEY: env.REKA_API_KEY,
    AGNES_API_KEY: env.AGNES_API_KEY,
    AGNES_API_KEY_2: env.AGNES_API_KEY_2,
    DEEPSEEK_API_KEY: env.DEEPSEEK_API_KEY,
    GROQ_API_KEY: env.GROQ_API_KEY,
    CLOUDFLARE_ACCOUNT_ID: env.CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN: env.CLOUDFLARE_API_TOKEN,
  });
}

