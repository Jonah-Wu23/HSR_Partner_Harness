# Third-Party Notices

## DeepSeek-Reasonix

Source: https://github.com/esengine/DeepSeek-Reasonix

`src/pair_harness/config/providers.py` contains a Python adaptation of provider host detection and reasoning-effort behavior from DeepSeek-Reasonix.

`src/pair_harness/adapters/acp/engine.py` implements an Agent Client Protocol (ACP) v1 client that launches the bundled DeepSeek-Reasonix `reasonix acp` binary as the DeepSeek coding engine boundary.

MIT License

Copyright (c) 2026 Reasonix Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## cloudflared

Source: https://github.com/cloudflare/cloudflared

cloudflared is the official tunnel client of Cloudflare, licensed under the Apache License, Version 2.0 (with a NOTICE file preserved in the upstream repository). The full license text is available at https://github.com/cloudflare/cloudflared/blob/master/LICENSE.

This project does not bundle, redistribute, or modify the cloudflared binary. When the user enables mobile remote access over the public internet (`src/pair_harness/desktop_backend/tunnel.py`), the Sidecar downloads the official cloudflared release binary for the current platform from the pinned Cloudflare GitHub release, verifies it against the official SHA256 checksum published for that release, stores it in the user's local application data directory, and manages it as a child process for Cloudflare Quick Tunnel. Tunnel traffic traverses Cloudflare's edge under Cloudflare's terms of service; this project makes no warranty for the third-party binary.
