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

The successful result contains `image.url` and `image.alt` for the existing
inline-image UI. The handler requests one image, preserves its MIME type, and
reports failure if the provider returns no usable image. Outputs are inline;
for a subsequent edit, upload the generated image and use its UUID.

Both AI image and video tools are available in the generic registry and the
standalone MCP server. Include their names explicitly in the MCP allowlist;
the default allowlist continues to expose the existing local tools.

Lucy registers a thin `image_generate` configuration adapter. Its existing
video and SVG adapters remain in place. Chat agents already allowed to use
`generate_image` gain `image_generate`; the Lucy MCP agent's allowlist is unchanged.

Release order: publish Galet 0.1.20, then Galet-tools 0.1.17, then install Lucy's
updated pinned requirements. The new packages are not published by these PRs.
