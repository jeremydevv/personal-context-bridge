# Build with me

Thanks for helping make personal context easier to use. This project is created by
[Jeremy](https://github.com/jeremydevv); contributions can be code, a clearer setup
step, a source adapter or a small fictional reproduction.

## Get started

1. Fork and clone the repository. Start your branch from `development`.
2. Follow the [fictional quickstart](README.md#quickstart), keeping all runtime
   state outside the checkout.
3. Install development dependencies and run the [validation commands](README.md#build-with-me).
4. Open a pull request targeting `development`. Explain the concrete problem,
   resulting behavior, checks run and any device validation still needed.

For video changes, install `.[videos]` plus FFmpeg and run
`.venv/bin/python -m pytest -q tests/saved_video` with pytest installed.

## Report a bug

Use [GitHub Issues](https://github.com/jeremydevv/personal-context-bridge/issues)
with the source/tool name, operating system, Python version, expected behavior,
actual behavior and a fictional reproduction. Remove credentials, paths that
identify people, private messages, source records and account details from logs.
Do not attach a real archive or filled runtime configuration.

## Add or change an MCP tool

- Link the tool from [the directory](docs/TOOLS.md) to its own
  `docs/tools/TOOL_NAME/README.md`.
- Document the signature, access mode, feature gates and actual setup/sync steps.
  Link the matching `docs/resources/RESOURCE/README.md` and detailed source guide.
- Keep optional feature registration separate from authentication, collection
  completion and client discovery. Explain how to verify each relevant state.
- Use fictional fixtures and record provenance/licenses for adapted code.

## Validate the behavior you change

Authentication, complete-snapshot deletion, encryption, attachment handling and
write operations need regression coverage. Check built package contents as well
as tracked files with the release/history privacy guard. Preserve permission and
scope checks. macOS/iPhone permissions, account authentication and native
persistence need device validation; CI checks synthetic behavior only.

When changing docs, verify local links and shell commands against the current CLI.
Keep the README focused on the first successful run and the resource guides
focused on permissions, collection, freshness and source-specific limitations.
