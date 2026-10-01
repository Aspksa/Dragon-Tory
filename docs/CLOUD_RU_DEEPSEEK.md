# Cloud.ru DeepSeek for Dragon Tory

Dragon Tory supports Cloud.ru Foundation Models through its OpenAI-compatible API.

Default configuration:

```env
TOORU_DEEPSEEK_BASE_URL=https://foundation-models.api.cloud.ru/v1
TOORU_DEEPSEEK_MODEL=deepseek-ai/DeepSeek-V4-Flash
TOORU_DEEPSEEK_API_KEY=
```

Put the Foundation Models Key Secret only in the local `.env` file:

```env
TOORU_DEEPSEEK_API_KEY=your-secret-key
```

Do not put the key into Python source, README files, commits, screenshots, or
GitHub Actions configuration.

`.env` is ignored by Git. On first startup, if `.env` does not exist,
Dragon Tory copies `.env.example` to `.env` automatically.

When the key is present, application startup registers an OpenAI-compatible
provider under the internal provider name `deepseek`. Memory Intelligence and
Memory Guardian can then use it automatically.

The default model is:

`deepseek-ai/DeepSeek-V4-Flash`

The provider adapter uses the OpenAI Python SDK and the chat-completions API.
