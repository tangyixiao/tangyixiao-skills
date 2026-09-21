#!/usr/bin/env node

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { renderVideos, VIDEO_PROFILE } from './silent_video.mjs';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.dirname(SCRIPT_DIR);
const POSTER_CSS_PATH = path.join(SKILL_DIR, 'assets', 'poster.css');
const CANVAS = Object.freeze({ width: 1080, height: 1440, ratio: '3:4' });
const X_STATUS_HOSTS = new Set(['x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com']);
const X_IMAGE_HOSTS = new Set(['pbs.twimg.com', 'video.twimg.com']);
const X_VIDEO_HOSTS = new Set(['video.twimg.com']);
const SOURCE_MARKER_LINE_RE = /^\s*(?:#{1,6}\s*)?(?:thread|post|part)\s*\d+\s*:?\s*$/iu;
const SOURCE_FENCE_CANDIDATE_RE = /^( {0,3})(`{3,}|~{3,})(.*)$/u;
const LITERAL_MARKER_ENCODED_RE = /<!--\s*yichen-literal-marker:v1:[0-9a-f]{64}\s*-->\s*$/iu;
const LITERAL_MARKER_ENCODING_VERSION = 'yichen-literal-marker/v1';

export const DEFAULT_TEMPLATE = 'sunset';
export const TEMPLATES = Object.freeze([
  { id: 'sunset', name: '落日琥珀版', description: '金黄、琥珀橙、暖米白与深棕' },
  { id: 'editorial', name: '暖白编辑版', description: '暖纸、墨蓝细线与克制留白' },
  { id: 'data', name: '冷白数据版', description: '冷白底、深蓝数字与清晰网格' },
  { id: 'fire', name: '火橙冲击版', description: '火橙满版、近黑粗线与强开场' },
  { id: 'yellow', name: '黄靛展览版', description: '明黄块面、靛蓝文字与展览感' },
  { id: 'mono', name: '黑白台账版', description: '象牙纸、黑墨与硬边框' },
  { id: 'night', name: '黑粉夜刊版', description: '近黑背景与热粉强调' },
  { id: 'ribbon', name: '奶油彩带版', description: '奶油纸、多色斜带与复古活力' },
  { id: 'cobalt', name: '钴蓝方格版', description: '方格纸、钴蓝线与证据索引感' },
  { id: 'news', name: '红黑报纸版', description: '米白新闻纸、红黑对比与粗边框' },
  { id: 'minimal', name: '极简留白版', description: '纯白、浅灰与最少装饰' }
]);

const TEMPLATE_BY_ID = new Map(TEMPLATES.map((template) => [template.id, template]));

export function normalizeText(value) {
  return String(value ?? '').replace(/\s+/gu, ' ').trim();
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function sha256Buffer(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function sha256File(file) {
  return sha256Buffer(fs.readFileSync(file));
}

function uniqueStrings(values) {
  return [...new Set(values.filter(Boolean).map(String))];
}

export function sanitizeRemoteUrlForPersistence(value) {
  let parsed;
  try {
    parsed = new URL(String(value));
  } catch {
    const error = new Error('persisted_remote_url_invalid');
    error.code = 'persisted_remote_url_invalid';
    throw error;
  }
  if (!['https:', 'http:'].includes(parsed.protocol)) {
    const error = new Error(`persisted_remote_url_protocol_rejected:${parsed.protocol}`);
    error.code = 'persisted_remote_url_protocol_rejected';
    error.protocol = parsed.protocol;
    throw error;
  }
  parsed.username = '';
  parsed.password = '';
  parsed.search = '';
  parsed.hash = '';
  return parsed.href;
}

function persistedRemoteUrlField(key) {
  return key === 'url' || key === 'endpoint' || key.endsWith('_url');
}

export function sanitizeRemoteUrlsForPersistence(value, key = '') {
  if (Array.isArray(value)) return value.map((item) => sanitizeRemoteUrlsForPersistence(item));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [
      childKey,
      sanitizeRemoteUrlsForPersistence(childValue, childKey)
    ]));
  }
  if (typeof value === 'string' && value && persistedRemoteUrlField(key)) {
    return sanitizeRemoteUrlForPersistence(value);
  }
  return value;
}

export function parseStatusUrl(value) {
  let parsed;
  try {
    parsed = new URL(String(value));
  } catch {
    throw new Error('请输入有效的 X status 链接');
  }
  const host = parsed.hostname.toLowerCase().replace(/^www\./u, '');
  if (!['x.com', 'twitter.com', 'mobile.twitter.com'].includes(host)) {
    throw new Error('仅支持 x.com 或 twitter.com 的 status 链接');
  }
  const systemMatch = parsed.pathname.match(/^\/i\/(?:web\/)?status\/(\d+)(?:\/.*)?$/u);
  const handleMatch = systemMatch ? null : parsed.pathname.match(/^\/([^/]+)\/status\/(\d+)(?:\/.*)?$/u);
  if (!handleMatch && !systemMatch) throw new Error('链接中缺少有效的 status ID');
  const id = handleMatch ? handleMatch[2] : systemMatch[1];
  const handle = handleMatch ? decodeURIComponent(handleMatch[1]) : null;
  return {
    id,
    handle,
    canonicalUrl: handle ? `https://x.com/${handle}/status/${id}` : `https://x.com/i/web/status/${id}`
  };
}

export function parseArgs(argv) {
  const options = {
    url: null,
    output: null,
    template: DEFAULT_TEMPLATE,
    sourceJson: null,
    sourceOnly: false,
    video: true,
    listTemplates: false,
    help: false
  };
  let explicitVideo = false;
  let explicitImagesOnly = false;
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--url') options.url = argv[++index];
    else if (arg === '--output') options.output = argv[++index];
    else if (arg === '--template') options.template = argv[++index];
    else if (arg === '--source-json') options.sourceJson = argv[++index];
    else if (arg === '--source-only') options.sourceOnly = true;
    else if (arg === '--video') explicitVideo = true;
    else if (arg === '--images-only') explicitImagesOnly = true;
    else if (arg === '--list-templates') options.listTemplates = true;
    else if (arg === '--help' || arg === '-h') options.help = true;
    else throw new Error(`未知参数：${arg}`);
  }
  for (const [name, value] of Object.entries({ '--url': options.url, '--output': options.output, '--template': options.template, '--source-json': options.sourceJson })) {
    if (value === undefined) throw new Error(`${name} 缺少参数值`);
  }
  if (options.template !== 'all' && !TEMPLATE_BY_ID.has(options.template)) {
    throw new Error(`未知模板：${options.template}`);
  }
  if (explicitVideo && explicitImagesOnly) throw new Error('不能同时使用 --video 与 --images-only');
  if (options.sourceOnly && (explicitVideo || explicitImagesOnly)) {
    throw new Error('--source-only 不生成切片成片，不能与 --video 或 --images-only 同时使用');
  }
  options.video = !explicitImagesOnly;
  return options;
}

function printHelp() {
  process.stdout.write([
    '用法：',
    '  node yichen_x_slicer.mjs --url <X链接> [--template sunset] [--images-only] [--output <目录>]',
    '  node yichen_x_slicer.mjs --url <X链接> --source-json <文件> --output <目录>',
    '  node yichen_x_slicer.mjs --url <X链接> --source-only --output <目录>',
    '  node yichen_x_slicer.mjs --list-templates',
    '',
    '默认模板：sunset（落日琥珀版）',
    '默认产物：图片组、图片 ZIP 和固定阅读节奏视频；原视频有音轨时保留原声',
    '--images-only：明确只生成图片和图片 ZIP，不生成视频',
    '--source-only：只生成 source.md、assets 与来源审计，不生成切片、ZIP 或成片',
    ''
  ].join('\n'));
}

export function listTemplatesText() {
  return TEMPLATES.map((template) => [
    template.id,
    template.name,
    template.id === DEFAULT_TEMPLATE ? '默认' : '',
    template.description
  ].filter(Boolean).join('\t')).join('\n') + '\n';
}

function authorKey(author) {
  const id = author?.id != null ? String(author.id).trim() : '';
  if (id) return `id:${id}`;
  const handle = String(author?.screen_name ?? author?.handle ?? '').trim().toLowerCase();
  return handle ? `handle:${handle}` : null;
}

function authorHandle(author) {
  return String(author?.screen_name ?? author?.handle ?? '');
}

function nodeReplyStatus(node) {
  const replying = node?.replying_to;
  if (!replying) return null;
  if (typeof replying === 'string' || typeof replying === 'number') return String(replying);
  return replying.status != null ? String(replying.status) : null;
}

function nodeReplyHandle(node) {
  const replying = node?.replying_to;
  if (!replying || typeof replying !== 'object') return '';
  return String(replying.screen_name ?? replying.handle ?? '');
}

