# Location dictionary and shared summaries

The private place dictionary turns encrypted OwnTracks observations into searchable
names, descriptions, source-linked context, and sampled visit histories. It uses
one ChatGPT-plan session and encrypted cache shared with Voice Memos. Raw source
records remain separate; generated descriptions are unverified.

## Configure

Set PERSONAL_CONTEXT_KEY_FILE to an existing private 32-byte archive key,
IPHONE_ARCHIVE_KEY_FILE to the phone archive key, IPHONE_TRAVEL_DB to the encrypted
OwnTracks database, and PERSONAL_CONTEXT_DB to the encrypted context archive.
Enable PERSONAL_CONTEXT_LOCATION_ENABLED=1 in the main and/or travel MCP process.
PERSONAL_CONTEXT_ENRICHMENT_DIR defaults to ~/.local/share/personal-context-enrichment.
Keep this directory and all real data outside source. Use the same directory/key
for the location and Voice Memos workers on a host.

Run `python -m personal_context.location_worker` every five minutes. The worker
works without model authentication; missing sign-in marks generated summaries
pending without blocking GPS indexing. It retries changed/failed work later.
No paid API-key fallback is enabled.

For optional Apple geocoding compile native/location-geocoder.swift on the Mac
with `swiftc -parse-as-library`, installing as
~/Library/Application Support/Personal Context Bridge/location-geocoder.
Set PERSONAL_CONTEXT_GEOCODE_SSH_TARGET to the existing strict SSH user@host.
Geocoding sends a bounded coordinate over SSH to Apple's system service, which
resolves addresses through Apple. It does not request the Mac's location.
Up to five new places are resolved per worker pass; successful results cache for
90 days and failures back off. An address is not proof of a particular venue.

## One shared sign-in

Run `python -m personal_context.enrichment_portal`. The default landing page is
127.0.0.1:8793; callback is always 127.0.0.1:8794. On a private network, set
PERSONAL_CONTEXT_AUTH_BIND to the exact private interface address. Do not expose
this administrative page to the public internet. The server checks Host, Origin
and CSRF, binds OAuth attempts to state/nonce/PKCE, and verifies signed identity.

For remote hosting, forward local 127.0.0.1:8794 to the same port on the host over
SSH before opening the landing page. Click Continue with ChatGPT. Consent takes
place on auth.openai.com. Authorization URLs are generated fresh; don't save an
expiring provider URL. Rotating credentials save atomically and encrypted under a
process lock. Both consumers reuse the same session and account-scoped cache.

The official plan-usage flow uses public /v1/responses, store=false, stream=true,
and account-specific model discovery. Only response.completed with schema-valid
JSON is cached. Interrupted/failed/incomplete outputs never become cache hits.
Transcription and embeddings are separate local operations, not covered by this
inference flow. Availability and usage limits depend on the signed-in account.

## Retrieval and corrections

Read-only tools: location_dictionary_status, search_visited_places,
get_visited_place, read_place_visits. The main MCP also supports existing-tool
compatibility via search_personal_context(kind="visited_place") and
get_personal_record(kind="visited_place", record_id=PLACE_ID), or
kind="location_dictionary_status" for status.

For a durable human correction:
`python -m personal_context.location_worker --correct-place PLACE_ID --title "Library" --alias "Study spot"`.
The title and aliases survive reprocessing. Exact coordinates are omitted by
default. Open the existing source event tool with an evidence ID to verify it.

Only fixes with reported accuracy up to 100m enter automatic clusters. Observed
clusters use a 100m radius; a stay needs at least two samples spanning ten minutes,
with no gap over thirty minutes. These conservative heuristics are not proof of
attendance or exact arrival/departure. Single sightings remain searchable but are
marked stay unconfirmed. GPS never establishes why someone visited a location.

Context uses explicit place aliases and bounded source evidence. Calendar/message
associations need temporal proximity and remain tentative. Neither model sign-in
nor this module grants access to ChatGPT conversation history; only authorized
archived sources may contribute. Source excerpts are untrusted data.

Freshness fields distinguish last transport receipt, last location receipt and
last GPS fix, with 24h/7d counts. A waypoint upload cannot refresh GPS freshness.
A stale fix can mean a stationary phone or delayed iOS delivery, not necessarily
a receiver failure. OwnTracks HTTP already queues unreachable-endpoint uploads;
use significant-change reporting for battery-conscious background collection.
No server can promise uninterrupted iOS GPS delivery.

## Shared Python interface

`personal_context.enrichment.EnrichmentClient.from_env().enrich_json(task,
instructions, input_data, output_schema, source_digest, source_version="1",
prompt_version="1")` returns value, model, source metadata, generated_at and
cache_hit. Inputs are bounded; callers chunk full transcripts before enrichment.
SignInRequired leaves source indexing available. EnrichmentError schedules retry.

References:
- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://owntracks.org/booklet/tech/http/
- https://owntracks.org/booklet/features/location/
