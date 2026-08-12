# Third-Party Notices

## DeepSeek-Reasonix

Source: https://github.com/esengine/DeepSeek-Reasonix

`src/pair_harness/config/providers.py` contains a Python adaptation of provider host detection and reasoning-effort behavior from DeepSeek-Reasonix.

`src/pair_harness/adapters/acp/engine.py` implements an Agent Client Protocol (ACP) v1 client that launches the bundled DeepSeek-Reasonix `reasonix acp` binary as the DeepSeek coding engine boundary (V0.2 M3).

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

## OpenAI Codex

Source: https://github.com/openai/codex

Release builds may include the Windows-native Codex app-server distributed through
the `@openai/codex` package. Its package metadata identifies it as Apache-2.0;
the bundled native directory retains the upstream `codex-package.json` metadata.
