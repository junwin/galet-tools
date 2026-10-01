# Media tools

The old Pillow `generate_image` tool has been removed. Use `image_generate` for AI images.

- `image_generate`: AI generation and reference-image editing through Galet.
- `video_generate`: existing Galet video handler, already extracted from Lucy.
- `generate_svg`: existing SVG validation/sanitization, already extracted from Lucy.

Install Galet alongside Galet-tools for image generation. For Gemini image/video
models also install `galet[gemini]`. Media provider clients initialize on first
use, not while registering tools.

```python
from galet_tools.tools.image_generate_handler import ImageGenerateHandler

handler = ImageGenerateHandler(storage_resolver)
result = handler.execute({
    "prompt": "Change the background; keep the garments unchanged.",
    "model": "gpt-image-1",
    "size": "1024x1024",
    "quality": "high",
    "image_ids": [uploaded_image_uuid],
    "messages": [],
}, account_name="arla")
```

`image_ids` must be UUIDs from the host upload endpoint. Both current references
and explicit earlier messages are resolved within the executing account using
upload metadata. Cross-account images and paths escaping storage are rejected
before the model call. Earlier turns use `role`, `text`, and `image_ids` fields.
Unrelated execution context or chat history is never sent automatically.

The handler saves the full-resolution output as `images/{account}/{uuid}.png`
with the same JSON metadata contract as host uploads. PNG conversion preserves
alpha. Provider base64 stays inside the handler; HTTPS provider URLs are downloaded
before saving. Invalid image data and failed downloads return an error.

The successful result contains only `ok`, `tool`, `model`, `image_id`, `path`
and `mime_type`. Provider bytes and URLs stay inside the handler. The result
contains no HTTP routes or browser presentation fields: the host owns delivery.

Lucy resolves the UUID within the executing account and sends an inline preview
in one SSE image event using the same service as `serve_image`. The model receives
compact metadata only. Saved chat events retain the UUID and host-owned download
reference, never the preview bytes. GPTChum renders the preview automatically,
deduplicates cards by UUID, and uses authenticated downloads when reopening chats
or when the user explicitly downloads the full-resolution image. For an edit,
pass the returned UUID directly without uploading it again.

Both AI image and video tools are available in the generic registry and the
standalone MCP server. Include their names explicitly in the MCP allowlist;
the default allowlist continues to expose the existing local tools.

Lucy registers a thin `image_generate` configuration adapter. Its existing
video and SVG adapters remain in place. Agents that create AI images must allow
`image_generate`; remove obsolete
`generate_image` entries from any local agent or MCP allowlists.

Publish the updated Galet-tools package before installing the matching release
in Lucy. Update Lucy's pinned requirement to the version actually published, and
deploy the UI image-download changes. Galet's image API requires no change here.
