# Create and install extensions

Extensions are JSON manifests plus a separate local service. Cortana never imports extension Python/JavaScript, executes an install command, or serves extension files. A missing extension contributes no tools or product-specific text.

## Install

1. Start the extension's local service using its own instructions. It produces a private JSON connection file.
2. On your PC, open Cortana → Systems → Extensions → Import extension.
3. Select that JSON, review the service address and tools, and press Install. New and updated extensions are disabled initially.
4. Press Enable, then ask Cortana naturally to use that ability. The model chooses the registered tools; no fixed voice phrases are required.
5. Disable or Remove unregisters the tools. Stop the separate service separately; removing its manifest does not terminate jobs that already started there.

Paired phones cannot manage or use extensions. The Abilities switch disables their tools too. Actions marked `approval:true` use the existing one-use, ten-minute approval cards on the PC. Installed service tokens are private database values and never returned by the management API.

## Make your own

Copy `examples/extension-template/service.py` into your own project and run it with Python 3.11+. It has no dependencies. Edit `ID`, `NAME`, `DESCRIPTION`, the `TOOLS` list and `handle()`. The example creates `extension.json` next to itself; import that file. Restarting this minimal example rotates its connection, so import the new file after restarting it. A production service should persist its token in its own private data directory.

Each tool has a name, description, fixed `/v1/...` path, `approval` boolean, and an object parameter schema with scalar string/boolean/integer/number properties. Its schema is passed directly to the local model. Descriptions should explain when to use the ability. Names are automatically namespaced, so authors do not modify Cortana code.

Transport: Cortana POSTs `{"arguments":{...},"approved":false}` with `Authorization: Bearer TOKEN` and `Content-Type: application/json`. Return a JSON object, at most 32 KB, within 15 seconds. For long work return a job ID immediately and provide a progress tool. Never embed HTML. Results are untrusted data; the model sees at most 2,500 characters, while returned results are also shown as escaped JSON cards without relying on a model summary.

Use `approval:true` for browsing tasks or anything that writes files or changes external state, and enforce that approval again in the service. Read-only status and cancellation can omit approval. A manifest is not a sandbox for the separate service: run only services you trust, with their own narrow permissions.

## Limits and validation

- Manifest version 1, at most 30 KB, unique lowercase extension ID and tool names, explicit semantic version.
- Literal `http://127.0.0.1:PORT`, ports 1024–65535; no credentials, URL parameters, remote hostnames, proxies or redirects.
- Private random bearer token, 32–128 URL-safe characters. Never commit the generated connection file.
- Up to four installed extensions, four tools per manifest and four enabled extension tools in total. Enabled schemas have a combined 5,500-character cap.
- Schema text consumes an equivalent amount of the chat history character allowance; the system prompt and context window stay intact. Real-model extension selection still needs testing on the owner's installed model.
- Updating or disabling a manifest invalidates an outstanding approval. No wildcard static routes, arbitrary subprocess entrypoints, custom HTML or dynamic imports.

See [API](API.md) and the example service for the exact protocol.
