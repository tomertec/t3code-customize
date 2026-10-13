# Pi token-speed integration

Approved in the conversation: use pi-token-speed footer updates in Stats for nerds.

Pi RPC emits extension_ui_request setStatus with statusKey tokenSpeed and ANSI-formatted statusText. Parse only that entry and store a separate optional, nullable responseTokenSpeed field on the active provider turn. Do not synthesize responseThroughput counters. Persist the field in server and client projections; null clears a reading, omission preserves it.

Display the extension rate for Pi with an approximation mark and explain that it is extension-reported, with provider counts or streaming estimates depending on extension configuration. Preserve Claude and Codex behavior. Bound live emissions to four per second, retaining the newest value at settlement. Ignore invalid, nonfinite or unrelated updates; a cleared status removes the reading. No extension auto-install inside the installer: document pi install npm:pi-token-speed.

Validate ANSI/placeholder parsing, active-turn RPC updates and settlement, clearing, provider isolation and projection retention. Run existing checks plus Pi parser/adapter tests and Pi typecheck. Build checked Windows bundles for the installed source commit and package without terminating T3.
