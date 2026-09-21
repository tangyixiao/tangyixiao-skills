# X source-only bridge

Use this mode only when another workflow needs a faithful local source package from a public X status URL. It performs the normal anonymous FxTwitter read, strict same-author direct-reply routing, Quote removal, and allowlisted media download, then stops before all slice and video-render stages.

## Command and outputs

```bash
"<node-bin>" "$SKILL_DIR/scripts/yichen_x_slicer.mjs" \
  --url "<x-status-url>" \
  --source-only \
  --output "<absolute-output-directory>"
```

The output directory contains exactly these source artifacts:

- `source.md`
- `assets/`
- `selected-source.json`
- `routing-audit.json`
- `source-import.json`

Do not generate HTML/PNG slices, a ZIP, `manifest.json`, `qa-report.json`, or a rendered MP4 in this mode. A pre-existing target gets a new `-run-N` sibling under the normal non-overwrite policy.

This bridge handles X Posts and verified same-author Threads, not X Articles. If any top-level node in the verified same-author chain carries an explicit Article signal, stop before writing a source package with structured error `x_article_route_required` and route the URL to the dedicated X Article materializer. Scan the verified chain before empty-node exclusion so a pure Article card with no teaser text or own media cannot disappear as `quote_only`. Never treat the status teaser as the complete Article body. Article data nested only inside an ignored Quote is not a chain-node signal.

## Markdown contract

`source.md` begins with frontmatter containing `mode`, `preserve_text: true`, `source_kind: x`, the canonical `source_url`, `title_policy: include`, and `source_import: source-import.json`. It adds no artificial title or heading.

The first selected X node is implicit. Each later selected node begins with one exclusive marker line: `Thread2:`, `Thread3:`, and so on. Marker numbering follows the selected-node sequence, so a routed `quote_only` exclusion never creates a numbering gap. Each node's own media appears after that node's cleaned text and keeps the source media order.

Treat `node.media.all` as the authoritative mixed-media order. If it is absent, a photos-only or videos-only node may use that single array, but a node containing both arrays must fail with `mixed_media_order_unavailable`; never guess by concatenating the arrays.

Fail closed instead of silently dropping any empty/non-object `media.all` entry, unknown media type, or photo/image without a URL. An empty `media.all` accompanied by non-empty `photos` or `videos` is contradictory and must fail with `media_all_inconsistent`.

If original body text outside a code fence already contains an exclusive marker-like line (`ThreadN`, `PostN`, or `PartN`, with the same optional heading/colon variants accepted by the publishing parser), append an invisible audited suffix instead of letting it become structural syntax:

```md
Thread2:<!-- yichen-literal-marker:v1:<sha256-of-exact-original-line> -->
```

The original portion remains visibly unchanged. `source-import.json.literal_marker_encoding.replacements` records the unit/status, the 1-based original body line including blank lines, the absolute `source.md` line, exact original and encoded values, and the SHA-256. A consumer must finish structural splitting first and then restore only these audited lines. Missing, extra, moved, or hash-mismatched replacements fail closed. Code-fenced examples are not encoded because the publishing parser already treats them as literal text. Fence tracking follows CommonMark semantics: retain the opener character and run length, and close only on the same character with a run at least as long as the opener and whitespace-only suffix. For example, a three-backtick Python line cannot close an outer four-backtick fence.

Photos use a local Markdown image embed. Source-only image and video-poster filenames use the format detected from downloaded bytes: JPEG is `.jpg`, PNG is `.png`, WebP is `.webp`, AVIF is `.avif`, and GIF is `.gif`. Do not preserve a misleading `.jpg` suffix when the file signature identifies another allowed type. `source-import.json` records the detected content type beside the path and hash.

A native video uses its correctly typed poster only as a Markdown preview and immediately follows it with:

```md
<!-- yichen-native-video: assets/media-N-M-source.mp4 -->
```

The marker is not publishable text. Consumers must use `source-import.json` to replace the preview with the bound native MP4 upload; they must never upload only the poster as if it were the video.

## Import manifest

`source-import.json` records source provenance, routed input type, Thread marker semantics, and ordered units. Each media record includes node-local `order`, `global_order`, `kind`, local `path`, byte count, and SHA-256. Video records also include the poster path/hash and the adjacent Markdown marker. File records bind the current hashes of `source.md`, `selected-source.json`, and `routing-audit.json`.

Full remote media URLs may remain in memory long enough to download signed resources, but persisted URL fields in `selected-source.json`, `routing-audit.json`, and render manifests remove URL userinfo, query parameters, and fragments. Delivery relies on local asset paths and hashes; credentials or signatures must never be written to the audit package.

Native video is fail-closed: URL selection, download, signature, path, and SHA-256 must all succeed before `source.md` and `source-import.json` are delivered. An MP4 failure may leave a diagnostic run directory, but it is not a usable source package.

Before and after downloading, compare every selected own-media ID and every source media URL hash with `routing-audit.json`'s ignored Quote-media ID and URL-hash sets. Any intersection is a routing collision and must stop the source package; never let an ambiguous own/Quote asset reach the consumer.

A Quote video without a poster still contributes an audit-only marker containing its real ID and any validated safe MP4 URL. The missing preview must not suppress Quote-collision detection.

## Verify and deliver

Before reporting success:

1. Confirm all five declared output entries exist and no render-only artifact was created.
2. Confirm `source.md` contains no artificial heading and later units have consecutive exclusive Thread markers.
3. Confirm every selected media record remains under its owning node and preserves local and global order, with zero ignored-Quote media collisions and an image extension/content type matching its magic bytes.
4. Confirm every audited literal-marker replacement restores the exact original line only after structural splitting.
5. Confirm `checks.hashes_match_current_files`, `checks.all_native_videos_have_mp4`, and `checks.literal_marker_encoding_verified` are true in `source-import.json`.
6. For every video, resolve its `path` inside the output directory, confirm the file has an MP4 signature, and upload that MP4 rather than its poster.

Return the source directory plus links to `source.md`, `selected-source.json`, `routing-audit.json`, and `source-import.json`. Do not claim image-slice, ZIP, QA, or finished-video deliverables.
