# FreeLLMAPI Sidecar Runtime TODO

News Sentry uses FreeLLMAPI as a local VPS sidecar for high-frequency OpenAI-compatible AI calls. The sidecar is deployed by the GitHub `Deploy` workflow and bound to loopback only:

- Preview: `http://127.0.0.1:13081/v1`
- Production: `http://127.0.0.1:13080/v1`

The workflow installs or updates `https://github.com/tashfeenahmed/freellmapi`, builds the server, starts a systemd service, and writes `FREELLMAPI_BASE_URL` plus public publication worker cadence into the News Sentry VPS `.env`.

## Manual Secrets Required

Do not commit any of these values to this repository.

1. Open the FreeLLMAPI dashboard on the VPS through a secure SSH tunnel.
2. Add upstream provider keys on the FreeLLMAPI Keys page.
3. Copy the generated FreeLLMAPI unified API key.
4. Add the unified key to the matching News Sentry VPS env file:
   - Preview: `/opt/news-sentry/preview/.env`
   - Production: `/opt/news-sentry/production/.env`
5. Restart News Sentry after editing the env file:
   - Preview: `systemctl restart news-sentry-preview`
   - Production: `systemctl restart news-sentry`

Required News Sentry env value:

```bash
FREELLMAPI_API_KEY=<copy from FreeLLMAPI dashboard>
```

FreeLLMAPI upstream provider keys to configure manually:

- Google
- Groq
- Cerebras
- Mistral
- OpenRouter
- GitHub Models
- Cohere
- Cloudflare
- HuggingFace
- Z.ai
- NVIDIA
- Ollama Cloud
- Kilo
- Pollinations
- LLM7
- OVH
- OpenCode Zen

## Runtime Notes

- FreeLLMAPI stores upstream keys in its own SQLite database encrypted with `ENCRYPTION_KEY`.
- The deploy workflow creates and preserves `ENCRYPTION_KEY` in `/opt/news-sentry/<env>/freellmapi/.env`.
- The sidecar database is stored outside the git checkout at `/opt/news-sentry/<env>/freellmapi/data`.
- Public News Sentry calls use `FREELLMAPI_BASE_URL=http://127.0.0.1:<port>/v1` and `FREELLMAPI_DEFAULT_MODEL=auto`.
- Public publication translation now uses the same FreeLLMAPI route as AI summary/reason generation. LibreTranslate, Cloudflare Workers AI, and MyMemory adapters are no longer in the default public publication path.
- If `FREELLMAPI_API_KEY` is missing, public publication processing can only fall back to the low-frequency OpenRouter/NVIDIA translation routes. Items without AI publication fields remain hidden from the public site.

## Public Publication Env Defaults

The workflow writes these values into the VPS News Sentry `.env` if needed:

```bash
NEWSSENTRY_PUBLIC_TRANSLATION=1
NEWSSENTRY_PUBLIC_TRANSLATION_INTERVAL=5
NEWSSENTRY_PUBLIC_TRANSLATION_PER_CYCLE=50
NEWSSENTRY_PUBLIC_TRANSLATION_CANDIDATES=500
NEWSSENTRY_PUBLIC_PUBLICATION_INTERVAL=5
NEWSSENTRY_PUBLIC_PUBLICATION_PER_CYCLE=50
FREELLMAPI_BASE_URL=http://127.0.0.1:<port>/v1
FREELLMAPI_DEFAULT_MODEL=auto
```

## Verification

After deployment and key setup:

```bash
curl -sf http://127.0.0.1:<port>/api/ping
curl -sf -H "Authorization: Bearer $FREELLMAPI_API_KEY" \
  http://127.0.0.1:<port>/v1/models
curl -sf https://news-sentry.com/api/v1/ai/translation/status
curl -sf https://news-sentry.com/api/v1/public/news
```

Public news should only expose Chinese-ready items with title, summary, one-line summary, and AI-generated recommendation reason.
