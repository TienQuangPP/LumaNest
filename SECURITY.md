# Security and privacy

LumaNest is a local single-user application. It binds to `127.0.0.1` by default. There is no user authentication or multi-user authorization; do not expose its port directly to a network or public tunnel.

Photos and face embeddings are sensitive. Keep `runtime/`, `weights/`, `.env*`, API keys, logs, backups and model files outside Git and release assets. The packager uses an explicit allowlist and scans common credential formats. This is a preventive check, not a guarantee that every secret format can be detected.

API credentials entered in the UI are kept in server RAM; credentials provided through environment variables follow the lifetime of the launching process. Never paste a key into chat. Gemini/OpenAI receive text only when selected; image generation occurs after an explicit creation action. Provider data policies and charges apply.

Upstream code/model URLs, pinned revisions and notices are recorded in `THIRD_PARTY.md` and local provenance files. Model loaders use safetensors or `torch.load(weights_only=True)`. The application does not enable remote modeling code from Hugging Face. Review upstream model/dataset conditions before redistributing weights or using them commercially.

Do not post photos, embeddings, logs or keys in public issues. Report vulnerabilities through a private channel to the repository owner.
