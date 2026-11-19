# Security and privacy

LumaNest is a local single-user application. It binds to `127.0.0.1` by default. There is no user authentication or multi-user authorization; do not expose its port directly to a network or public tunnel.

Photos and face embeddings are sensitive. Keep `runtime/`, `weights/`, `.env*`, API keys, logs, backups and model files outside Git and release assets. The packager uses an explicit allowlist and scans common credential formats. This is a preventive check, not a guarantee that every secret format can be detected.

API credentials entered in the UI are kept in server RAM; credentials provided through environment variables follow the lifetime of the launching process. Never paste a key into chat. Chat with Gemini, OpenAI or an OpenAI-compatible API sends conversation text only. When the user picks an API image model and explicitly clicks create, the selected photo is downscaled to at most 1536 px on its long side and sent to that provider, which repaints it; gateways without an image-edit endpoint first send the photo to their vision model to describe the scene. Face search, semantic search, subject masks and local style transfer never upload photos; choose the local Qwen assistant to keep every photo on the machine. Provider data policies and charges apply.

Upstream code/model URLs, pinned revisions and notices are recorded in `THIRD_PARTY.md` and local provenance files. Model loaders use safetensors or `torch.load(weights_only=True)`. The application does not enable remote modeling code from Hugging Face. Review upstream model/dataset conditions before redistributing weights or using them commercially.

Do not post photos, embeddings, logs or keys in public issues. Report vulnerabilities through a private channel to the repository owner.