function nodeCreatedTime(node) {
  const unix = Number(node?.created_timestamp);
  if (Number.isFinite(unix) && unix > 0) return unix * 1000;
  const parsed = Date.parse(String(node?.created_at ?? ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function isStrictlyLater(child, parent) {
  const childTime = nodeCreatedTime(child);
  const parentTime = nodeCreatedTime(parent);
  if (childTime != null && parentTime != null) {
    if (childTime > parentTime) return true;
    if (childTime < parentTime) return false;
  }
  try {
    return BigInt(String(child.id)) > BigInt(String(parent.id));
  } catch {
    return false;
  }
}

function statusIdFromUrl(value) {
  try {
    const parsed = new URL(String(value));
    if (!X_STATUS_HOSTS.has(parsed.hostname.toLowerCase())) return null;
    const segments = parsed.pathname.split('/').filter(Boolean);
    const statusAt = segments.findIndex((segment) => segment.toLowerCase() === 'status');
    const id = statusAt >= 0 ? segments[statusAt + 1] : null;
    return /^\d+$/u.test(String(id ?? '')) ? String(id) : null;
  } catch {
    return null;
  }
}

function quoteId(node) {
  if (!node?.quote) return null;
  if (node.quote.id != null) return String(node.quote.id);
  for (const value of [node.quote.url, node.quote.tweet_url, node.quote.status_url]) {
    const extracted = statusIdFromUrl(value);
    if (extracted) return extracted;
  }
  const error = new Error(`quote_identity_missing:${String(node?.id ?? 'unknown')}`);
  error.code = 'quote_identity_missing';
  error.statusId = node?.id != null ? String(node.id) : null;
  throw error;
}

function assertStatusId(value, label = 'status ID') {
  const id = String(value ?? '');
  if (!/^\d+$/u.test(id)) throw new Error(`${label} 不是有效数字 ID`);
  return id;
}

function isStatusUrlForId(value, id) {
  try {
    const parsed = new URL(String(value));
    if (!X_STATUS_HOSTS.has(parsed.hostname.toLowerCase())) return false;
    const segments = parsed.pathname.split('/').filter(Boolean);
    return segments.some((segment, index) => segment.toLowerCase() === 'status' && segments[index + 1] === String(id));
  } catch {
    return false;
  }
}

function topLevelUrlEntities(node) {
  const groups = [node?.entities?.urls, node?.entities?.url?.urls, node?.urls];
  return groups.flatMap((group) => Array.isArray(group) ? group : []).filter((item) => item && typeof item === 'object');
}

export function removeQuoteStatusUrl(text, id, node = null) {
  const source = String(text ?? '').replace(/\r\n?/gu, '\n');
  if (!id) return source.trim();
  const quoteStatusId = assertStatusId(id, 'Quote ID');
  const removableShortUrls = new Set();
  const knownNonQuoteShortUrls = new Set();
  for (const entity of topLevelUrlEntities(node)) {
    const shortUrl = String(entity.url ?? entity.short_url ?? '').trim();
    const expanded = String(entity.expanded_url ?? entity.expandedUrl ?? entity.unwound_url ?? entity.display_url ?? '').trim();
    if (!/^https?:\/\/t\.co\//iu.test(shortUrl)) continue;
    if (isStatusUrlForId(expanded, quoteStatusId)) removableShortUrls.add(shortUrl);
    else if (expanded) knownNonQuoteShortUrls.add(shortUrl);
  }
  const urlPattern = /https?:\/\/[A-Za-z0-9._~:\/?#\[\]@!$&'()*+,;=%-]+/giu;
  const cleaned = source.replace(urlPattern, (matched) => {
    const trailing = matched.match(/[),.;!?，。；！？]+$/u)?.[0] ?? '';
    const candidate = trailing ? matched.slice(0, -trailing.length) : matched;
    if (isStatusUrlForId(candidate, quoteStatusId) || removableShortUrls.has(candidate)) return trailing;
    return matched;
  });
  const unresolvedShortUrls = cleaned.match(/https?:\/\/t\.co\/[A-Za-z0-9._~:\/?#\[\]@!$&'()*+,;=%-]+/giu) ?? [];
  if (unresolvedShortUrls.some((url) => !knownNonQuoteShortUrls.has(url.replace(/[),.;!?，。；！？]+$/u, '')))) {
    const error = new Error(`unresolved_quote_short_url:${quoteStatusId}`);
    error.code = 'unresolved_quote_short_url';
    error.quoteStatusId = quoteStatusId;
    throw error;
  }
  return cleaned
    .replace(/[ \t]+\n/gu, '\n')
    .replace(/\n[ \t]+/gu, '\n')
    .replace(/\n{3,}/gu, '\n\n')
    .trim();
}

function videoVariantDimensions(value) {
  try {
    const pathname = new URL(String(value)).pathname;
    const match = pathname.match(/\/(\d+)x(\d+)\//u);
    if (!match) return { width: null, height: null, area: 0 };
    const width = Number(match[1]);
    const height = Number(match[2]);
    return { width, height, area: width * height };
  } catch {
    return { width: null, height: null, area: 0 };
  }
}

function safeNativeVideoUrl(value) {
  try {
    const parsed = new URL(String(value));
    return parsed.protocol === 'https:'
      && parsed.hostname.toLowerCase() === 'video.twimg.com'
      && !parsed.username
      && !parsed.password;
  } catch {
    return false;
  }
}

export function selectNativeVideoVariant(item) {
  const candidates = (Array.isArray(item?.formats) ? item.formats : [])
    .filter((format) => {
      if (!format?.url || !safeNativeVideoUrl(format.url)) return false;
      const container = String(format.container ?? '').toLowerCase();
      if (container === 'mp4') return true;
      try {
        return new URL(String(format.url)).pathname.toLowerCase().endsWith('.mp4');
      } catch {
        return false;
      }
    })
    .map((format) => {
      const dimensions = videoVariantDimensions(format.url);
      const bitrate = Number(format.bitrate);
      return {
        url: String(format.url),
        container: 'mp4',
        codec: format.codec ? String(format.codec) : null,
        bitrate: Number.isFinite(bitrate) && bitrate >= 0 ? bitrate : null,
        width: dimensions.width,
        height: dimensions.height,
        area: dimensions.area
      };
    })
    .sort((left, right) => (
      (right.bitrate ?? -1) - (left.bitrate ?? -1)
      || right.area - left.area
      || right.url.localeCompare(left.url)
    ));
  if (candidates.length) {
    const canvasMatched = candidates
      .filter((candidate) => Math.max(candidate.width ?? 0, candidate.height ?? 0) >= 1080)
      .sort((left, right) => (
        (left.bitrate ?? Number.MAX_SAFE_INTEGER) - (right.bitrate ?? Number.MAX_SAFE_INTEGER)
        || left.area - right.area
        || left.url.localeCompare(right.url)
      ));
    const chosen = canvasMatched[0] ?? candidates[0];
    const { area: ignoredArea, ...selected } = chosen;
    return {
      ...selected,
      selection: canvasMatched.length ? 'canvas_matched_mp4' : 'highest_available_mp4'
    };
  }
  if (!item?.url || String(item?.format ?? '').toLowerCase() !== 'video/mp4' || !safeNativeVideoUrl(item.url)) return null;
  const dimensions = videoVariantDimensions(item.url);
  return {
    url: String(item.url),
    container: 'mp4',
    codec: null,
    bitrate: null,
    width: dimensions.width || Number(item?.width ?? 0) || null,
    height: dimensions.height || Number(item?.height ?? 0) || null,
    selection: 'validated_top_level_mp4_fallback'
  };
}

export function ownMedia(node, { strictVideoPoster = true } = {}) {
  const orderedMedia = node?.media?.all;
  const photos = Array.isArray(node?.media?.photos) ? node.media.photos : [];
  const videos = Array.isArray(node?.media?.videos) ? node.media.videos : [];
  const statusId = String(node?.id ?? 'unknown');
  if (Array.isArray(orderedMedia) && orderedMedia.length === 0 && (photos.length || videos.length)) {
    const error = new Error(`media_all_inconsistent:${statusId}:empty_all_with_fallback_items`);
    error.code = 'media_all_inconsistent';
    error.statusId = statusId;
    error.reason = 'empty_all_with_fallback_items';
    error.photoCount = photos.length;
    error.videoCount = videos.length;
    throw error;
  }
  if (!Array.isArray(orderedMedia) && photos.length && videos.length) {
    const error = new Error(`mixed_media_order_unavailable:${statusId}`);
    error.code = 'mixed_media_order_unavailable';
    error.statusId = statusId;
    error.photoCount = photos.length;
    error.videoCount = videos.length;
    throw error;
  }
  const media = Array.isArray(orderedMedia)
    ? orderedMedia
    : photos.length ? photos : videos;
  const mediaSource = Array.isArray(orderedMedia) ? 'all' : photos.length ? 'photos' : 'videos';
  const seen = new Set();
  const selected = [];
  for (let mediaIndex = 0; mediaIndex < media.length; mediaIndex += 1) {
    const item = media[mediaIndex];
    if (!item || typeof item !== 'object' || Array.isArray(item) || Object.keys(item).length === 0) {
      const error = new Error(`media_entry_invalid:${statusId}:${mediaSource}:${mediaIndex}`);
      error.code = 'media_entry_invalid';
      error.statusId = statusId;
      error.mediaSource = mediaSource;
      error.mediaIndex = mediaIndex;
      throw error;
    }
    const type = String(item.type ?? '').trim().toLowerCase();
    const isImage = type === 'photo' || type === 'image';
    const isVideo = ['video', 'gif', 'animated_gif'].includes(type);
    if (!isImage && !isVideo) {
      const error = new Error(`media_type_unknown:${statusId}:${mediaSource}:${mediaIndex}:${type || 'missing'}`);
      error.code = 'media_type_unknown';
      error.statusId = statusId;
      error.mediaSource = mediaSource;
      error.mediaIndex = mediaIndex;
      error.mediaId = item.id != null ? String(item.id) : null;
      error.mediaType = type || null;
      throw error;
    }
    const sourceUrl = isImage ? item?.url : isVideo ? item?.thumbnail_url : null;
    const variant = isVideo ? selectNativeVideoVariant(item) : null;
    if (typeof sourceUrl !== 'string' || !sourceUrl.trim()) {
      if (isImage) {
        const error = new Error(`media_image_url_missing:${statusId}:${mediaSource}:${mediaIndex}`);
        error.code = 'media_image_url_missing';
        error.statusId = statusId;
        error.mediaSource = mediaSource;
        error.mediaIndex = mediaIndex;
        error.mediaId = item.id != null ? String(item.id) : null;
        error.mediaType = type;
        throw error;
      }
      if (strictVideoPoster) {
        const error = new Error(`media_video_poster_missing:${statusId}:${mediaSource}:${mediaIndex}`);
        error.code = 'media_video_poster_missing';
        error.statusId = statusId;
        error.mediaSource = mediaSource;
        error.mediaIndex = mediaIndex;
        error.mediaId = item.id != null ? String(item.id) : null;
        error.mediaType = type;
        throw error;
      }
      const auditId = item.id != null && String(item.id).trim() ? String(item.id) : null;
      const auditKey = auditId ?? variant?.url ?? null;
      if (!auditKey) {
        const error = new Error(`media_video_audit_marker_unavailable:${statusId}:${mediaSource}:${mediaIndex}`);
        error.code = 'media_video_audit_marker_unavailable';
        error.statusId = statusId;
        error.mediaSource = mediaSource;
        error.mediaIndex = mediaIndex;
        error.mediaType = type;
        throw error;
      }
      if (seen.has(auditKey)) continue;
      seen.add(auditKey);
      const duration = Number(item?.duration);
      selected.push({
        id: auditId,
        type: 'video',
        url: null,
        poster_url: null,
        width: null,
        height: null,
        video_url: variant?.url ?? null,
        video_duration_seconds: Number.isFinite(duration) && duration > 0 ? duration : null,
        video_variant: variant,
        audit_only: true
      });
      continue;
    }
    const key = String(item?.id ?? sourceUrl);
    if (seen.has(key)) continue;
    seen.add(key);
    if (isImage) {
      selected.push({
        id: item?.id != null ? String(item.id) : key,
        type: 'photo',
        url: String(sourceUrl),
        width: Number(item?.width ?? item?.original_info?.width ?? 0) || null,
        height: Number(item?.height ?? item?.original_info?.height ?? 0) || null
      });
      continue;
    }
    const duration = Number(item?.duration);
    selected.push({
      id: item?.id != null ? String(item.id) : key,
      type: 'video',
      url: String(sourceUrl),
      poster_url: String(sourceUrl),
      width: null,
      height: null,
      video_url: variant?.url ?? null,
      video_duration_seconds: Number.isFinite(duration) && duration > 0 ? duration : null,
      video_variant: variant
    });
  }
  return selected;
}

function quoteMediaMarkers(nodes) {
  const ids = [];
  const urlHashes = [];
  for (const node of nodes) {
    for (const media of ownMedia(node?.quote, { strictVideoPoster: false })) {
      if (media.id != null) ids.push(String(media.id));
      if (media.url) urlHashes.push(sha256Buffer(Buffer.from(String(media.url))));
      if (media.video_url) urlHashes.push(sha256Buffer(Buffer.from(String(media.video_url))));
    }
  }
  return {
    ids: uniqueStrings(ids),
    urlHashes: uniqueStrings(urlHashes)
  };
}

export function quoteMediaCollisionAudit(mediaItems, routingAudit) {
  const ignoredIds = new Set((routingAudit?.ignored_quote_media_ids ?? []).map(String));
  const ignoredUrlHashes = new Set((routingAudit?.ignored_quote_media_url_sha256 ?? []).map(String));
  const collisions = [];
  for (let index = 0; index < mediaItems.length; index += 1) {
    const media = mediaItems[index];
    const mediaId = String(media?.id ?? '');
    const urlHashes = uniqueStrings([media?.url, media?.poster_url, media?.video_url])
      .map((url) => sha256Buffer(Buffer.from(url)));
    const matchingUrlHashes = urlHashes.filter((urlHash) => ignoredUrlHashes.has(urlHash));
    const idCollision = Boolean(mediaId && ignoredIds.has(mediaId));
    if (idCollision || matchingUrlHashes.length) {
      collisions.push({
        index,
        media_id: mediaId || null,
        id_collision: idCollision,
        url_hash_collisions: matchingUrlHashes
      });
    }
  }
  return collisions;
}

export function assertNoQuoteMediaCollisions(mediaItems, routingAudit, phase = 'unknown') {
  const collisions = quoteMediaCollisionAudit(mediaItems, routingAudit);
  if (collisions.length) {
    const error = new Error(`quote_media_collision:${phase}:${collisions.length}`);
    error.code = 'quote_media_collision';
    error.phase = phase;
    error.collisions = collisions;
    throw error;
  }
  return { phase, collision_count: 0 };
}

function selectedNodeArticleSignalFields(node) {
  const fields = [];
  const explicitValues = {
    article: node?.article,
    article_id: node?.article_id,
    article_url: node?.article_url,
    article_data: node?.article_data,
    article_preview: node?.article_preview
  };
  for (const [field, value] of Object.entries(explicitValues)) {
    if (value == null || value === false || value === '') continue;
    fields.push(field);
  }
  if (node?.is_article === true) fields.push('is_article');
  for (const field of ['content_type', 'contentType', 'kind', 'type']) {
    const value = String(node?.[field] ?? '').trim().toLowerCase();
    if (value === 'x_article' || value === 'article') fields.push(field);
  }
  const cardType = String(node?.card?.type ?? '').trim().toLowerCase();
  if (cardType === 'x_article' || cardType === 'article') fields.push('card.type');
  return uniqueStrings(fields);
}

export function assertNoSelectedArticleSignals(route) {
  const verifiedNodes = Array.isArray(route?.verifiedChain)
    ? route.verifiedChain
    : (route?.selectedNodes ?? []).map(({ node }) => node);
  const articleNodes = verifiedNodes
    .map((node) => ({
      status_id: String(node?.id ?? 'unknown'),
      signal_fields: selectedNodeArticleSignalFields(node)
    }))
    .filter(({ signal_fields }) => signal_fields.length > 0);
  if (articleNodes.length) {
    const error = new Error(`x_article_route_required:${articleNodes.map(({ status_id }) => status_id).join(',')}`);
    error.code = 'x_article_route_required';
    error.statusIds = articleNodes.map(({ status_id }) => status_id);
    error.articleNodes = articleNodes;
    error.requiredMaterializer = 'x_article';
    throw error;
  }
  return { article_signal_count: 0 };
}

export function normalizeSourcePayload(payload, requestedId) {
  if (!payload || typeof payload !== 'object') throw new Error('源数据不是有效对象');
  let focal = null;
  let thread = [];
  let backend = 'source-json';
  let retrievedAt = new Date().toISOString();

  if (payload.status && typeof payload.status === 'object' && !Array.isArray(payload.status)) {
    focal = payload.status;
    thread = Array.isArray(payload.thread) ? payload.thread : [];
    backend = 'fxtwitter-public-thread';
  } else if (payload.content && typeof payload.content === 'object') {
    focal = payload.content;
    thread = Array.isArray(payload.thread) ? payload.thread : [];
    backend = payload.route?.backend_used ?? backend;
    retrievedAt = payload.route?.retrieved_at ?? retrievedAt;
  } else if (payload.id != null) {
    focal = payload;
    thread = [];
  }

  const candidates = [];
  const seen = new Set();
  for (const node of [focal, ...thread]) {
    if (!node || node.id == null) continue;
    const id = assertStatusId(node.id, '帖子 ID');
    const replyId = nodeReplyStatus(node);
    if (replyId != null) assertStatusId(replyId, '回复目标 ID');
    const nodeQuoteId = quoteId(node);
    if (nodeQuoteId != null) assertStatusId(nodeQuoteId, 'Quote ID');
    if (seen.has(id)) continue;
    seen.add(id);
    candidates.push(node);
  }
  const requested = candidates.find((node) => String(node.id) === String(requestedId));
  if (requested) focal = requested;
  if (!focal || String(focal.id) !== String(requestedId)) {
    throw new Error(`源数据不包含链接所指 status：${requestedId}`);
  }
  if (!focal.author || !authorKey(focal.author)) throw new Error('源帖子缺少可核验的作者身份');
  return { focal, candidates, backend, retrievedAt, raw: payload };
}

export function routeThread(normalized, endpoint = null) {
  const { focal, candidates } = normalized;
  const rootAuthorKey = authorKey(focal.author);
  const rootHandle = authorHandle(focal.author).toLowerCase();
  const candidateById = new Map(candidates.map((node) => [String(node.id), node]));
  let discoveredRoot = focal;
  const backwardIds = [String(focal.id)];
  while (nodeReplyStatus(discoveredRoot)) {
    const parentId = nodeReplyStatus(discoveredRoot);
    const parent = candidateById.get(parentId);
    if (!parent) {
      if (nodeReplyHandle(discoveredRoot).toLowerCase() === rootHandle || !nodeReplyHandle(discoveredRoot)) {
        const error = new Error(`thread_parent_missing:${parentId}`);
        error.code = 'thread_parent_missing';
        error.parentStatusId = parentId;
        error.childStatusId = String(discoveredRoot.id);
        throw error;
      }
      break;
    }
    if (authorKey(parent.author) !== rootAuthorKey) break;
    if (!isStrictlyLater(discoveredRoot, parent)) {
      const error = new Error(`thread_parent_invalid_time:${parentId}`);
      error.code = 'thread_parent_invalid_time';
      error.parentStatusId = parentId;
      error.childStatusId = String(discoveredRoot.id);
      throw error;
    }
    discoveredRoot = parent;
    backwardIds.unshift(String(parent.id));
  }
  const discoveredParent = nodeReplyStatus(discoveredRoot) ? candidateById.get(nodeReplyStatus(discoveredRoot)) : null;
  const externalRootReply = Boolean(
    nodeReplyStatus(discoveredRoot)
    && (
      (discoveredParent && authorKey(discoveredParent.author) !== rootAuthorKey)
      || (!discoveredParent && nodeReplyHandle(discoveredRoot) && nodeReplyHandle(discoveredRoot).toLowerCase() !== rootHandle)
    )
  );
  const verifiedChain = [externalRootReply ? focal : discoveredRoot];
  const excludedOtherAuthor = [];
  const excludedNotLater = [];

  if (!externalRootReply) {
    let parent = discoveredRoot;
    while (true) {
      const directChildren = candidates.filter((node) => String(node.id) !== String(parent.id) && nodeReplyStatus(node) === String(parent.id));
      const sameAuthor = directChildren.filter((node) => authorKey(node.author) === rootAuthorKey);
      excludedOtherAuthor.push(...directChildren.filter((node) => authorKey(node.author) !== rootAuthorKey).map((node) => String(node.id)));
      const later = sameAuthor.filter((node) => isStrictlyLater(node, parent));
      excludedNotLater.push(...sameAuthor.filter((node) => !isStrictlyLater(node, parent)).map((node) => String(node.id)));
      if (later.length > 1) {
        const error = new Error(`ambiguous_self_reply_branch:${String(parent.id)}`);
        error.code = 'ambiguous_self_reply_branch';
        error.parentStatusId = String(parent.id);
        error.childStatusIds = later.map((node) => String(node.id));
        throw error;
      }
      if (later.length === 0) break;
      parent = later[0];
      verifiedChain.push(parent);
    }
  }

  const ignoredQuoteIds = uniqueStrings(candidates.map(quoteId));
  const ignoredQuoteMedia = quoteMediaMarkers(candidates);
  const excludedStatuses = [];
  const selectedNodes = [];
  for (const node of verifiedChain) {
    const ignoredQuoteId = quoteId(node);
    const cleanedText = removeQuoteStatusUrl(node.text, ignoredQuoteId, node);
    const media = ownMedia(node);
    if (!normalizeText(cleanedText) && media.length === 0) {
      excludedStatuses.push({
        id: String(node.id),
        reason: 'quote_only',
        ignored_quote_id: ignoredQuoteId
      });
      continue;
    }
    selectedNodes.push({ node, cleanedText, media });
  }
  for (const selected of selectedNodes) {
    for (const media of selected.media) {
      assertAllowedHttpsUrl(media.url, X_IMAGE_HOSTS, 'X 自身媒体封面');
      if (media.type === 'video' && media.video_url) assertAllowedHttpsUrl(media.video_url, X_VIDEO_HOSTS, 'X 原生视频');
    }
  }

  const isThread = verifiedChain.length > 1;
  const hasQuote = verifiedChain.some((node) => Boolean(quoteId(node)));
  const resolvedInputType = isThread
    ? hasQuote ? 'thread_with_quote' : 'thread'
    : hasQuote ? 'quote_post' : 'post';

  const audit = {
    version: 'x-thread-routing-audit/v1',
    checked_at: new Date().toISOString(),
    backend: normalized.backend,
    endpoint,
    focal_status_id: String(focal.id),
    thread_root_status_id: String(discoveredRoot.id),
    backward_verified_status_ids: backwardIds,
    resolved_input_type: resolvedInputType,
    focal_is_external_reply: externalRootReply,
    thread_nodes_seen: candidates.length,
    verified_chain_status_ids: verifiedChain.map((node) => String(node.id)),
    selected_status_ids: selectedNodes.map(({ node }) => String(node.id)),
    excluded_statuses: excludedStatuses,
    excluded_other_author_reply_ids: uniqueStrings(excludedOtherAuthor),
    excluded_not_later_ids: uniqueStrings(excludedNotLater),
    ignored_quote_ids: ignoredQuoteIds,
    ignored_quote_media_ids: ignoredQuoteMedia.ids,
    ignored_quote_media_url_sha256: ignoredQuoteMedia.urlHashes,
    ambiguous_self_reply_branch: false
  };
  return { focal, verifiedChain, selectedNodes, resolvedInputType, audit };
}

function boundaryCandidates(text, start, end) {
  const candidates = [];
  const patterns = [
    { regex: /\n\n/gu, penalty: 0 },
    { regex: /\n/gu, penalty: 8 },
    { regex: /[。！？!?；;]/gu, penalty: 12 },
    { regex: /[，、,:：]/gu, penalty: 24 },
    { regex: /\s/gu, penalty: 34 }
  ];
  for (const { regex, penalty } of patterns) {
    regex.lastIndex = 0;
    let match;
    while ((match = regex.exec(text))) {
      const position = match.index + match[0].length;
      if (position >= start && position <= end) candidates.push({ position, penalty });
    }
  }
  return candidates;
}

const GRAPHEME_SEGMENTER = typeof Intl.Segmenter === 'function'
  ? new Intl.Segmenter('zh-CN', { granularity: 'grapheme' })
  : null;

function graphemeSegments(value) {
  const text = String(value);
  return GRAPHEME_SEGMENTER
    ? Array.from(GRAPHEME_SEGMENTER.segment(text), ({ segment }) => segment)
    : Array.from(text);
}

function safeCutIndex(text, requested) {
  const maximum = Math.max(0, Math.min(Number(requested) || 0, text.length));
  if (maximum === 0 || maximum === text.length) return maximum;
  let consumed = 0;
  for (const segment of graphemeSegments(text)) {
    const next = consumed + segment.length;
    if (next > maximum) return consumed || next;
    consumed = next;
  }
  return consumed;
}

function estimatedRenderedLines(value, lineWidth = 22) {
  return String(value).split('\n').reduce((total, line) => {
    return total + Math.max(1, Math.ceil(visualWidth(line) / lineWidth));
  }, 0);
}

function maximumFittingCut(text, maximumCharacters, maximumLines) {
  let consumed = 0;
  let best = 0;
  for (const segment of graphemeSegments(text)) {
    const next = consumed + segment.length;
    if (next > maximumCharacters || next >= text.length) break;
    if (estimatedRenderedLines(text.slice(0, next)) > maximumLines) break;
    best = next;
    consumed = next;
  }
  return best;
}

function chooseBoundary(text, ideal, minimum, maximum) {
  const candidates = boundaryCandidates(text, minimum, Math.min(maximum, text.length - 1));
  if (!candidates.length) return safeCutIndex(text, Math.min(ideal, maximum, text.length - 1));
  candidates.sort((left, right) => {
    const leftScore = Math.abs(left.position - ideal) + left.penalty;
    const rightScore = Math.abs(right.position - ideal) + right.penalty;
    return leftScore - rightScore || right.position - left.position;
  });
  return candidates[0].position;
}

export function splitText(value, { target = 320, maximum = 370, minimum = 150, targetLines = 15, maximumLines = 18 } = {}) {
  const source = String(value ?? '').replace(/\r\n?/gu, '\n').trim();
  if (!source) return [];
  const needsSplit = (text) => text.length > maximum || estimatedRenderedLines(text) > maximumLines;
  if (!needsSplit(source)) return [source];
  const slices = [];
  let remaining = source;
  while (needsSplit(remaining)) {
    const renderedLines = estimatedRenderedLines(remaining);
    const desiredFrames = Math.max(2, Math.ceil(remaining.length / target), Math.ceil(renderedLines / targetLines));
    const hardCut = maximumFittingCut(remaining, maximum, maximumLines);
    if (!hardCut) throw new Error('正文自动拆帧失败：单个字形无法放入安全区域');
    const balanced = safeCutIndex(remaining, Math.round(remaining.length / desiredFrames));
    const ideal = Math.max(1, Math.min(hardCut, balanced || hardCut));
    const adaptiveMinimum = Math.min(minimum, Math.max(1, Math.floor(ideal / 2)));
    const lower = Math.max(1, safeCutIndex(remaining, Math.max(adaptiveMinimum, ideal - 82)));
    const cut = chooseBoundary(remaining, ideal, lower, hardCut);
    const slice = remaining.slice(0, cut);
    if (!slice.trim()) throw new Error('正文自动拆帧失败：生成了空切片');
    slices.push(slice);
    remaining = remaining.slice(cut);
  }
  if (remaining) slices.push(remaining);
  if (slices.join('') !== source) {
    throw new Error('正文自动拆帧未完整覆盖原文');
  }
  return slices;
}

function visualWidth(value) {
  let total = 0;
  for (const character of graphemeSegments(value)) {
    total += /^[\u0000-\u00ff]+$/u.test(character) ? 0.55 : 1;
  }
  return total;
}

function cutVisualWidth(value, maximum) {
  let total = 0;
  let result = '';
  let lastBoundary = '';
  for (const character of graphemeSegments(value)) {
    const width = /^[\u0000-\u00ff]+$/u.test(character) ? 0.55 : 1;
    if (total + width > maximum) return lastBoundary && visualWidth(lastBoundary) >= 6 ? lastBoundary.trim() : result.trim();
    total += width;
    result += character;
    if (/[\s：:，,、；;。！？!?/]/u.test(character)) lastBoundary = result;
  }
  return result.trim();
}

export function deriveHook(text) {
  const lines = String(text ?? '')
    .split(/\n+/u)
    .map((line) => line.trim())
    .filter(Boolean);
  const candidate = lines.find((line) => !/^https?:\/\//iu.test(line)) ?? lines[0] ?? '';
  if (!candidate) return '';
  const sentence = candidate.match(/^.*?[。！？!?；;]/u)?.[0] ?? candidate;
  return visualWidth(sentence) <= 16 ? sentence : cutVisualWidth(sentence, 16);
}

export function formatMetric(value, suffix) {
  if (value == null || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return null;
  if (number >= 100_000_000) return `${(number / 100_000_000).toFixed(1).replace(/\.0$/u, '')}亿${suffix}`;
  if (number >= 10_000) return `${(number / 10_000).toFixed(1).replace(/\.0$/u, '')}万${suffix}`;
  return `${Math.round(number)}${suffix}`;
}

function metricsFor(node) {
  const metrics = node?.metrics ?? node ?? {};
  return [
    formatMetric(metrics.views, '阅读'),
    formatMetric(metrics.likes, '赞'),
    formatMetric(metrics.bookmarks, '收藏')
  ].filter(Boolean);
}

export function resolveOutputDirectory(requestedPath) {
  const absolute = path.resolve(requestedPath);
  if (!fs.existsSync(absolute)) return absolute;
  let run = 2;
  while (fs.existsSync(`${absolute}-run-${run}`)) run += 1;
  return `${absolute}-run-${run}`;
}

function reserveOutputDirectory(requestedPath) {
  const absolute = path.resolve(requestedPath);
  fs.mkdirSync(path.dirname(absolute), { recursive: true });
  let run = 1;
  while (true) {
    const candidate = run === 1 ? absolute : `${absolute}-run-${run}`;
    try {
      fs.mkdirSync(candidate);
      return candidate;
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      run += 1;
    }
  }
}

function safeOutputPath(outputDirectory, relativePath) {
  const root = path.resolve(outputDirectory);
  const resolved = path.resolve(root, relativePath);
  if (resolved === root || !resolved.startsWith(root + path.sep)) throw new Error(`输出路径越界：${relativePath}`);
  return resolved;
}

function assertAllowedHttpsUrl(value, allowedHosts, label) {
  let parsed;
  try {
    parsed = new URL(String(value));
  } catch {
    throw new Error(`${label}不是有效 URL`);
  }
  if (parsed.protocol !== 'https:' || !allowedHosts.has(parsed.hostname.toLowerCase())) {
    throw new Error(`拒绝非白名单 ${label}：${parsed.origin}`);
  }
  return parsed;
}

function mimeAllowed(contentType, allowedMimeTypes) {
  const normalized = String(contentType ?? '').split(';', 1)[0].trim().toLowerCase();
  return allowedMimeTypes.has(normalized);
}

async function responseBufferLimited(response, maximumBytes) {
  const declared = Number(response.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > maximumBytes) throw new Error(`响应超过 ${maximumBytes} 字节上限`);
  if (!response.body) {
    const buffer = Buffer.from(await response.arrayBuffer());
    if (buffer.length > maximumBytes) throw new Error(`响应超过 ${maximumBytes} 字节上限`);
    return buffer;
  }
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maximumBytes) {
      await reader.cancel();
      throw new Error(`响应超过 ${maximumBytes} 字节上限`);
    }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks, total);
}

async function fetchAllowedBuffer(value, { allowedHosts, allowedMimeTypes, maximumBytes, timeoutMs, headers, label }) {
  let current = assertAllowedHttpsUrl(value, allowedHosts, label);
  let lastError = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      for (let redirect = 0; redirect <= 4; redirect += 1) {
        const response = await fetch(current, {
          headers,
          redirect: 'manual',
          signal: AbortSignal.timeout(timeoutMs)
        });
        if (response.status >= 300 && response.status < 400) {
          const location = response.headers.get('location');
          if (!location || redirect === 4) throw new Error('重定向链无效或过长');
          current = assertAllowedHttpsUrl(new URL(location, current).href, allowedHosts, label);
          continue;
        }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const contentType = response.headers.get('content-type');
        if (!mimeAllowed(contentType, allowedMimeTypes)) throw new Error(`响应类型不允许：${contentType ?? '缺失'}`);
        return {
          buffer: await responseBufferLimited(response, maximumBytes),
          finalUrl: current.href,
          contentType: String(contentType)
        };
      }
    } catch (error) {
      lastError = error;
    }
  }

  const marker = `\n__YICHEN_X_SLICER_META_${crypto.randomBytes(12).toString('hex')}__\n`;
  const curl = spawnSync('curl', [
    '--fail', '--silent', '--show-error', '--max-time', String(Math.ceil(timeoutMs / 1000)),
    '--max-redirs', '0', '--proto', '=https', '--max-filesize', String(maximumBytes),
    ...Object.entries(headers).flatMap(([name, headerValue]) => ['--header', `${name}: ${headerValue}`]),
    '--write-out', `${marker}%{http_code}\n%{content_type}\n%{url_effective}`,
    current.href
  ], { encoding: null, maxBuffer: maximumBytes + 1024 * 1024 });
  if (curl.error || curl.status !== 0) {
    const stderr = Buffer.isBuffer(curl.stderr) ? curl.stderr.toString('utf8') : String(curl.stderr ?? '');
    throw new Error(`${label}读取失败：${lastError?.message ?? 'fetch 失败'}；curl：${curl.error?.message ?? stderr.trim()}`);
  }
  const stdout = Buffer.from(curl.stdout ?? []);
  const markerBuffer = Buffer.from(marker);
  const markerAt = stdout.lastIndexOf(markerBuffer);
  if (markerAt < 0) throw new Error(`${label}读取失败：curl 元数据缺失`);
  const buffer = stdout.subarray(0, markerAt);
  const [statusText, contentType, effectiveUrl] = stdout.subarray(markerAt + markerBuffer.length).toString('utf8').split('\n');
  const status = Number(statusText);
  assertAllowedHttpsUrl(effectiveUrl, allowedHosts, label);
  if (!Number.isInteger(status) || status < 200 || status >= 300) throw new Error(`${label}读取失败：HTTP ${statusText}`);
  if (!mimeAllowed(contentType, allowedMimeTypes)) throw new Error(`${label}响应类型不允许：${contentType || '缺失'}`);
  if (buffer.length > maximumBytes) throw new Error(`${label}响应超过 ${maximumBytes} 字节上限`);
  return { buffer, finalUrl: effectiveUrl, contentType };
}

async function readSource(options, status) {
  if (options.sourceJson) {
    const sourcePath = path.resolve(options.sourceJson);
    const sourceSize = fs.statSync(sourcePath).size;
    if (sourceSize > 8 * 1024 * 1024) throw new Error('source JSON 超过 8MB 上限');
    return {
      payload: JSON.parse(fs.readFileSync(sourcePath, 'utf8')),
      endpoint: null,
      sourcePath
    };
  }
  const endpoint = `https://api.fxtwitter.com/2/thread/${status.id}`;
  try {
    const response = await fetchAllowedBuffer(endpoint, {
      allowedHosts: new Set(['api.fxtwitter.com']),
      allowedMimeTypes: new Set(['application/json', 'text/json']),
      maximumBytes: 8 * 1024 * 1024,
      timeoutMs: 30_000,
      headers: { accept: 'application/json', 'user-agent': 'yichen-x-slicer/1.0' },
      label: 'FxTwitter JSON'
    });
    return { payload: JSON.parse(response.buffer.toString('utf8')), endpoint, sourcePath: null };
  } catch (error) {
    throw new Error(`FxTwitter 匿名读取失败：${error.message}`);
  }
}

export function detectImageFormat(buffer) {
  if (!Buffer.isBuffer(buffer) || buffer.length < 32) return null;
  if (buffer[0] === 0xff && buffer[1] === 0xd8 && buffer[2] === 0xff) {
    return { extension: '.jpg', content_type: 'image/jpeg' };
  }
  if (buffer.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    return { extension: '.png', content_type: 'image/png' };
  }
  const gifSignature = buffer.subarray(0, 6).toString('ascii');
  if (gifSignature === 'GIF87a' || gifSignature === 'GIF89a') {
    return { extension: '.gif', content_type: 'image/gif' };
  }
  if (buffer.subarray(0, 4).toString('ascii') === 'RIFF' && buffer.subarray(8, 12).toString('ascii') === 'WEBP') {
    return { extension: '.webp', content_type: 'image/webp' };
  }
  if (buffer.subarray(4, 8).toString('ascii') === 'ftyp') {
    const declaredSize = buffer.readUInt32BE(0);
    const boxEnd = declaredSize >= 16 ? Math.min(declaredSize, buffer.length) : Math.min(32, buffer.length);
    const brands = [buffer.subarray(8, 12).toString('ascii')];
    for (let offset = 16; offset + 4 <= boxEnd; offset += 4) {
      brands.push(buffer.subarray(offset, offset + 4).toString('ascii'));
    }
    if (brands.some((brand) => brand === 'avif' || brand === 'avis')) {
      return { extension: '.avif', content_type: 'image/avif' };
    }
  }
  return null;
}

function supportedMp4Signature(buffer) {
  return buffer.length >= 12 && buffer.subarray(4, 8).toString('ascii') === 'ftyp';
}

export async function materializeAsset(source, destination) {
  const value = String(source);
  if (!/^https:\/\//iu.test(value)) throw new Error('拒绝本地路径、file URL、data URL 或非 HTTPS 素材');
  const response = await fetchAllowedBuffer(value, {
    allowedHosts: X_IMAGE_HOSTS,
    allowedMimeTypes: new Set(['image/jpeg', 'image/png', 'image/webp', 'image/avif', 'image/gif']),
    maximumBytes: 25 * 1024 * 1024,
    timeoutMs: 45_000,
    headers: { accept: 'image/avif,image/webp,image/png,image/jpeg,image/gif', 'user-agent': 'Mozilla/5.0' },
    label: 'X 官方图片'
  });
  const buffer = response.buffer;
  const detected = detectImageFormat(buffer);
  if (!detected) throw new Error('素材签名不是受支持的位图格式');
  fs.writeFileSync(destination, buffer, { flag: 'wx' });
  return {
    bytes: buffer.length,
    sha256: sha256Buffer(buffer),
    content_type: detected.content_type,
    extension: detected.extension
  };
}

export async function materializeSourceImage(source, outputDirectory, relativeStem) {
  const provisionalRelativePath = `${relativeStem}.download`;
  const provisionalPath = safeOutputPath(outputDirectory, provisionalRelativePath);
  const integrity = await materializeAsset(source, provisionalPath);
  const relativePath = `${relativeStem}${integrity.extension}`;
  const destination = safeOutputPath(outputDirectory, relativePath);
  if (fs.existsSync(destination)) throw new Error(`source-only 素材目标已存在：${relativePath}`);
  fs.renameSync(provisionalPath, destination);
  return { relative_path: relativePath, ...integrity };
}

export async function materializeVideoAsset(source, destination) {
  const value = String(source);
  if (!/^https:\/\//iu.test(value)) throw new Error('拒绝本地路径、file URL、data URL 或非 HTTPS 视频素材');
  const response = await fetchAllowedBuffer(value, {
    allowedHosts: X_VIDEO_HOSTS,
    allowedMimeTypes: new Set(['video/mp4']),
    maximumBytes: 512 * 1024 * 1024,
    timeoutMs: 180_000,
    headers: { accept: 'video/mp4', 'user-agent': 'Mozilla/5.0' },
    label: 'X 官方原生视频'
  });
  const buffer = response.buffer;
  if (!supportedMp4Signature(buffer)) throw new Error('视频素材签名不是受支持的 MP4');
  fs.writeFileSync(destination, buffer, { flag: 'wx' });
  return {
    bytes: buffer.length,
    sha256: sha256Buffer(buffer),
    content_type: response.contentType.split(';', 1)[0].trim().toLowerCase()
  };
}

function normalizedAuthor(author) {
  return {
    id: author?.id != null ? String(author.id) : null,
    name: String(author?.name ?? authorHandle(author) ?? '作者'),
    screen_name: authorHandle(author),
    avatar_url: author?.avatar_url ? String(author.avatar_url) : null
  };
}

async function prepareContent(route, outputDirectory, {
  includeNativeVideo = true,
  includeAvatar = true,
  useDetectedMediaExtensions = false
} = {}) {
  const assetsDirectory = safeOutputPath(outputDirectory, 'assets');
  fs.mkdirSync(assetsDirectory);
  const rootAuthor = normalizedAuthor(route.focal.author);
  let avatar = null;
  if (includeAvatar && rootAuthor.avatar_url) {
    const relativePath = 'assets/avatar.jpg';
    const destination = safeOutputPath(outputDirectory, relativePath);
    try {
      avatar = {
        relative_path: relativePath,
        source_url: rootAuthor.avatar_url,
        ...await materializeAsset(rootAuthor.avatar_url, destination)
      };
    } catch (error) {
      avatar = { relative_path: null, source_url: rootAuthor.avatar_url, error: error.message };
    }
  }

  const mediaAssets = [];
  const contentFrames = [];
  for (let nodeIndex = 0; nodeIndex < route.selectedNodes.length; nodeIndex += 1) {
    const selected = route.selectedNodes[nodeIndex];
    const node = selected.node;
    const author = normalizedAuthor(node.author);
    const slices = splitText(selected.cleanedText);
    const hookFallback = deriveHook(selected.cleanedText);
    for (let textIndex = 0; textIndex < slices.length; textIndex += 1) {
      contentFrames.push({
        id: `${String(node.id)}-text-${textIndex + 1}`,
        kind: 'text',
        source_scope: String(node.id) === String(route.focal.id) ? 'focal_body' : 'thread_body',
        source_post_id: String(node.id),
        source_node_index: nodeIndex,
        source_part_index: textIndex,
        text: slices[textIndex],
        source_full_text: selected.cleanedText,
        hook: deriveHook(slices[textIndex]) || hookFallback,
        author,
        avatar_relative_path: avatar?.relative_path ?? null,
        metrics: metricsFor(node)
      });
    }
    for (let mediaIndex = 0; mediaIndex < selected.media.length; mediaIndex += 1) {
      const media = selected.media[mediaIndex];
      const relativeStem = `assets/media-${nodeIndex + 1}-${mediaIndex + 1}${media.type === 'video' ? '-poster' : ''}`;
      let relativePath;
      let integrity;
      if (useDetectedMediaExtensions) {
        const downloaded = await materializeSourceImage(media.url, outputDirectory, relativeStem);
        relativePath = downloaded.relative_path;
        integrity = downloaded;
      } else {
        relativePath = `${relativeStem}.jpg`;
        const destination = safeOutputPath(outputDirectory, relativePath);
        integrity = await materializeAsset(media.url, destination);
      }
      const asset = {
        ...media,
        relative_path: relativePath,
        source_post_id: String(node.id),
        bytes: integrity.bytes,
        sha256: integrity.sha256,
        ...(useDetectedMediaExtensions ? { content_type: integrity.content_type } : {}),
        source_scope: 'own_media'
      };
      if (media.type === 'video') asset.native_video_requested = includeNativeVideo;
      if (media.type === 'video' && includeNativeVideo) {
        if (!media.video_url) throw new Error(`原生视频 ${media.id} 没有可用的 MP4；拒绝退化为静态封面`);
        const videoRelativePath = `assets/media-${nodeIndex + 1}-${mediaIndex + 1}-source.mp4`;
        const videoDestination = safeOutputPath(outputDirectory, videoRelativePath);
        const videoIntegrity = await materializeVideoAsset(media.video_url, videoDestination);
        asset.native_video = {
          relative_path: videoRelativePath,
          bytes: videoIntegrity.bytes,
          sha256: videoIntegrity.sha256,
          content_type: videoIntegrity.content_type,
          requested_duration_seconds: media.video_duration_seconds,
          selected_variant: media.video_variant
        };
      }
      mediaAssets.push(asset);
      contentFrames.push({
        id: `${String(node.id)}-media-${mediaIndex + 1}`,
        kind: 'media',
        source_scope: String(node.id) === String(route.focal.id) ? 'focal_body' : 'thread_body',
        source_post_id: String(node.id),
        source_node_index: nodeIndex,
        source_part_index: mediaIndex,
        source_full_text: selected.cleanedText,
        hook: hookFallback,
        author,
        avatar_relative_path: avatar?.relative_path ?? null,
        metrics: metricsFor(node),
        media: asset
      });
    }
  }
  return { contentFrames, assets: { avatar, media: mediaAssets } };
}

function fontSettings(text) {
  const length = String(text).length;
  if (length > 330) return { size: 36, lineHeight: 1.35 };
  if (length > 285) return { size: 37, lineHeight: 1.38 };
  return { size: 38, lineHeight: 1.4 };
}

function authorHeader(frame) {
  const avatar = frame.avatar_relative_path
    ? `<img class="avatar" src="${escapeHtml(frame.avatar_relative_path)}" alt="${escapeHtml(frame.author.name)}头像">`
    : '<div class="avatar-fallback" aria-hidden="true"></div>';
  return [
    '<header class="source-head">',
    avatar,
    '<div class="author"><strong>', escapeHtml(frame.author.name), '</strong><span>@', escapeHtml(frame.author.screen_name), '</span></div>',
    '<div class="source-label" aria-hidden="true"></div>',
    '</header>'
  ].join('');
}

function frameCore(frame) {
  if (frame.kind === 'media') {
    const mediaAlt = frame.media.type === 'video' ? '原生视频画面' : '内容图片';
    return [
      '<section class="source-card source-media" data-source-post-id="', escapeHtml(frame.source_post_id), '">',
      authorHeader(frame),
      '<div class="media-stage"><img class="source-image" src="', escapeHtml(frame.media.relative_path), '" alt="', mediaAlt, '"></div>',
      '</section>'
    ].join('');
  }
  const font = fontSettings(frame.text);
  return [
    '<section class="source-card source-text" data-source-post-id="', escapeHtml(frame.source_post_id), '" style="--body-size:', String(font.size), 'px;--body-line-height:', String(font.lineHeight), '">',
    authorHeader(frame),
    '<div class="source-content" data-exact-source="body">', escapeHtml(frame.text), '</div>',
    '</section>'
  ].join('');
}

function frameHtml(css, template, frame, sequenceNumber) {
  const metricHtml = frame.metrics.map((metric, index) => [
    index ? '<i>｜</i>' : '',
    '<span>', escapeHtml(metric), '</span>'
  ].join('')).join('');
  return [
    '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=1080,initial-scale=1">',
    '<title>', escapeHtml(template.name), '·第', String(sequenceNumber), '张</title>',
    '<style>', css, '</style></head><body>',
    '<main class="poster theme-', escapeHtml(template.id), '" data-template="', escapeHtml(template.id), '" data-source-id="', escapeHtml(frame.source_post_id), '">',
    '<div class="decor decor-one"></div><div class="decor decor-two"></div><div class="decor decor-three"></div>',
    '<h1 class="hook">', escapeHtml(frame.hook), '</h1>',
    frameCore(frame),
    '<footer class="highlights">', metricHtml, '</footer>',
    '</main><script>(()=>{const hook=document.querySelector(".hook");if(!hook)return;let size=Number.parseFloat(getComputedStyle(hook).fontSize);while((hook.scrollHeight>hook.clientHeight+1||hook.scrollWidth>hook.clientWidth+1)&&size>38){size-=1;hook.style.fontSize=size+"px";}})();</script></body></html>'
  ].join('');
}

function makeOutputs(contentFrames, templates, outputDirectory) {
  const css = fs.readFileSync(POSTER_CSS_PATH, 'utf8');
  const total = contentFrames.length * templates.length;
  const digits = Math.max(2, String(total).length);
  const outputs = [];
  let sequence = 1;
  for (const template of templates) {
    for (const contentFrame of contentFrames) {
      const templatePart = templates.length > 1 ? `${template.id}-` : '';
      const base = `${String(sequence).padStart(digits, '0')}-${templatePart}${contentFrame.id}`;
      const output = {
        ...contentFrame,
        order: sequence,
        base,
        template_id: template.id,
        template_name: template.name,
        label: '',
        html_file: `${base}.html`,
        png_file: `${base}.png`
      };
      fs.writeFileSync(safeOutputPath(outputDirectory, output.html_file), frameHtml(css, template, output, sequence), { encoding: 'utf8', flag: 'wx' });
      outputs.push(output);
      sequence += 1;
    }
  }
  return outputs;
}

function makePreviewFiles(outputs, templates, outputDirectory) {
  const columns = 4;
  const itemWidth = 270;
  const itemHeight = 392;
  const rows = Math.ceil(outputs.length / columns);
  const sheetHeight = Math.max(itemHeight, rows * itemHeight);
  const items = outputs.map((output) => [
    '<figure><a href="', escapeHtml(output.html_file), '"><img src="', escapeHtml(output.png_file), '" alt="第', String(output.order), '张"></a>',
    '<figcaption>', String(output.order).padStart(2, '0'), ' · ', escapeHtml(output.template_name), output.hook ? ' · ' + escapeHtml(output.hook) : '', '</figcaption></figure>'
  ].join('')).join('');
  const contactSheetHtml = [
    '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>',
    '*{box-sizing:border-box}html,body{margin:0;width:1080px;height:', String(sheetHeight), 'px;overflow:hidden;background:#241b17}',
    'body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{display:grid;grid-template-columns:repeat(4,270px)}',
    'figure{height:392px;margin:0;padding:6px;background:#241b17;color:#fff}a{display:block}img{display:block;width:258px;height:344px;object-fit:contain;background:#120e0c}',
    'figcaption{height:36px;padding:7px 4px 0;overflow:hidden;font-size:16px;font-weight:700;line-height:1.1;white-space:nowrap}',
    '</style></head><body><main>', items, '</main></body></html>'
  ].join('');
  fs.writeFileSync(safeOutputPath(outputDirectory, 'contact-sheet.html'), contactSheetHtml, { encoding: 'utf8', flag: 'wx' });

  const templateSummary = templates.map((template) => template.name).join('、');
  const indexHtml = [
    '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>帖子成片图像</title><style>',
    '*{box-sizing:border-box}body{margin:0;background:#241b17;color:#fff8e9;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}',
    'header{padding:42px 5vw 28px;background:linear-gradient(135deg,#fae46d,#f1aa4d,#d3975a);color:#442b25}h1{margin:0 0 10px;font-size:40px}p{margin:8px 0;line-height:1.6}',
    'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px;padding:32px 5vw 60px}figure{margin:0;padding:12px;background:#4a2d1e;border:1px solid #8c5939;border-radius:16px}',
    'img{display:block;width:100%;aspect-ratio:3/4;object-fit:contain;background:#19100b;border-radius:10px}figcaption{padding:12px 4px 2px;font-size:17px;font-weight:700;white-space:normal}',
    '</style></head><body><header><h1>帖子成片图像</h1><p>', escapeHtml(templateSummary), '</p><p>共 ', String(outputs.length), ' 张，全部为 1080×1440；只保留帖子本体与同作者连续帖子，所有引用内容均忽略。</p></header><main>', items, '</main></body></html>'
  ].join('');
  fs.writeFileSync(safeOutputPath(outputDirectory, 'index.html'), indexHtml, { encoding: 'utf8', flag: 'wx' });
  return { width: 1080, height: sheetHeight };
}

function calculateCoverage(outputs, templates, route) {
  const byTemplate = {};
  let allTextMatches = true;
  let allMediaMatches = true;
  for (const template of templates) {
    const perNode = {};
    for (const selected of route.selectedNodes) {
      const id = String(selected.node.id);
      const relevant = outputs.filter((output) => output.template_id === template.id && output.source_post_id === id);
      const text = relevant.filter((output) => output.kind === 'text').map((output) => output.text).join('');
      const actualMediaIds = relevant.filter((output) => output.kind === 'media').map((output) => output.media.id);
      const expectedMediaIds = selected.media.map((media) => media.id);
      const actualMediaDescriptors = relevant.filter((output) => output.kind === 'media').map((output) => ({
        id: output.media.id,
        type: output.media.type,
        video_url_sha256: output.media.video_url ? sha256Buffer(Buffer.from(String(output.media.video_url))) : null
      }));
      const expectedMediaDescriptors = selected.media.map((media) => ({
        id: media.id,
        type: media.type,
        video_url_sha256: media.video_url ? sha256Buffer(Buffer.from(String(media.video_url))) : null
      }));
      const textMatches = normalizeText(text) === normalizeText(selected.cleanedText);
      const mediaMatches = JSON.stringify(actualMediaDescriptors) === JSON.stringify(expectedMediaDescriptors);
      allTextMatches &&= textMatches;
      allMediaMatches &&= mediaMatches;
      perNode[id] = {
        text_normalized_matches: textMatches,
        expected_media_ids: expectedMediaIds,
        output_media_ids: actualMediaIds,
        expected_media_descriptors: expectedMediaDescriptors,
        output_media_descriptors: actualMediaDescriptors,
        media_matches: mediaMatches,
        text_frames: relevant.filter((output) => output.kind === 'text').length,
        media_frames: actualMediaIds.length
      };
    }
    byTemplate[template.id] = perNode;
  }
  const outputMedia = outputs.filter((output) => output.kind === 'media').map((output) => output.media);
  const quoteMediaCollisions = quoteMediaCollisionAudit(outputMedia, route.audit);
  return {
    all_text_normalized_matches: allTextMatches,
    all_own_media_matches: allMediaMatches,
    quote_frames: outputs.filter((output) => output.source_scope === 'quote').length,
    quote_media_collision_count: quoteMediaCollisions.length,
    selected_status_ids: route.selectedNodes.map(({ node }) => String(node.id)),
    excluded_quote_only_count: route.audit.excluded_statuses.filter((status) => status.reason === 'quote_only').length,
    by_template: byTemplate
  };
}

function findFilesNamed(root, relativeSuffix, maximumDepth = 8) {
  if (!root || !fs.existsSync(root)) return [];
  const results = [];
  const stack = [{ directory: root, depth: 0 }];
  while (stack.length) {
    const current = stack.pop();
    if (current.depth > maximumDepth) continue;
    let entries;
    try {
      entries = fs.readdirSync(current.directory, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const fullPath = path.join(current.directory, entry.name);
      if (entry.isDirectory()) {
        if (!entry.name.startsWith('.') || current.depth < 2) stack.push({ directory: fullPath, depth: current.depth + 1 });
      } else if (fullPath.endsWith(relativeSuffix)) {
        results.push(fullPath);
      }
    }
  }
  return results;
}

function possiblePlaywrightFiles() {
  const candidates = [];
  const explicit = process.env.YICHEN_X_SLICER_PLAYWRIGHT_MODULE;
  if (explicit) {
    const resolved = path.resolve(explicit);
    candidates.push(fs.existsSync(resolved) && fs.statSync(resolved).isDirectory() ? path.join(resolved, 'index.mjs') : resolved);
  }
  let current = path.dirname(process.execPath);
  for (let depth = 0; depth < 7; depth += 1) {
    candidates.push(path.join(current, 'node_modules', 'playwright', 'index.mjs'));
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  const home = os.homedir();
  const searchRoots = [
    path.join(home, '.cache', 'codex-runtimes'),
    path.join(home, '.codex', 'plugins', 'cache', 'openai-primary-runtime')
  ];
  for (const root of searchRoots) {
    candidates.push(...findFilesNamed(root, `${path.sep}node_modules${path.sep}playwright${path.sep}index.mjs`, 9));
  }
  return uniqueStrings(candidates.filter((candidate) => fs.existsSync(candidate))).sort((left, right) => {
    try {
      return fs.statSync(right).mtimeMs - fs.statSync(left).mtimeMs;
    } catch {
      return 0;
    }
  });
}

export async function loadPlaywrightChromium() {
  try {
    const module = await import('playwright');
    const chromium = module.chromium ?? module.default?.chromium;
    if (chromium) return { chromium, modulePath: 'playwright' };
  } catch {
    // The Codex desktop runtime usually keeps Playwright outside normal Node resolution.
  }
  const errors = [];
  for (const modulePath of possiblePlaywrightFiles()) {
    try {
      const module = await import(pathToFileURL(modulePath).href);
      const chromium = module.chromium ?? module.default?.chromium;
      if (chromium) return { chromium, modulePath };
    } catch (error) {
      errors.push(`${modulePath}: ${error.message}`);
    }
  }
  throw new Error(`未找到可用的 Codex Playwright。可设置 YICHEN_X_SLICER_PLAYWRIGHT_MODULE。${errors.length ? `\n${errors.join('\n')}` : ''}`);
}

function findLocalChrome() {
  const candidates = [
    process.env.YICHEN_X_SLICER_CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser'
  ].filter(Boolean);
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) throw new Error('未找到本机 Chrome；可设置 YICHEN_X_SLICER_CHROME_PATH');
  return found;
}

function readPngDimensions(file) {
  const buffer = fs.readFileSync(file);
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (buffer.length < 24 || !buffer.subarray(0, 8).equals(signature) || buffer.toString('ascii', 12, 16) !== 'IHDR') {
    throw new Error(`不是有效的 PNG：${file}`);
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

function expectedFrameForBrowser(output) {
  return {
    kind: output.kind,
    text: output.kind === 'text' ? output.text : null,
    sourceFullText: output.source_full_text,
    hook: output.hook,
    sourcePostId: output.source_post_id,
    author: output.author,
    metrics: output.metrics,
    media: output.kind === 'media' ? {
      relativePath: output.media.relative_path,
      width: output.media.width,
      height: output.media.height
    } : null
  };
}

async function inspectPage(page, expected) {
  return page.evaluate((frame) => {
    const poster = document.querySelector('.poster');
    const card = document.querySelector('.source-card');
    const exact = document.querySelector('[data-exact-source]');
    const author = document.querySelector('.author');
    const authorName = document.querySelector('.author strong');
    const authorHandle = document.querySelector('.author span');
    const header = document.querySelector('.source-head');
    const highlights = document.querySelector('.highlights');
    const labelNodes = Array.from(document.querySelectorAll('.source-label'));
    const posterRect = poster?.getBoundingClientRect();
    const cardRect = card?.getBoundingClientRect();
    const hook = document.querySelector('.hook');
    const hookRect = hook?.getBoundingClientRect();
    const authorRect = author?.getBoundingClientRect();
    const headerRect = header?.getBoundingClientRect();
    const sourceImages = Array.from(document.querySelectorAll('.source-image')).map((image) => {
      const imageRect = image.getBoundingClientRect();
      const stageRect = image.closest('.media-stage')?.getBoundingClientRect();
      return {
        relativePath: image.getAttribute('src'),
        loaded: image.complete && image.naturalWidth > 0 && image.naturalHeight > 0,
        naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight,
        objectFit: getComputedStyle(image).objectFit,
        transform: getComputedStyle(image).transform,
        renderedRect: { left: imageRect.left, top: imageRect.top, right: imageRect.right, bottom: imageRect.bottom, width: imageRect.width, height: imageRect.height },
        stageRect: stageRect ? { left: stageRect.left, top: stageRect.top, right: stageRect.right, bottom: stageRect.bottom, width: stageRect.width, height: stageRect.height } : null,
        containedWithinStage: Boolean(stageRect)
          && imageRect.left >= stageRect.left - 1
          && imageRect.top >= stageRect.top - 1
          && imageRect.right <= stageRect.right + 1
          && imageRect.bottom <= stageRect.bottom + 1
      };
    });
    const contentOverflow = exact ? {
      scrollHeight: exact.scrollHeight,
      clientHeight: exact.clientHeight,
      scrollWidth: exact.scrollWidth,
      clientWidth: exact.clientWidth,
      fontSize: Number.parseFloat(getComputedStyle(exact).fontSize)
    } : null;
    const nonCoreImages = Array.from(document.querySelectorAll('img')).filter((image) => !image.classList.contains('avatar') && !image.classList.contains('source-image'));
    const labels = labelNodes.map((node) => {
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return {
        text: node.textContent.trim(),
        width: rect.width,
        height: rect.height,
        display: style.display,
        visibility: style.visibility,
        opacity: style.opacity
      };
    });
    return {
      poster: posterRect ? { width: posterRect.width, height: posterRect.height } : null,
      card: cardRect && posterRect ? {
        left: cardRect.left,
        top: cardRect.top,
        right: cardRect.right,
        bottom: cardRect.bottom,
        width: cardRect.width,
        height: cardRect.height,
        centerOffsetX: Math.abs(cardRect.left + cardRect.width / 2 - posterRect.width / 2),
        centerOffsetY: Math.abs(cardRect.top + cardRect.height / 2 - posterRect.height / 2),
        areaRatio: cardRect.width * cardRect.height / (posterRect.width * posterRect.height)
      } : null,
      sourcePostId: card?.dataset.sourcePostId ?? null,
      exactNodePresent: frame.kind === 'text' ? Boolean(exact) : !exact,
      exactNodeMatches: frame.kind === 'text' ? exact?.textContent === frame.text : !exact,
      authorMatches: authorName?.textContent === frame.author.name && authorHandle?.textContent === '@' + frame.author.screen_name,
      headerLayoutValid: Boolean(authorRect && headerRect) && authorRect.right <= headerRect.right + 1 && authorRect.left >= headerRect.left - 1,
      authorUnclipped: Boolean(author) && author.scrollWidth <= author.clientWidth + 1,
      labels,
      sourceImages,
      contentOverflow,
      hookText: hook?.textContent ?? '',
      hookSourceDerived: !frame.hook || frame.sourceFullText.includes(frame.hook),
      hookLayout: hook && hookRect && posterRect ? {
        left: hookRect.left,
        top: hookRect.top,
        right: hookRect.right,
        bottom: hookRect.bottom,
        scrollHeight: hook.scrollHeight,
        clientHeight: hook.clientHeight,
        scrollWidth: hook.scrollWidth,
        clientWidth: hook.clientWidth,
        fontSize: Number.parseFloat(getComputedStyle(hook).fontSize),
        containedWithinHeaderSafeArea: hookRect.left >= 72
          && hookRect.right <= posterRect.right - 72
          && hookRect.top >= 24
          && hookRect.bottom <= 150
      } : null,
      metricTexts: Array.from(document.querySelectorAll('.highlights span')).map((node) => node.textContent),
      highlightsLayout: highlights ? {
        scrollWidth: highlights.scrollWidth,
        clientWidth: highlights.clientWidth,
        scrollHeight: highlights.scrollHeight,
        clientHeight: highlights.clientHeight
      } : null,
      decorativeImageCount: nonCoreImages.length,
      documentOverflow: document.documentElement.scrollWidth > 1080 || document.documentElement.scrollHeight > 1440
    };
  }, expected);
}

function browserProblems(checks, output) {
  const problems = [];
  if (!checks.poster || checks.poster.width !== CANVAS.width || checks.poster.height !== CANVAS.height) problems.push('画布尺寸错误');
  if (!checks.card || checks.card.left < 72 || checks.card.right > 1008 || checks.card.top < 150 || checks.card.bottom > 1290) problems.push('中央源卡越过安全区');
  if (!checks.card || checks.card.centerOffsetX > 1 || checks.card.centerOffsetY > 12 || checks.card.areaRatio < .6) problems.push('中央源卡未完整居中');
  if (checks.sourcePostId !== output.source_post_id) problems.push('源帖子 ID 不一致');
  if (!checks.exactNodePresent || !checks.exactNodeMatches) problems.push('本帧原文缺失或未逐字保留');
  if (!checks.authorMatches || !checks.headerLayoutValid || !checks.authorUnclipped) problems.push('作者栏不完整');
  if (checks.labels.length !== 1 || checks.labels.some((label) => label.text !== '' || label.width !== 0 || label.height !== 0 || (label.visibility !== 'hidden' && label.opacity !== '0'))) problems.push('作者栏右侧标签未保持零尺寸空白');
  if (checks.contentOverflow && (checks.contentOverflow.scrollHeight > checks.contentOverflow.clientHeight + 1 || checks.contentOverflow.scrollWidth > checks.contentOverflow.clientWidth + 1)) problems.push('正文区域发生裁切');
  if (checks.contentOverflow && checks.contentOverflow.fontSize < 36) problems.push('正文字号低于 36px');
  if (!checks.hookSourceDerived || checks.hookText !== output.hook) problems.push('外围标题不是原文提取内容');
  if (!checks.hookLayout || checks.hookLayout.scrollHeight > checks.hookLayout.clientHeight + 1 || checks.hookLayout.scrollWidth > checks.hookLayout.clientWidth + 1 || !checks.hookLayout.containedWithinHeaderSafeArea) problems.push('外围标题发生裁切或越过安全区');
  if (JSON.stringify(checks.metricTexts) !== JSON.stringify(output.metrics)) problems.push('外围数据与源数据不一致');
  if (!checks.highlightsLayout || checks.highlightsLayout.scrollWidth > checks.highlightsLayout.clientWidth + 1 || checks.highlightsLayout.scrollHeight > checks.highlightsLayout.clientHeight + 1) problems.push('外围数据区域发生裁切');
  if (checks.decorativeImageCount !== 0) problems.push('出现装饰性图片');
  if (checks.documentOverflow) problems.push('页面发生溢出');
  if (output.kind === 'media') {
    if (checks.sourceImages.length !== 1) problems.push('媒体帧图片数量错误');
    const image = checks.sourceImages[0];
    if (!image || image.relativePath !== output.media.relative_path || !image.loaded || image.objectFit !== 'contain' || image.transform !== 'none' || !image.containedWithinStage) problems.push('媒体未完整适配或图片元素越过容器');
    if (image && output.media.width && image.naturalWidth !== output.media.width) problems.push('媒体原始宽度不一致');
    if (image && output.media.height && image.naturalHeight !== output.media.height) problems.push('媒体原始高度不一致');
    if (output.media.type === 'video' && output.media.native_video_requested) {
      const layout = output.media_layout;
      if (!output.media.native_video) problems.push('原生视频未下载，不能只输出静态封面');
      if (!layout || layout.x < 0 || layout.y < 0 || layout.width < 2 || layout.height < 2 || layout.x + layout.width > CANVAS.width || layout.y + layout.height > CANVAS.height) {
        problems.push('原生视频嵌入区域无效');
      }
    }
  } else if (checks.sourceImages.length !== 0) {
    problems.push('正文帧混入媒体');
  }
  if (output.source_scope === 'quote') problems.push('输出混入引用内容');
  return problems;
}

async function renderAndInspect(outputs, previewSheet, outputDirectory, coverage) {
  const { chromium, modulePath } = await loadPlaywrightChromium();
  const chromePath = findLocalChrome();
  const browser = await chromium.launch({
    headless: true,
    executablePath: chromePath,
    args: ['--allow-file-access-from-files', '--disable-background-networking', '--disable-component-update', '--disable-sync']
  });
  const report = {
    version: 'yichen-x-slicer-qa/v3',
    created_at: new Date().toISOString(),
    canvas: CANVAS,
    playwright_runtime: modulePath === 'playwright' ? 'playwright' : 'bundled-playwright',
    browser: path.basename(chromePath),
    coverage,
    rendered: [],
    failures: [],
    zip: null
  };
  try {
    const context = await browser.newContext({ viewport: { width: CANVAS.width, height: CANVAS.height }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    for (const output of outputs) {
      const htmlPath = safeOutputPath(outputDirectory, output.html_file);
      await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
      await page.evaluate(() => document.fonts.ready);
      await page.waitForFunction(() => Array.from(document.images).every((image) => image.complete), null, { timeout: 15_000 });
      const checks = await inspectPage(page, expectedFrameForBrowser(output));
      if (output.kind === 'media' && output.media.type === 'video') {
        const stage = checks.sourceImages[0]?.stageRect;
        if (stage) {
          output.media_layout = {
            x: Math.round(stage.left) + 1,
            y: Math.round(stage.top) + 1,
            width: Math.max(2, Math.round(stage.width) - 2),
            height: Math.max(2, Math.round(stage.height) - 2)
          };
        }
      }
      const pngPath = safeOutputPath(outputDirectory, output.png_file);
      await page.screenshot({ path: pngPath, clip: { x: 0, y: 0, width: CANVAS.width, height: CANVAS.height } });
      const dimensions = readPngDimensions(pngPath);
      const problems = browserProblems(checks, output);
      if (dimensions.width !== CANVAS.width || dimensions.height !== CANVAS.height) problems.push('PNG 尺寸错误');
      const rendered = {
        base: output.base,
        template_id: output.template_id,
        source_post_id: output.source_post_id,
        kind: output.kind,
        checks,
        png_dimensions: dimensions,
        png_sha256: sha256File(pngPath),
        problems
      };
      report.rendered.push(rendered);
      if (problems.length) report.failures.push({ base: output.base, problems });
      process.stdout.write(`已渲染并检查 ${output.base}\n`);
    }
    await page.setViewportSize(previewSheet);
    await page.goto(pathToFileURL(safeOutputPath(outputDirectory, 'contact-sheet.html')).href, { waitUntil: 'load' });
    await page.waitForFunction(() => Array.from(document.images).every((image) => image.complete), null, { timeout: 30_000 });
    await page.screenshot({ path: safeOutputPath(outputDirectory, 'contact-sheet.png'), clip: { x: 0, y: 0, width: previewSheet.width, height: previewSheet.height } });
    await context.close();
  } finally {
    await browser.close();
  }
  return report;
}

function runCommand(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: options.encoding ?? null, maxBuffer: 256 * 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const stderr = Buffer.isBuffer(result.stderr) ? result.stderr.toString('utf8') : String(result.stderr ?? '');
    throw new Error(`${command} 执行失败：${stderr.trim()}`);
  }
  return result.stdout;
}

function createAndVerifyZip(outputs, templateIds, outputDirectory) {
  const title = templateIds.length === 1 ? TEMPLATE_BY_ID.get(templateIds[0]).name : '十一套模板';
  const zipName = `${title}-${outputs.length}张成片.zip`;
  const zipPath = safeOutputPath(outputDirectory, zipName);
  const pngPaths = outputs.map((output) => safeOutputPath(outputDirectory, output.png_file));
  runCommand('zip', ['-q', '-j', zipPath, ...pngPaths]);
  const entryText = String(runCommand('unzip', ['-Z1', zipPath], { encoding: 'utf8' }));
  const entries = entryText.split(/\r?\n/u).filter(Boolean);
  const expectedEntries = outputs.map((output) => output.png_file);
  const entrySetMatches = JSON.stringify([...entries].sort()) === JSON.stringify([...expectedEntries].sort());
  const hashes = [];
  let hashesMatch = entrySetMatches;
  for (const output of outputs) {
    const archived = runCommand('unzip', ['-p', zipPath, output.png_file]);
    const archivedHash = sha256Buffer(archived);
    const currentHash = sha256File(safeOutputPath(outputDirectory, output.png_file));
    const matches = archivedHash === currentHash;
    hashesMatch &&= matches;
    hashes.push({ entry: output.png_file, archived_sha256: archivedHash, current_sha256: currentHash, matches });
  }
  return {
    file: zipName,
    path: zipPath,
    entry_count: entries.length,
    expected_entry_count: expectedEntries.length,
    entries_only_numbered_pngs: entries.every((entry) => /^\d+-.+\.png$/u.test(entry)),
    entry_set_matches: entrySetMatches,
    hashes_match: hashesMatch,
    hashes,
    sha256: sha256File(zipPath)
  };
}

function serializableOutput(output) {
  const copy = { ...output };
  delete copy.source_full_text;
  return copy;
}

export function manifestFor({ options, status, normalized, route, templates, outputs, assets, previewSheet, coverage, outputDirectory }) {
  const manifest = {
    version: 'yichen-x-slicer-manifest/v3',
    created_at: new Date().toISOString(),
    output_directory: '.',
    template_requested: options.template,
    default_template: DEFAULT_TEMPLATE,
    default_applied: options.template === DEFAULT_TEMPLATE,
    templates: templates.map(({ id, name, description }) => ({ id, name, description })),
    canvas: CANVAS,
    source: {
      url: status.canonicalUrl,
      post_id: status.id,
      backend: normalized.backend,
      login_state_used: false,
      discovery_performed: false,
      retrieved_at: normalized.retrievedAt
    },
    routed_input_type: route.resolvedInputType,
    content_policy: {
      include_focal_body: true,
      include_verified_same_author_direct_reply_chain: route.resolvedInputType.startsWith('thread'),
      include_each_selected_node_own_media: true,
      ignore_all_quotes: true,
      exclude_other_author_replies: true,
      skip_quote_only_nodes: true,
      embed_complete_own_native_video_in_mp4: options.video,
      preserve_selected_native_video_audio: options.video,
      generated_tts: false,
      bgm: false,
      source_label: 'blank_zero_size',
      minimum_body_font_px: 36
    },
    coverage,
    assets,
    preview_sheet: previewSheet,
    outputs: outputs.map(serializableOutput),
    zip: null
  };
  if (options.video) {
    manifest.video = {
      requested: true,
      profile: VIDEO_PROFILE,
      outputs: []
    };
  }
  return sanitizeRemoteUrlsForPersistence(manifest);
}

function assertPreRenderIntegrity(route, contentFrames, coverage) {
  const selectedIds = new Set(route.audit.selected_status_ids);
  const problems = [];
  if (!contentFrames.length) problems.push('去除引用内容后没有可生成的正文或自身媒体');
  if (!coverage.all_text_normalized_matches) problems.push('正文拆帧未完整连续覆盖');
  if (!coverage.all_own_media_matches) problems.push('自身媒体未完整覆盖');
  if (coverage.quote_frames !== 0) problems.push('输出中存在引用内容帧');
  if (coverage.quote_media_collision_count !== 0) problems.push('输出中存在引用媒体 ID 或来源碰撞');
  if (contentFrames.some((frame) => !selectedIds.has(frame.source_post_id))) problems.push('输出中存在未选中的帖子');
  if (contentFrames.some((frame) => frame.kind === 'media' && frame.media.source_scope !== 'own_media')) problems.push('输出中存在非帖子自身媒体');
  if (contentFrames.some((frame) => frame.kind === 'media' && frame.media.type === 'video' && frame.media.native_video_requested && !frame.media.native_video?.relative_path)) problems.push('原生视频未准备完成，拒绝静态封面替代');
  if (contentFrames.some((frame) => frame.hook && !frame.source_full_text.includes(frame.hook))) problems.push('外围标题不是原文子串');
  if (problems.length) throw new Error(problems.join('；'));
}

export function selectedSourceForDelivery(status, normalized, route) {
  const focalMetrics = route.focal?.metrics ?? route.focal ?? {};
  const metricValue = (value) => {
    if (value == null || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 ? number : null;
  };
  return sanitizeRemoteUrlsForPersistence({
    version: 'yichen-x-slicer-selected-source/v2',
    source: {
      url: status.canonicalUrl,
      post_id: status.id,
      backend: normalized.backend,
      login_state_used: false,
      discovery_performed: false,
      retrieved_at: normalized.retrievedAt
    },
    routed_input_type: route.resolvedInputType,
    selected_statuses: route.selectedNodes.map(({ node, cleanedText, media }) => ({
      id: String(node.id),
      url: String(node.url ?? `https://x.com/${authorHandle(node.author)}/status/${String(node.id)}`),
      cleaned_text: cleanedText,
      created_at: node.created_at ?? null,
      author: {
        id: node.author?.id != null ? String(node.author.id) : null,
        name: String(node.author?.name ?? ''),
        screen_name: authorHandle(node.author),
        avatar_url: node.author?.avatar_url ? String(node.author.avatar_url) : null
      },
      own_media: media.map(({ id, type, url, poster_url, width, height, video_url, video_duration_seconds, video_variant }) => ({
        id,
        type,
        url,
        width,
        height,
        ...(type === 'video' ? {
          poster_url,
          video_url,
          video_duration_seconds,
          video_variant
        } : {})
      }))
    })),
    focal_metrics: {
      views: metricValue(focalMetrics.views),
      likes: metricValue(focalMetrics.likes),
      bookmarks: metricValue(focalMetrics.bookmarks)
    }
  });
}

function sourceOnlyMediaBindings(route, assets) {
  const downloaded = Array.isArray(assets?.media) ? assets.media : [];
  let cursor = 0;
  let globalOrder = 0;
  const units = route.selectedNodes.map(({ node, cleanedText, media }, unitIndex) => {
    const boundMedia = media.map((sourceMedia, mediaIndex) => {
      const asset = downloaded[cursor];
      cursor += 1;
      globalOrder += 1;
      if (!asset
        || String(asset.source_post_id) !== String(node.id)
        || String(asset.id) !== String(sourceMedia.id)
        || asset.type !== sourceMedia.type) {
        throw new Error(`source-only 媒体绑定错位：status ${String(node.id)} media ${String(sourceMedia.id)}`);
      }
      if (!asset.relative_path || !asset.sha256 || !asset.content_type) {
        throw new Error(`source-only 媒体 ${String(sourceMedia.id)} 缺少本地路径、类型或哈希`);
      }
      if (asset.type === 'video') {
        if (!asset.native_video?.relative_path || !asset.native_video?.sha256) {
          throw new Error(`原生视频 ${String(sourceMedia.id)} 缺少已下载 MP4；拒绝只把海报当视频`);
        }
        return {
          order: mediaIndex + 1,
          global_order: globalOrder,
          source_media_id: String(sourceMedia.id),
          kind: 'video',
          path: asset.native_video.relative_path,
          sha256: asset.native_video.sha256,
          bytes: asset.native_video.bytes,
          content_type: asset.native_video.content_type,
          poster: {
            path: asset.relative_path,
            sha256: asset.sha256,
            bytes: asset.bytes,
            content_type: asset.content_type
          },
          markdown_embed: `![原生视频封面](${asset.relative_path})`,
          markdown_marker: `<!-- yichen-native-video: ${asset.native_video.relative_path} -->`
        };
      }
      return {
        order: mediaIndex + 1,
        global_order: globalOrder,
        source_media_id: String(sourceMedia.id),
        kind: 'photo',
        path: asset.relative_path,
        sha256: asset.sha256,
        bytes: asset.bytes,
        content_type: asset.content_type,
        poster: null,
        markdown_embed: `![](${asset.relative_path})`,
        markdown_marker: null
      };
    });
    return {
      order: unitIndex + 1,
      marker: unitIndex === 0 ? null : `Thread${unitIndex + 1}:`,
      status_id: String(node.id),
      text: cleanedText,
      media: boundMedia
    };
  });
  if (cursor !== downloaded.length) {
    throw new Error(`source-only 存在未绑定素材：expected ${cursor}, downloaded ${downloaded.length}`);
  }
  return units;
}

function yamlQuoted(value) {
  return JSON.stringify(String(value));
}

function sourceFenceStateForLine(line, activeFence) {
  const match = String(line).match(SOURCE_FENCE_CANDIDATE_RE);
  if (activeFence) {
    if (!match) return { activeFence, fenced: true };
    const run = match[2];
    const suffix = match[3];
    const closes = run[0] === activeFence.character
      && run.length >= activeFence.length
      && /^\s*$/u.test(suffix);
    return { activeFence: closes ? null : activeFence, fenced: true };
  }
  if (!match) return { activeFence: null, fenced: false };
  const run = match[2];
  const suffix = match[3];
  if (run[0] === '`' && suffix.includes('`')) {
    return { activeFence: null, fenced: false };
  }
  return {
    activeFence: { character: run[0], length: run.length },
    fenced: true
  };
}

export function encodeLiteralMarkerLines(text, { unitOrder, statusId }) {
  const lines = String(text ?? '').split('\n');
  const replacements = [];
  let activeFence = null;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const fenceState = sourceFenceStateForLine(line, activeFence);
    activeFence = fenceState.activeFence;
    if (fenceState.fenced) continue;
    if (LITERAL_MARKER_ENCODED_RE.test(line)) {
      throw new Error(`literal_marker_reserved_syntax:${String(statusId)}:${index + 1}`);
    }
    if (!SOURCE_MARKER_LINE_RE.test(line)) continue;
    const originalLineSha256 = sha256Buffer(Buffer.from(line));
    const encodedLine = `${line}<!-- yichen-literal-marker:v1:${originalLineSha256} -->`;
    replacements.push({
      unit_order: unitOrder,
      status_id: String(statusId),
      line_order: index + 1,
      source_markdown_line: null,
      original_line: line,
      original_line_sha256: originalLineSha256,
      encoded_line: encodedLine
    });
    lines[index] = encodedLine;
  }
  return { text: lines.join('\n'), replacements };
}

function bindLiteralMarkerSourceLines(markdown, replacements) {
  const sourceLines = markdown.split('\n');
  let searchFrom = 0;
  for (const replacement of replacements) {
    const foundAt = sourceLines.findIndex((line, index) => index >= searchFrom && line === replacement.encoded_line);
    if (foundAt < 0) {
      throw new Error(`literal_marker_encoding_missing:${replacement.status_id}:${replacement.line_order}`);
    }
    replacement.source_markdown_line = foundAt + 1;
    searchFrom = foundAt + 1;
  }
}

export function sourceMarkdownForDelivery(status, route, assets) {
  const units = sourceOnlyMediaBindings(route, assets);
  const mode = units.length > 1 ? 'thread' : 'post';
  const parts = [[
    '---',
    `mode: ${mode}`,
    'preserve_text: true',
    'source_kind: x',
    `source_url: ${yamlQuoted(status.canonicalUrl)}`,
    'title_policy: include',
    'source_import: source-import.json',
    '---'
  ].join('\n')];
  const replacements = [];
  for (const unit of units) {
    if (unit.marker) parts.push(unit.marker);
    if (String(unit.text ?? '').trim()) {
      const encoded = encodeLiteralMarkerLines(unit.text, {
        unitOrder: unit.order,
        statusId: unit.status_id
      });
      parts.push(encoded.text);
      replacements.push(...encoded.replacements);
    }
    for (const media of unit.media) {
      parts.push(media.markdown_embed);
      if (media.markdown_marker) parts.push(media.markdown_marker);
    }
  }
  const markdown = parts.join('\n\n') + '\n';
  bindLiteralMarkerSourceLines(markdown, replacements);
  return {
    markdown,
    units,
    literalMarkerEncoding: {
      version: LITERAL_MARKER_ENCODING_VERSION,
      syntax: '<original><!-- yichen-literal-marker:v1:<sha256> -->',
      replacements
    }
  };
}

export function sourceImportForDelivery({ status, normalized, route, assets, literalMarkerEncoding = null, sourceMarkdownSha256, selectedSourceSha256, routingAuditSha256 }) {
  const units = sourceOnlyMediaBindings(route, assets);
  const nativeVideos = units.flatMap((unit) => unit.media).filter((media) => media.kind === 'video');
  const markerEncoding = literalMarkerEncoding ?? sourceMarkdownForDelivery(status, route, assets).literalMarkerEncoding;
  assertNoQuoteMediaCollisions(
    route.selectedNodes.flatMap((selected) => selected.media),
    route.audit,
    'source-import'
  );
  return {
    version: 'yichen-x-slicer-source-import/v1',
    created_at: new Date().toISOString(),
    mode: 'source-only',
    source: {
      kind: 'x',
      url: status.canonicalUrl,
      post_id: status.id,
      backend: normalized.backend,
      retrieved_at: normalized.retrievedAt,
      login_state_used: false
    },
    routed_input_type: route.resolvedInputType,
    title_policy: 'include',
    artificial_title_added: false,
    files: {
      markdown: { path: 'source.md', sha256: sourceMarkdownSha256 },
      selected_source: { path: 'selected-source.json', sha256: selectedSourceSha256 },
      routing_audit: { path: 'routing-audit.json', sha256: routingAuditSha256 },
      assets_directory: 'assets'
    },
    thread_marker: {
      first_unit_implicit: true,
      subsequent_pattern: 'Thread{n}:',
      marker_line_is_exclusive: true
    },
    media_policy: {
      node_order_preserved: true,
      within_node_order_preserved: true,
      native_video_marker: '<!-- yichen-native-video: <relative-mp4-path> -->',
      video_poster_is_preview_only: true,
      native_video_upload_must_use_mp4_path: true
    },
    literal_marker_encoding: markerEncoding,
    units,
    checks: {
      selected_unit_count: units.length,
      bound_media_count: units.reduce((sum, unit) => sum + unit.media.length, 0),
      native_video_count: nativeVideos.length,
      all_native_videos_have_mp4: nativeVideos.every((media) => Boolean(media.path && media.sha256)),
      hashes_match_current_files: null,
      quote_media_collision_count: 0,
      literal_marker_replacement_count: markerEncoding.replacements.length,
      literal_marker_encoding_verified: null,
      no_artificial_title: true
    }
  };
}

function outsideFenceLineRecords(text) {
  const records = [];
  const lines = String(text).split('\n');
  let activeFence = null;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const fenceState = sourceFenceStateForLine(line, activeFence);
    activeFence = fenceState.activeFence;
    if (!fenceState.fenced) records.push({ line, line_number: index + 1 });
  }
  return records;
}

export function assertLiteralMarkerEncodingIntegrity(sourceMarkdown, sourceImport) {
  const encoding = sourceImport.literal_marker_encoding;
  if (!encoding
    || encoding.version !== LITERAL_MARKER_ENCODING_VERSION
    || !Array.isArray(encoding.replacements)) {
    throw new Error('literal_marker_encoding_invalid');
  }
  if (sourceImport.checks.literal_marker_replacement_count !== encoding.replacements.length) {
    throw new Error('literal_marker_encoding_count_mismatch');
  }
  const sourceLines = String(sourceMarkdown).split('\n');
  const encodedSourceLines = outsideFenceLineRecords(sourceMarkdown)
    .filter(({ line }) => LITERAL_MARKER_ENCODED_RE.test(line));
  if (encodedSourceLines.length !== encoding.replacements.length) {
    throw new Error(`literal_marker_encoding_unbound_line:${encodedSourceLines.length}:${encoding.replacements.length}`);
  }
  const usedSourceLines = new Set();
  for (const replacement of encoding.replacements) {
    const unit = sourceImport.units[Number(replacement.unit_order) - 1];
    const originalLine = String(replacement.original_line ?? '');
    const expectedHash = sha256Buffer(Buffer.from(originalLine));
    const expectedEncodedLine = `${originalLine}<!-- yichen-literal-marker:v1:${expectedHash} -->`;
    if (!unit
      || String(unit.status_id) !== String(replacement.status_id)
      || String(unit.text ?? '').split('\n')[Number(replacement.line_order) - 1] !== originalLine
      || replacement.original_line_sha256 !== expectedHash
      || replacement.encoded_line !== expectedEncodedLine
      || !SOURCE_MARKER_LINE_RE.test(originalLine)
      || SOURCE_MARKER_LINE_RE.test(expectedEncodedLine)) {
      throw new Error(`literal_marker_encoding_binding_mismatch:${String(replacement.status_id)}:${String(replacement.line_order)}`);
    }
    const sourceLine = Number(replacement.source_markdown_line);
    if (!Number.isSafeInteger(sourceLine)
      || sourceLine < 1
      || usedSourceLines.has(sourceLine)
      || sourceLines[sourceLine - 1] !== expectedEncodedLine) {
      throw new Error(`literal_marker_encoding_source_line_mismatch:${String(replacement.status_id)}:${String(replacement.line_order)}`);
    }
    usedSourceLines.add(sourceLine);
  }
  sourceImport.checks.literal_marker_encoding_verified = true;
}

function assertSourceOnlyFileIntegrity(outputDirectory, sourceImport) {
  const hashedFiles = [
    sourceImport.files.markdown,
    sourceImport.files.selected_source,
    sourceImport.files.routing_audit
  ];
  for (const record of hashedFiles) {
    const file = safeOutputPath(outputDirectory, record.path);
    if (!fs.statSync(file).isFile() || sha256File(file) !== record.sha256) {
      throw new Error(`source-only 文件哈希不一致：${record.path}`);
    }
  }
  const sourceMarkdown = fs.readFileSync(safeOutputPath(outputDirectory, sourceImport.files.markdown.path), 'utf8');
  assertLiteralMarkerEncodingIntegrity(sourceMarkdown, sourceImport);
  for (const unit of sourceImport.units) {
    for (const media of unit.media) {
      const mediaPath = safeOutputPath(outputDirectory, media.path);
      if (!fs.statSync(mediaPath).isFile() || sha256File(mediaPath) !== media.sha256) {
        throw new Error(`source-only 素材哈希不一致：${media.path}`);
      }
      const mediaBuffer = fs.readFileSync(mediaPath);
      if (media.kind === 'video') {
        if (!supportedMp4Signature(mediaBuffer)) {
          throw new Error(`source-only 原生视频不是有效 MP4：${media.path}`);
        }
      } else {
        const detected = detectImageFormat(mediaBuffer);
        if (!detected
          || detected.extension !== path.extname(media.path).toLowerCase()
          || detected.content_type !== media.content_type) {
          throw new Error(`source-only 图片扩展名或类型与魔数不一致：${media.path}`);
        }
      }
      if (media.poster) {
        const posterPath = safeOutputPath(outputDirectory, media.poster.path);
        if (!fs.statSync(posterPath).isFile() || sha256File(posterPath) !== media.poster.sha256) {
          throw new Error(`source-only 视频海报哈希不一致：${media.poster.path}`);
        }
        const detectedPoster = detectImageFormat(fs.readFileSync(posterPath));
        if (!detectedPoster
          || detectedPoster.extension !== path.extname(media.poster.path).toLowerCase()
          || detectedPoster.content_type !== media.poster.content_type) {
          throw new Error(`source-only 视频海报扩展名或类型与魔数不一致：${media.poster.path}`);
        }
      }
    }
  }
  sourceImport.checks.hashes_match_current_files = true;
}

async function runSourceOnly({ status, normalized, route, outputDirectory }) {
  assertNoQuoteMediaCollisions(
    route.selectedNodes.flatMap((selected) => selected.media),
    route.audit,
    'source-only-pre-download'
  );
  const prepared = await prepareContent(route, outputDirectory, {
    includeNativeVideo: true,
    includeAvatar: false,
    useDetectedMediaExtensions: true
  });
  assertNoQuoteMediaCollisions(
    prepared.assets.media,
    route.audit,
    'source-only-post-download'
  );
  const source = sourceMarkdownForDelivery(status, route, prepared.assets);
  const sourceMarkdownPath = safeOutputPath(outputDirectory, 'source.md');
  fs.writeFileSync(sourceMarkdownPath, source.markdown, { encoding: 'utf8', flag: 'wx' });
  const selectedSourcePath = safeOutputPath(outputDirectory, 'selected-source.json');
  const routingAuditPath = safeOutputPath(outputDirectory, 'routing-audit.json');
  const sourceImport = sourceImportForDelivery({
    status,
    normalized,
    route,
    assets: prepared.assets,
    literalMarkerEncoding: source.literalMarkerEncoding,
    sourceMarkdownSha256: sha256File(sourceMarkdownPath),
    selectedSourceSha256: sha256File(selectedSourcePath),
    routingAuditSha256: sha256File(routingAuditPath)
  });
  assertSourceOnlyFileIntegrity(outputDirectory, sourceImport);
  const sourceImportPath = safeOutputPath(outputDirectory, 'source-import.json');
  fs.writeFileSync(sourceImportPath, JSON.stringify(sourceImport, null, 2) + '\n', { encoding: 'utf8', flag: 'wx' });
  const allMedia = source.units.flatMap((unit) => unit.media);
  const result = {
    status: 'success',
    mode: 'source-only',
    output_directory: outputDirectory,
    routed_input_type: route.resolvedInputType,
    source_markdown: sourceMarkdownPath,
    selected_source: selectedSourcePath,
    routing_audit: routingAuditPath,
    source_import: sourceImportPath,
    unit_count: source.units.length,
    media_count: allMedia.length,
    asset_count: allMedia.reduce((sum, media) => sum + (media.kind === 'video' ? 2 : 1), 0),
    photo_count: allMedia.filter((media) => media.kind === 'photo').length,
    native_video_count: allMedia.filter((media) => media.kind === 'video').length,
    quote_only_exclusions: route.audit.excluded_statuses.filter((statusItem) => statusItem.reason === 'quote_only')
  };
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  return result;
}

export async function run(options) {
  options = { ...options, sourceOnly: options.sourceOnly === true, video: options.video !== false };
  const status = parseStatusUrl(options.url);
  const source = await readSource(options, status);
  const normalized = normalizeSourcePayload(source.payload, status.id);
  const route = routeThread(normalized, source.endpoint);
  if (options.sourceOnly) assertNoSelectedArticleSignals(route);
  if (!route.selectedNodes.length) throw new Error('去除引用内容后没有可生成的正文或自身媒体');
  const requestedOutput = options.output
    ? path.resolve(options.output)
    : path.resolve(process.cwd(), 'outputs', options.sourceOnly
      ? `x-source-${status.id}`
      : `x-post-${status.id}-${options.template}`);
  const outputDirectory = reserveOutputDirectory(requestedOutput);
  fs.writeFileSync(safeOutputPath(outputDirectory, 'selected-source.json'), JSON.stringify(selectedSourceForDelivery(status, normalized, route), null, 2) + '\n', { encoding: 'utf8', flag: 'wx' });
  fs.writeFileSync(safeOutputPath(outputDirectory, 'routing-audit.json'), JSON.stringify(sanitizeRemoteUrlsForPersistence(route.audit), null, 2) + '\n', { encoding: 'utf8', flag: 'wx' });

  if (options.sourceOnly) {
    try {
      return await runSourceOnly({ status, normalized, route, outputDirectory });
    } catch (error) {
      throw new Error(`${error.message}\n诊断目录：${outputDirectory}`);
    }
  }

  const templates = options.template === 'all' ? [...TEMPLATES] : [TEMPLATE_BY_ID.get(options.template)];
  const prepared = await prepareContent(route, outputDirectory, { includeNativeVideo: options.video });
  const outputs = makeOutputs(prepared.contentFrames, templates, outputDirectory);
  const previewSheet = makePreviewFiles(outputs, templates, outputDirectory);
  const coverage = calculateCoverage(outputs, templates, route);
  assertPreRenderIntegrity(route, prepared.contentFrames, coverage);
  const manifest = manifestFor({ options, status, normalized, route, templates, outputs, assets: prepared.assets, previewSheet, coverage, outputDirectory });
  fs.writeFileSync(safeOutputPath(outputDirectory, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n', { encoding: 'utf8', flag: 'wx' });

  let qa;
  let finalZipPath = null;
  let videoRecords = [];
  try {
    qa = await renderAndInspect(outputs, previewSheet, outputDirectory, coverage);
    if (qa.failures.length) throw new Error(`程序验收未通过：${qa.failures.length} 张存在问题`);
    const zip = createAndVerifyZip(outputs, templates.map((template) => template.id), outputDirectory);
    finalZipPath = zip.path;
    const { path: ignoredAbsoluteZipPath, ...zipRecord } = zip;
    qa.zip = zipRecord;
    if (!zip.entry_set_matches || !zip.entries_only_numbered_pngs || !zip.hashes_match || zip.entry_count !== outputs.length) {
      qa.failures.push({ base: 'zip', problems: ['压缩包内容或哈希不一致'] });
      throw new Error('压缩包内容或哈希不一致');
    }
    manifest.zip = { file: zip.file, count: zip.entry_count, sha256: zip.sha256 };
    if (options.video) {
      videoRecords = renderVideos({ outputs, templates, outputDirectory });
      qa.videos = videoRecords;
      manifest.video.outputs = videoRecords;
    }
    manifest.outputs = outputs.map(serializableOutput);
    manifest.qa = { pass: true, rendered_count: qa.rendered.length, failure_count: 0 };
    fs.writeFileSync(safeOutputPath(outputDirectory, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n', 'utf8');
    fs.writeFileSync(safeOutputPath(outputDirectory, 'qa-report.json'), JSON.stringify({ ...qa, pass: true }, null, 2) + '\n', { encoding: 'utf8', flag: 'wx' });
  } catch (error) {
    qa ??= {
      version: 'yichen-x-slicer-qa/v3',
      created_at: new Date().toISOString(),
      canvas: CANVAS,
      coverage,
      rendered: [],
      failures: []
    };
    if (!qa.failures.length) qa.failures.push({ base: 'run', problems: [error.message] });
    manifest.qa = { pass: false, rendered_count: qa.rendered.length, failure_count: qa.failures.length };
    fs.writeFileSync(safeOutputPath(outputDirectory, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n', 'utf8');
    fs.writeFileSync(safeOutputPath(outputDirectory, 'qa-report.json'), JSON.stringify({ ...qa, pass: false }, null, 2) + '\n', { encoding: 'utf8', flag: 'wx' });
    throw new Error(`${error.message}\n诊断目录：${outputDirectory}`);
  }

  const result = {
    status: 'success',
    output_directory: outputDirectory,
    routed_input_type: route.resolvedInputType,
    template_requested: options.template,
    templates: templates.map((template) => template.id),
    default_template_used: options.template === DEFAULT_TEMPLATE,
    frame_count: outputs.length,
    text_frame_count: outputs.filter((output) => output.kind === 'text').length,
    media_frame_count: outputs.filter((output) => output.kind === 'media').length,
    native_video_frame_count: outputs.filter((output) => output.kind === 'media' && output.media.type === 'video').length,
    quote_frame_count: 0,
    quote_only_exclusions: route.audit.excluded_statuses.filter((statusItem) => statusItem.reason === 'quote_only'),
    index: path.join(outputDirectory, 'index.html'),
    contact_sheet: path.join(outputDirectory, 'contact-sheet.png'),
    zip: finalZipPath,
    qa: safeOutputPath(outputDirectory, 'qa-report.json')
  };
  if (options.video) {
    result.video_profile = VIDEO_PROFILE.id;
    result.video_count = videoRecords.length;
    result.videos = videoRecords.map((record) => path.join(outputDirectory, record.file));
  }
  process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  return result;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    printHelp();
    return;
  }
  if (options.listTemplates) {
    process.stdout.write(listTemplatesText());
    return;
  }
  if (!options.url) throw new Error('缺少 --url');
  await run(options);
}

export function isDirectExecution(argvPath, moduleUrl = import.meta.url) {
  if (!argvPath) return false;
  try {
    const argvRealPath = fs.realpathSync(path.resolve(argvPath));
    const moduleRealPath = fs.realpathSync(fileURLToPath(moduleUrl));
    return argvRealPath === moduleRealPath;
  } catch {
    return moduleUrl === pathToFileURL(path.resolve(argvPath)).href;
  }
}

const isDirectRun = isDirectExecution(process.argv[1]);
if (isDirectRun) {
  main().catch((error) => {
    process.stderr.write(`错误：${error.message}\n`);
    process.exitCode = 1;
  });
}
