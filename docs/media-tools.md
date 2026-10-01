# Media tools

- `generate_image`: existing Pillow rectangle/text renderer, unchanged.
- `image_generate`: AI generation and reference-image editing through Galet.
- `video_generate`: existing Galet video handler, already extracted from Lucy.
- `generate_svg`: existing SVG validation/sanitization, already extracted from Lucy.

Install `galet-tools[image]` for OpenAI image generation. For Gemini image/video
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

The successful result contains only `image_id`, `path`, `mime_type`, `download_url`,
and `image.url`/`image.alt` plus status/model fields. There is no image payload in
the tool result. The existing SSE image event carries the download URL; Lucy's
`/download/image/{uuid}?accountName=...` endpoint serves the file under the same
API-key guard as the video endpoint. The UI downloads it with the configured API
key and displays a browser blob URL, including after chat-history reload. For a
subsequent edit, pass the returned UUID directly without uploading it again.

Both AI image and video tools are available in the generic registry and the
standalone MCP server. Include their names explicitly in the MCP allowlist;
the default allowlist continues to expose the existing local tools.

Lucy registers a thin `image_generate` configuration adapter. Its existing
video and SVG adapters remain in place. Chat agents already allowed to use
`generate_image` gain `image_generate`; the Lucy MCP agent's allowlist is unchanged.

Publish the updated Galet-tools package before installing the matching release
in Lucy. Update Lucy's pinned requirement to the version actually published, and
deploy the UI image-download changes. Galet's image API requires no change here.
