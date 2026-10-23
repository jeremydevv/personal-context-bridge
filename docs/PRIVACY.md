# Privacy, retention, and publication

Public code and private runtime state have separate locations. Setup creates
private keys, source configuration, archives and upload credentials outside the
checkout. Examples contain placeholders; tests use made-up values or publicly
published synthetic upstream fixtures. No private deployment or Git history was
copied into this distribution.

SQLCipher protects archived records, indexes, changes and summaries at rest.
Binary Messages attachments use chunked authenticated AES-GCM encryption. The
optional Saved-video archive and compressed speech/OCR search index use the same
authenticated encrypted blob format. Source MP4s retain their downloaded bytes;
frames regenerate temporarily rather than accumulating duplicate images. The
Saved collector uses only the exact Saved-list GET endpoint and no redirects;
its session remains in memory/private tmpfs and its process exits before anonymous
media processing. Browser sign-in, encrypted keys, runtime media, Saved URLs and
collection reports must never enter a release. See [Saved-video setup](INSTAGRAM-SAVED.md).

The archive key is a random 32-byte file, separate from databases and backups. Keys
are not protected from another process running as your user or from the operating
system administrator. Protect the host, use full-disk encryption, restrict access,
and keep a recovery copy of keys in a secure place separate from public code.

The Mac reads plaintext data from Apple applications. Retry spools also contain
plaintext batches until delivered. Google exports are plaintext source files.
Source records exist in memory during processing; an MCP client receives selected
plaintext tool results. Canvas Inbox messages are collected as private
conversation records and become available through Canvas Inbox/search/read tools;
connecting that MCP may send selected message content to the client/model provider.
Local storage does not prevent those results from being
sent to the client/model provider. Read that provider's data policies before
connecting sensitive sources. Obsidian uses the encryption of your own mounted
filesystem; its note history is plaintext within that mount.

The core archive retains current records, historical versions, and tombstones.
Removing a source or a record from search is not permanent erasure of its history.
Backups, attachment blobs, and device originals may hold independent copies.
There is no automatic retention purge across all those locations. If you require
permanent erasure, stop collection and account for every archive, blob, backup,
key copy and original; reinitializing one database does not erase other copies.

No telemetry service is built into this bridge. Explicit integrations include
user-configured Canvas APIs, SSH hosts, local Ollama, phone upload routes, MCP
clients, Instagram Saved collection and anonymous media downloads, and optional
OpenAI enrichment. OpenAI sign-in uses `auth.openai.com`; configured enrichment
requests send selected source input to `api.openai.com/v1/responses` with
`store=false`. Location enrichment can include place/context evidence; Voice
Memos enrichment can include transcript text. Smart Drive search sends bounded
allowed filename/folder/tag/date metadata; file excerpts are returned locally.
Encrypted local storage and caching do not make provider processing local.
Review the applicable provider policy before enabling these optional consumers.
Stdio readers need no network listener. Receiver HTTP
ports are loopback-only and still require tokens/passwords. Supply HTTPS/private
transport rather than exposing the HTTP endpoints directly.

Before contributing or publishing a fork:

- Never copy `data`, `runtime`, keys, private config, logs, exports, screenshots,
  plugin account manifests or an installed virtual environment.
- Review the exact staged files and package artifacts. `.gitignore` is a guardrail,
  not a detector for personal information in source strings or Git history.
- Run `scripts/check_release.py` and review every new test fixture for provenance.
  Use `--history` to inspect every reachable Git blob, including deleted files;
  the checker always checks the Git index as well as working files and packages.
  Optionally provide a local denylist through `PERSONAL_CONTEXT_PRIVATE_MARKERS`
  (newline-separated strings); the checker reports paths/line numbers, not values.
- Distribution archive ownership must be neutral, including header metadata;
  content scanning alone cannot detect an identifying build account.
- Use synthetic examples, a public-safe Git author identity, and a fresh history
  when extracting private software. Existing commits can retain deleted files.
- GitHub secret scanning cannot identify every name, conversation, location or
  health record. Human source review remains necessary.

If credentials are ever exposed, revoke/rotate them before history cleanup.
GitHub's [sensitive-data removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
explains why deleting the latest file does not remove older commits or clones.
