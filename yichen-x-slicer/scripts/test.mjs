#!/usr/bin/env node

import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  DEFAULT_TEMPLATE,
  TEMPLATES,
  assertLiteralMarkerEncodingIntegrity,
  assertNoQuoteMediaCollisions,
  assertNoSelectedArticleSignals,
  deriveHook,
  detectImageFormat,
  encodeLiteralMarkerLines,
  formatMetric,
  isDirectExecution,
  manifestFor,
  materializeAsset,
  materializeSourceImage,
  materializeVideoAsset,
  normalizeSourcePayload,
  normalizeText,
  ownMedia,
  parseArgs,
  parseStatusUrl,
  quoteMediaCollisionAudit,
  removeQuoteStatusUrl,
  routeThread,
  run,
  sanitizeRemoteUrlsForPersistence,
  selectNativeVideoVariant,
  selectedSourceForDelivery,
  sourceImportForDelivery,
  sourceMarkdownForDelivery,
  splitText
} from './yichen_x_slicer.mjs';
import {
  VIDEO_PROFILE,
  assertSilentVideoRuntime,
  buildReadingStabilityFilter,
  buildVideoFilter,
  buildVideoOutputArgs,
  buildVideoPlan,
  isNativeVideoOutput,
  parseReadingSsimStats,
  probeNativeVideoSource,
  readingStabilityPairIndices,
  renderVideos,
  sampleRangeCoveredByUnion,
  videoFramesForDuration,
  videoFramesForOutput
} from './silent_video.mjs';

const author = Object.freeze({ id: 'author-1', name: '作者甲', screen_name: 'writer' });
const otherAuthor = Object.freeze({ id: 'author-2', name: '作者乙', screen_name: 'reader' });
const deprecatedPaceLabel = new RegExp([
  ['3', 'x'].join(''),
  ['三', '倍', '速'].join(''),
  ['stable', 'fast'].join('-')
].join('|'), 'iu');
const localFfmpeg = process.env.YICHEN_X_SLICER_FFMPEG || 'ffmpeg';
const localFfprobe = process.env.YICHEN_X_SLICER_FFPROBE || 'ffprobe';
const integrationTemplate = Object.freeze({ id: 'integration', name: 'FFmpeg 集成测试版' });

function runLocalCommand(command, args) {
  const result = spawnSync(command, args, {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} 集成测试命令失败：${String(result.stderr ?? '').trim()}`);
  }
  return result.stdout;
}

function integrationDirectory(label) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `yichen-x-slicer-${label}-`));
}

function writeFixturePng(directory, file, color) {
  const target = path.join(directory, file);
  runLocalCommand(localFfmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-f', 'lavfi', '-i', `color=c=${color}:s=1080x1440:r=30:d=0.04`,
    '-frames:v', '1', '-threads', '1', '-c:v', 'png',
    target
  ]);
  return target;
}

function writePositiveOffsetFixture(directory, relativePath) {
  const target = path.join(directory, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  runLocalCommand(localFfmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=1.8',
    '-itsoffset', '0.6',
    '-f', 'lavfi', '-i', 'sine=frequency=740:sample_rate=48000:duration=0.6',
    '-map', '0:v:0', '-map', '1:a:0',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '128k',
    '-t', '1.8', '-avoid_negative_ts', 'disabled', '-movflags', '+faststart',
    target
  ]);
  return target;
}

function writeNegativeOffsetFixture(directory, relativePath) {
  const target = path.join(directory, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  runLocalCommand(localFfmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-itsoffset', '0.3',
    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=1.5',
    '-f', 'lavfi', '-i', 'sine=frequency=980:sample_rate=48000:duration=1.2',
    '-map', '0:v:0', '-map', '1:a:0',
    // Preserve the delayed first video frame instead of duplicating it to t=0.
    '-fps_mode:v', 'passthrough',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '128k',
    '-t', '1.8', '-avoid_negative_ts', 'disabled', '-movflags', '+faststart',
    target
  ]);
  return target;
}

function writeSilentVideoFixture(directory, relativePath) {
  const target = path.join(directory, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  runLocalCommand(localFfmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=1',
    '-map', '0:v:0',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-an', '-movflags', '+faststart',
    target
  ]);
  return target;
}

function writeTwoAudioTrackFixture(directory, relativePath) {
  const target = path.join(directory, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  runLocalCommand(localFfmpeg, [
    '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=1',
    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
    '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=1',
    '-map', '0:v:0', '-map', '1:a:0', '-map', '2:a:0',
    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart',
    target
  ]);
  return target;
}

function ffprobeFixture(file) {
  return JSON.parse(runLocalCommand(localFfprobe, [
    '-v', 'error',
    '-show_entries', 'format=duration:stream=index,codec_name,codec_type,start_time,duration,nb_frames,sample_rate,channels',
    '-of', 'json',
    file
  ]));
}

function nativeVideoOutput(order, pngFile, relativePath) {
  return {
    template_id: integrationTemplate.id,
    order,
    kind: 'media',
    png_file: pngFile,
    media: {
      type: 'video',
      native_video_requested: true,
      native_video: { relative_path: relativePath }
    },
    media_layout: { x: 180, y: 500, width: 720, height: 406 }
  };
}

function post(id, text, options = {}) {
  return {
    id: String(id),
    text,
    created_at: options.createdAt ?? `2026-08-05T00:00:${String(Number(id) % 60).padStart(2, '0')}Z`,
    author: options.author ?? author,
    replying_to: options.replyTo ? {
      status: String(options.replyTo),
      screen_name: options.replyHandle ?? 'writer'
    } : null,
    quote: options.quoteId ? {
      id: String(options.quoteId),
      text: options.quoteText ?? '这段引用内容绝不能输出',
      media: { all: [{ id: 'quote-media', type: 'photo', url: 'https://quote.invalid/image.jpg', width: 800, height: 800 }] }
    } : null,
    media: { all: options.media ?? [] },
    views: 12345,
    likes: 88,
    bookmarks: 66
  };
}

function normalizeFixture(focal, thread = [focal]) {
  return normalizeSourcePayload({ status: focal, thread }, String(focal.id));
}

function ids(route) {
  return route.selectedNodes.map(({ node }) => String(node.id));
}

const tests = [];
function test(name, callback) {
  tests.push({ name, callback });
}

test('默认模板为落日琥珀版', () => {
  assert.equal(DEFAULT_TEMPLATE, 'sunset');
  const parsed = parseArgs(['--url', 'https://x.com/writer/status/100', '--output', '/tmp/example']);
  assert.equal(parsed.template, 'sunset');
  assert.equal(parsed.video, true);
  assert.equal(parsed.sourceOnly, false);
});

test('source-only 是隔离的轻量来源模式', () => {
  const parsed = parseArgs([
    '--url', 'https://x.com/writer/status/100',
    '--source-only',
    '--output', '/tmp/example-source'
  ]);
  assert.equal(parsed.sourceOnly, true);
  assert.equal(parsed.video, true);
  assert.throws(
    () => parseArgs(['--url', 'https://x.com/writer/status/100', '--source-only', '--images-only']),
    /不能与 --video 或 --images-only 同时使用/u
  );
  assert.throws(
    () => parseArgs(['--url', 'https://x.com/writer/status/100', '--source-only', '--video']),
    /不能与 --video 或 --images-only 同时使用/u
  );
});

test('默认追加成片，只有显式 --images-only 才关闭', () => {
  assert.equal(VIDEO_PROFILE.id, 'fixed-reading-v1');
  assert.doesNotMatch(JSON.stringify(VIDEO_PROFILE), deprecatedPaceLabel);
  const parsed = parseArgs(['--url', 'https://x.com/writer/status/100', '--template', 'all']);
  assert.equal(parsed.video, true);
  assert.equal(parsed.template, 'all');
  assert.equal(parseArgs(['--url', 'https://x.com/writer/status/100', '--images-only']).video, false);
  assert.equal(parseArgs(['--url', 'https://x.com/writer/status/100', '--video']).video, true);
  assert.throws(
    () => parseArgs(['--url', 'https://x.com/writer/status/100', '--video', '--images-only']),
    /不能同时使用/u
  );
  const outputs = [
    { template_id: 'sunset', order: 2, kind: 'media', png_file: '02-sunset-media.png' },
    { template_id: 'editorial', order: 1, kind: 'text', text: '乙', png_file: '01-editorial-text.png' },
    { template_id: 'sunset', order: 1, kind: 'text', text: '甲', png_file: '01-sunset-text.png' }
  ];
  const sunsetPlan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' });
  const editorialPlan = buildVideoPlan(outputs, { id: 'editorial', name: '暖白编辑版' });
  assert.deepEqual(sunsetPlan.slides.map(({ png_file }) => png_file), ['01-sunset-text.png', '02-sunset-media.png']);
  assert.deepEqual(editorialPlan.slides.map(({ png_file }) => png_file), ['01-editorial-text.png']);
  assert.equal(sunsetPlan.file, 'video-sunset.mp4');
  assert.equal(sunsetPlan.filter_file, 'video-sunset-filter.txt');
  assert.doesNotMatch(JSON.stringify([sunsetPlan.file, sunsetPlan.filter_file]), deprecatedPaceLabel);
});

test('固定阅读节奏帧数公式严格按 JavaScript text.length 计算', () => {
  for (const [length, expected] of [[0, 54], [213, 54], [214, 55], [308, 69], [309, 70], [800, 70]]) {
    assert.equal(videoFramesForOutput({ kind: 'text', text: '字'.repeat(length) }), expected);
  }
  assert.equal(videoFramesForOutput({ kind: 'text', text: '😀'.repeat(107) }), 55);
  assert.equal('😀'.repeat(107).length, 214);
  assert.equal(videoFramesForOutput({ kind: 'media' }), 40);
  assert.throws(() => videoFramesForOutput({ kind: 'quote' }), /不支持的帧类型/u);
  assert.equal(videoFramesForDuration(2620 / 30), 2620);
  assert.equal(videoFramesForDuration(0.066667), 2);
  assert.equal(videoFramesForDuration(1.033333), 31);
  assert.equal(videoFramesForDuration(1.0001), 31);
  assert.equal(sampleRangeCoveredByUnion(
    { start_sample: 1000, end_sample: 2500 },
    [{ start_sample: 500, end_sample: 2000 }, { start_sample: 1500, end_sample: 3000 }]
  ), true);
  assert.equal(sampleRangeCoveredByUnion(
    { start_sample: 1000, end_sample: 2500 },
    [{ start_sample: 500, end_sample: 1499 }, { start_sample: 1500, end_sample: 3000 }]
  ), false);
});

test('九页黄金样本固定为 492 帧与 16.4 秒', () => {
  const lengths = [301, 262, 276, 283, 244, 215, 209, 228];
  const outputs = lengths.map((length, index) => ({
    template_id: 'sunset',
    order: index + 1,
    kind: 'text',
    text: '字'.repeat(length),
    png_file: `${String(index + 1).padStart(2, '0')}-sunset-text.png`
  }));
  outputs.push({ template_id: 'sunset', order: 9, kind: 'media', png_file: '09-sunset-media.png' });
  const plan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' });
  assert.deepEqual(plan.slides.map(({ frames }) => frames), [68, 62, 64, 65, 59, 55, 54, 57, 40]);
  assert.equal(plan.slides.reduce((sum, slide) => sum + slide.frames, 0), 524);
  assert.equal(plan.transition_count, 8);
  assert.equal(plan.total_frames, 492);
  assert.equal(plan.duration_seconds, 16.4);
});

test('视频滤镜只在四帧换页窗口运动，阅读期没有几何动画', () => {
  const outputs = [
    { template_id: 'sunset', order: 1, kind: 'text', text: '字'.repeat(301), png_file: '01.png' },
    { template_id: 'sunset', order: 2, kind: 'text', text: '字'.repeat(262), png_file: '02.png' },
    { template_id: 'sunset', order: 3, kind: 'media', png_file: '03.png' }
  ];
  const plan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' });
  const filter = buildVideoFilter(plan);
  assert.equal((filter.match(/xfade=/gu) ?? []).length, 2);
  assert.equal((filter.match(/duration=0\.133333/gu) ?? []).length, 2);
  assert.match(filter, /format=yuv420p\[v0\]/u);
  assert.doesNotMatch(filter, /format=yuv420p,\[/u);
  for (const forbidden of ['zoompan', 'scale=', 'crop=', 'rotate=', 'transpose=', 'perspective=', 'pad=']) {
    assert(!filter.includes(forbidden), `不应包含 ${forbidden}`);
  }
  const args = buildVideoOutputArgs(plan, '/tmp/output.mp4');
  assert(args.includes('-an'));
  assert.equal(args[args.indexOf('-frames:v') + 1], String(plan.total_frames));
  assert.equal(args[args.indexOf('-r') + 1], '30');
  assert.equal(args[args.indexOf('-c:v') + 1], 'libx264');
  assert.equal(args[args.indexOf('-g') + 1], String(plan.total_frames + 1));
  assert.equal(args[args.indexOf('-keyint_min') + 1], String(plan.total_frames + 1));
  assert.equal(args[args.indexOf('-sc_threshold') + 1], '0');
});

test('视频 QA 排除转场后逐对检查所有阅读区相邻帧', () => {
  const outputs = [
    { template_id: 'sunset', order: 1, kind: 'text', text: '字'.repeat(301), png_file: '01.png' },
    { template_id: 'sunset', order: 2, kind: 'text', text: '字'.repeat(262), png_file: '02.png' },
    { template_id: 'sunset', order: 3, kind: 'media', png_file: '03.png' }
  ];
  const plan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' });
  const indices = readingStabilityPairIndices(plan);
  assert.deepEqual(indices.transition, [65, 66, 67, 68, 123, 124, 125, 126]);
  assert.equal(indices.stable.length + indices.transition.length, plan.total_frames - 1);
  assert.match(buildReadingStabilityFilter(plan), /ssim=stats_file=-/u);
  const stats = Array.from({ length: plan.total_frames - 1 }, (_, index) => (
    `n:${index + 1} Y:1.000000 U:1.000000 V:1.000000 All:${index === 20 ? '0.999950' : '1.000000'} (inf)`
  )).join('\n');
  const audit = parseReadingSsimStats(stats, plan);
  assert.equal(audit.pass, true);
  assert.equal(audit.minimum_adjacent_reading_ssim, 0.99995);
  const failing = stats.replace('n:21 Y:1.000000 U:1.000000 V:1.000000 All:0.999950', 'n:21 Y:1.000000 U:1.000000 V:1.000000 All:0.998000');
  assert.throws(() => parseReadingSsimStats(failing, plan), /阅读区出现画面变化/u);
});

test('原生视频页使用混合输入并完整保留实际视觉帧数', () => {
  const nativeOutput = {
    template_id: 'sunset',
    order: 2,
    kind: 'media',
    png_file: '02-video-poster.png',
    media: {
      type: 'video',
      native_video: { relative_path: 'assets/source.mp4' }
    },
    media_layout: { x: 116, y: 296, width: 848, height: 952 }
  };
  assert.equal(isNativeVideoOutput(nativeOutput), true);
  const outputs = [
    { template_id: 'sunset', order: 1, kind: 'text', text: '字'.repeat(287), png_file: '01-text.png' },
    nativeOutput
  ];
  const probe = {
    decode_pass: true,
    audio_decode_pass: true,
    audio_stream_count: 1,
    audio_streams: [{ codec: 'aac', sample_rate: 48000, channels: 2, duration_seconds: 87.333333, start_time_seconds: 0.7 }],
    video_start_time_seconds: 0.5,
    audio_offset_from_video_seconds: 0.2,
    embedded_frames: 2620,
    source_duration_seconds: 87.333333,
    embedded_duration_seconds: 87.333333
  };
  const plan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' }, {
    nativeVideoProbes: new Map([['assets/source.mp4', probe]])
  });
  assert.deepEqual(plan.slides.map(({ frames }) => frames), [66, 2620]);
  assert.equal(plan.total_frames, 2682);
  assert.equal(plan.duration_seconds, 89.4);
  assert.equal(plan.input_count, 3);
  assert.equal(plan.native_video_count, 1);
  assert.equal(plan.source_audio_video_count, 1);
  assert.equal(plan.slides[0].background_input_index, 0);
  assert.equal(plan.slides[1].background_input_index, 1);
  assert.equal(plan.slides[1].native_video_input_index, 2);
  const filter = buildVideoFilter(plan);
  assert.match(filter, /\[2:v\]fps=30/u);
  assert.match(filter, /scale=w=848:h=952:force_original_aspect_ratio=decrease/u);
  assert.match(filter, /overlay=x=116\+\(848-overlay_w\)\/2:y=296\+\(952-overlay_h\)\/2/u);
  assert.match(filter, /\[2:a:0\]asetpts=PTS-\(0\.500000000\/TB\),aresample=48000/u);
  assert.match(filter, /atrim=end_sample=4192000,apad=whole_len=4192000,atrim=end_sample=4192000/u);
  assert.match(filter, /anullsrc=r=48000:cl=stereo/u);
  assert.match(filter, /acrossfade=ns=6400/u);
  assert.match(filter, /\[audio_timeline\]atrim=end_sample=4291200,apad=whole_len=4291200,atrim=end_sample=4291200/u);
  const outputArgs = buildVideoOutputArgs(plan, '/tmp/native-audio.mp4');
  assert(!outputArgs.includes('-an'));
  assert.equal(outputArgs[outputArgs.indexOf('-c:a') + 1], 'aac');
  assert.equal(outputArgs[outputArgs.indexOf('-b:a') + 1], '192k');
  assert(outputArgs.includes('[aout]'));
  const indices = readingStabilityPairIndices(plan);
  assert.equal(indices.transition.length, 4);
  assert.equal(indices.dynamic_native_video.length, 2615);
  assert.equal(indices.stable.length, 62);
  assert.equal(indices.transition.length + indices.dynamic_native_video.length + indices.stable.length, plan.total_frames - 1);
  const stats = Array.from({ length: plan.total_frames - 1 }, (_, index) => (
    `n:${index + 1} Y:1.000000 U:1.000000 V:1.000000 All:1.000000 (inf)`
  )).join('\n');
  const audit = parseReadingSsimStats(stats, plan);
  assert.equal(audit.dynamic_native_video_pair_count, 2615);
  assert.equal(audit.stable_pair_count, 62);
});

test('原生视频没有源音轨时最终不创建空白音轨', () => {
  const output = {
    template_id: 'sunset',
    order: 1,
    kind: 'media',
    png_file: '01-video-poster.png',
    media: { type: 'video', native_video: { relative_path: 'assets/silent-source.mp4' } },
    media_layout: { x: 116, y: 296, width: 848, height: 952 }
  };
  const plan = buildVideoPlan([output], { id: 'sunset', name: '落日琥珀版' }, {
    nativeVideoProbes: new Map([['assets/silent-source.mp4', {
      decode_pass: true,
      audio_decode_pass: true,
      audio_stream_count: 0,
      audio_streams: [],
      embedded_frames: 90,
      source_duration_seconds: 3,
      embedded_duration_seconds: 3
    }]])
  });
  assert.equal(plan.source_audio_video_count, 0);
  assert(!buildVideoFilter(plan).includes('anullsrc='));
  const outputArgs = buildVideoOutputArgs(plan, '/tmp/no-source-audio.mp4');
  assert(outputArgs.includes('-an'));
  assert(!outputArgs.includes('[aout]'));
});

test('多个原生视频的原声按真实输入索引与页面转场拼成一条时间轴', () => {
  const videoOutput = (order, relativePath, pngFile) => ({
    template_id: 'sunset',
    order,
    kind: 'media',
    png_file: pngFile,
    media: { type: 'video', native_video: { relative_path: relativePath } },
    media_layout: { x: 116, y: 296, width: 848, height: 952 }
  });
  const audioProbe = (frames, duration) => ({
    decode_pass: true,
    audio_decode_pass: true,
    audio_stream_count: 1,
    audio_streams: [{ codec: 'aac', sample_rate: 48000, channels: 2, duration_seconds: duration, start_time_seconds: 0 }],
    video_start_time_seconds: 0,
    audio_offset_from_video_seconds: 0,
    embedded_frames: frames,
    source_duration_seconds: duration,
    embedded_duration_seconds: duration
  });
  const outputs = [
    { template_id: 'sunset', order: 1, kind: 'text', text: '正文', png_file: '01-text.png' },
    videoOutput(2, 'assets/first.mp4', '02-video.png'),
    { template_id: 'sunset', order: 3, kind: 'media', png_file: '03-photo.png' },
    videoOutput(4, 'assets/second.mp4', '04-video.png')
  ];
  const plan = buildVideoPlan(outputs, { id: 'sunset', name: '落日琥珀版' }, {
    nativeVideoProbes: new Map([
      ['assets/first.mp4', audioProbe(60, 2)],
      ['assets/second.mp4', audioProbe(90, 3)]
    ])
  });
  assert.deepEqual(plan.slides.map(({ background_input_index, native_video_input_index }) => [background_input_index, native_video_input_index ?? null]), [
    [0, null], [1, 2], [3, null], [4, 5]
  ]);
  assert.equal(plan.input_count, 6);
  assert.equal(plan.source_audio_video_count, 2);
  assert.equal(plan.total_frames, 232);
  const filter = buildVideoFilter(plan);
  assert.match(filter, /\[2:a:0\]asetpts=/u);
  assert.match(filter, /\[5:a:0\]asetpts=/u);
  assert.equal((filter.match(/acrossfade=ns=6400/gu) ?? []).length, 3);
  assert.match(filter, /\[audio_timeline\]atrim=end_sample=371200,apad=whole_len=371200/u);
});

test('真实 FFmpeg 混合时间轴保留正负音画偏移并验证静音前后区间', () => {
  assertSilentVideoRuntime({ ffmpeg: localFfmpeg, ffprobe: localFfprobe });
  const directory = integrationDirectory('mixed-audio-e2e');
  writeFixturePng(directory, '01-static.png', '0x152033');
  writeFixturePng(directory, '02-positive-video.png', '0x573226');
  writeFixturePng(directory, '03-photo.png', '0x244f3c');
  writeFixturePng(directory, '04-negative-video.png', '0x392753');
  writePositiveOffsetFixture(directory, 'assets/positive-audio.mp4');
  writeNegativeOffsetFixture(directory, 'assets/negative-audio.mp4');

  const positiveProbe = probeNativeVideoSource({
    outputDirectory: directory,
    relativePath: 'assets/positive-audio.mp4',
    ffmpeg: localFfmpeg,
    ffprobe: localFfprobe
  });
  const negativeProbe = probeNativeVideoSource({
    outputDirectory: directory,
    relativePath: 'assets/negative-audio.mp4',
    ffmpeg: localFfmpeg,
    ffprobe: localFfprobe
  });
  assert.equal(positiveProbe.video_stream_count, 1);
  assert.equal(positiveProbe.audio_stream_count, 1);
  assert.equal(positiveProbe.decode_pass, true);
  assert.equal(positiveProbe.audio_decode_pass, true);
  assert(positiveProbe.audio_offset_from_video_seconds > 0.5);
  assert(positiveProbe.audio_streams[0].duration_seconds < positiveProbe.source_duration_seconds);
  assert(positiveProbe.audio_offset_from_video_seconds + positiveProbe.audio_streams[0].duration_seconds
    < positiveProbe.source_duration_seconds - 0.5);
  assert.equal(negativeProbe.video_stream_count, 1);
  assert.equal(negativeProbe.audio_stream_count, 1);
  assert.equal(negativeProbe.decode_pass, true);
  assert(negativeProbe.audio_offset_from_video_seconds < -0.25);

  const outputs = [
    {
      template_id: integrationTemplate.id,
      order: 1,
      kind: 'text',
      text: '静态正文',
      png_file: '01-static.png'
    },
    nativeVideoOutput(2, '02-positive-video.png', 'assets/positive-audio.mp4'),
    {
      template_id: integrationTemplate.id,
      order: 3,
      kind: 'media',
      png_file: '03-photo.png',
      media: { type: 'photo' }
    },
    nativeVideoOutput(4, '04-negative-video.png', 'assets/negative-audio.mp4')
  ];
  const [record] = renderVideos({
    outputs,
    templates: [integrationTemplate],
    outputDirectory: directory,
    ffmpeg: localFfmpeg,
    ffprobe: localFfprobe
  });
  assert.deepEqual(record.slide_frames, [54, 54, 40, 45]);
  assert.equal(record.transition_count, 3);
  assert.equal(record.total_frames, 181);
  assert.equal(record.duration_seconds, 181 / 30);
  assert.equal(record.source_audio_video_count, 2);
  assert.equal(record.source_audio_preserved, true);
  assert.equal(record.checks.pass, true);
  assert.equal(record.checks.video_stream_count, 1);
  assert.equal(record.checks.audio_stream_count, 1);
  assert.equal(record.checks.frame_count, record.total_frames);
  assert(Math.abs(record.checks.duration_seconds - record.duration_seconds) < 0.001);
  assert.equal(record.checks.final_audio_matches_source_presence, true);
  assert.equal(record.checks.audio.source_audio_video_count, 2);
  assert.equal(record.checks.audio.all_source_audio_preserved, true);
  assert.equal(record.checks.audio.timeline_checks.length, 2);
  assert.equal(record.checks.audio.transition_timeline_checks.length, 3);
  assert(record.checks.audio.transition_timeline_checks.every((check) => check.pass));
  assert(record.checks.audio.transition_timeline_checks.some((check) => check.expected_audible));
  assert(record.checks.audio.timeline_checks.every((check) => (
    check.pass && check.source_audio_preserved && check.timeline_aligned && check.sample_count >= 1
  )));
  assert.equal(record.checks.native_video.count, 2);
  assert.equal(record.checks.native_video.all_source_videos_decode_pass, true);
  assert.equal(record.checks.native_video.all_visual_durations_preserved, true);
  assert.equal(record.checks.native_video.embedded_frame_checks.length, 2);
  const silenceQa = record.checks.audio.non_source_intervals;
  assert.equal(silenceQa.pass, true);
  assert.equal(silenceQa.coverage_complete, true);
  assert.equal(silenceQa.total_timeline_samples, record.total_frames * 1600);
  assert.equal(silenceQa.checked_samples, silenceQa.expected_complement_samples);
  assert.equal(
    silenceQa.permitted_source_audio_samples + silenceQa.strict_silent_samples + silenceQa.boundary_band_samples,
    silenceQa.total_timeline_samples
  );
  assert(silenceQa.boundary_audits.every((check) => check.pass));
  assert(silenceQa.checks.filter((check) => check.verification === 'bounded_aac_boundary_expected_timeline')
    .every((check) => check.sample_count <= 2 * VIDEO_PROFILE.audioCodecBoundarySamples));
  assert.equal(silenceQa.permitted_source_audio_ranges.length, 2);
  assert(silenceQa.checks.every((check) => check.silent || check.bounded_codec_boundary));
  const positiveRange = silenceQa.permitted_source_audio_ranges.find((range) => (
    range.sources.includes('assets/positive-audio.mp4')
  ));
  const negativeRange = silenceQa.permitted_source_audio_ranges.find((range) => (
    range.sources.includes('assets/negative-audio.mp4')
  ));
  assert(positiveRange.start_sample > 50 * 1600 + 0.5 * 48000);
  assert(positiveRange.end_sample < (50 + 54) * 1600 - 0.5 * 48000);
  assert.equal(negativeRange.start_sample, 136 * 1600);
  assert(negativeRange.end_sample < (136 + 45) * 1600);
  const silenceCoversSample = (sample) => silenceQa.checks.some((check) => (
    check.start_sample <= sample && sample < check.end_sample
  ));
  assert(silenceCoversSample(20 * 1600));
  assert(silenceCoversSample(120 * 1600));
  assert(silenceCoversSample(positiveRange.start_sample - 1));
  assert(silenceCoversSample(positiveRange.end_sample));

  const finalProbe = ffprobeFixture(path.join(directory, record.file));
  assert.equal(finalProbe.streams.filter((stream) => stream.codec_type === 'video').length, 1);
  assert.equal(finalProbe.streams.filter((stream) => stream.codec_type === 'audio').length, 1);
  assert.equal(Number(finalProbe.streams.find((stream) => stream.codec_type === 'video').nb_frames), 181);
  assert(Math.abs(Number(finalProbe.format.duration) - 181 / 30) < 0.01);
  assert.equal(record.runtime_provenance.version, 'yichen-x-slicer-runtime-provenance/v1');
  assert.deepEqual(
    record.runtime_provenance.files.map((entry) => entry.file),
    ['scripts/silent_video.mjs', 'scripts/yichen_x_slicer.mjs', 'scripts/test.mjs', 'SKILL.md']
  );
});

test('真实 FFmpeg 无声源视频生成零音频流并保留完整视觉 QA', () => {
  const directory = integrationDirectory('silent-source-e2e');
  writeFixturePng(directory, '01-silent-video.png', '0x28384d');
  writeSilentVideoFixture(directory, 'assets/silent-source.mp4');
  const sourceProbe = probeNativeVideoSource({
    outputDirectory: directory,
    relativePath: 'assets/silent-source.mp4',
    ffmpeg: localFfmpeg,
    ffprobe: localFfprobe
  });
  assert.equal(sourceProbe.video_stream_count, 1);
  assert.equal(sourceProbe.audio_stream_count, 0);
  assert.equal(sourceProbe.source_audio_present, false);
  assert.deepEqual(sourceProbe.audio_streams, []);
  assert.equal(sourceProbe.embedded_frames, 30);

  const [record] = renderVideos({
    outputs: [nativeVideoOutput(1, '01-silent-video.png', 'assets/silent-source.mp4')],
    templates: [integrationTemplate],
    outputDirectory: directory,
    ffmpeg: localFfmpeg,
    ffprobe: localFfprobe
  });
  assert.equal(record.total_frames, 30);
  assert.equal(record.duration_seconds, 1);
  assert.equal(record.source_audio_video_count, 0);
  assert.equal(record.audio, null);
  assert.equal(record.checks.pass, true);
  assert.equal(record.checks.video_stream_count, 1);
  assert.equal(record.checks.audio_stream_count, 0);
  assert.equal(record.checks.final_audio_matches_source_presence, true);
  assert.equal(record.checks.audio, null);
  assert.equal(record.checks.native_video.count, 1);
  assert.equal(record.checks.native_video.all_source_videos_decode_pass, true);
  assert.equal(record.checks.native_video.all_visual_durations_preserved, true);
  assert.equal(record.checks.native_video.embedded_frame_checks.length, 1);
  const finalProbe = ffprobeFixture(path.join(directory, record.file));
  assert.equal(finalProbe.streams.filter((stream) => stream.codec_type === 'video').length, 1);
  assert.equal(finalProbe.streams.filter((stream) => stream.codec_type === 'audio').length, 0);
  assert.equal(Number(finalProbe.streams.find((stream) => stream.codec_type === 'video').nb_frames), 30);
  assert(Math.abs(Number(finalProbe.format.duration) - 1) < 0.01);
});

test('真实 FFmpeg 双音轨源在探测和渲染入口都 fail closed', () => {
  const directory = integrationDirectory('two-audio-tracks-e2e');
  writeFixturePng(directory, '01-two-audio-tracks.png', '0x4d2525');
  writeTwoAudioTrackFixture(directory, 'assets/two-audio-tracks.mp4');
  const rawProbe = ffprobeFixture(path.join(directory, 'assets/two-audio-tracks.mp4'));
  assert.equal(rawProbe.streams.filter((stream) => stream.codec_type === 'video').length, 1);
  assert.equal(rawProbe.streams.filter((stream) => stream.codec_type === 'audio').length, 2);
  assert.throws(
    () => probeNativeVideoSource({
      outputDirectory: directory,
      relativePath: 'assets/two-audio-tracks.mp4',
      ffmpeg: localFfmpeg,
      ffprobe: localFfprobe
    }),
    /音轨数量超过 1/u
  );
  assert.throws(
    () => renderVideos({
      outputs: [nativeVideoOutput(1, '01-two-audio-tracks.png', 'assets/two-audio-tracks.mp4')],
      templates: [integrationTemplate],
      outputDirectory: directory,
      ffmpeg: localFfmpeg,
      ffprobe: localFfprobe
    }),
    /音轨数量超过 1/u
  );
});

test('单页视频不创建转场，缺少本地视频运行时会 fail closed', () => {
  const plan = buildVideoPlan([
    { template_id: 'sunset', order: 1, kind: 'text', text: '正文', png_file: '01.png' }
  ], { id: 'sunset', name: '落日琥珀版' });
  const filter = buildVideoFilter(plan);
  assert(!filter.includes('xfade='));
  assert(filter.endsWith('[vout]'));
  assert.throws(
    () => assertSilentVideoRuntime({ ffmpeg: '__x_post_missing_ffmpeg__', ffprobe: '__x_post_missing_ffprobe__' }),
    /缺少本地命令/u
  );
});

test('支持 handle 与 i/web 两类 X status 输入链接', () => {
  assert.deepEqual(parseStatusUrl('https://x.com/writer/status/900?s=20'), {
    id: '900', handle: 'writer', canonicalUrl: 'https://x.com/writer/status/900'
  });
  assert.deepEqual(parseStatusUrl('https://x.com/i/web/status/900'), {
    id: '900', handle: null, canonicalUrl: 'https://x.com/i/web/status/900'
  });
  assert.deepEqual(parseStatusUrl('https://twitter.com/i/status/900'), {
    id: '900', handle: null, canonicalUrl: 'https://x.com/i/web/status/900'
  });
});

test('11 套模板完整注册且无重复', () => {
  assert.equal(TEMPLATES.length, 11);
  assert.equal(new Set(TEMPLATES.map(({ id }) => id)).size, 11);
  assert.deepEqual(TEMPLATES.map(({ id }) => id), [
    'sunset', 'editorial', 'data', 'fire', 'yellow', 'mono', 'night', 'ribbon', 'cobalt', 'news', 'minimal'
  ]);
});

test('普通 Post 只选择链接所指本体', () => {
  const root = post(100, '这是一条普通帖子。');
  const route = routeThread(normalizeFixture(root));
  assert.equal(route.resolvedInputType, 'post');
  assert.deepEqual(ids(route), ['100']);
});

test('Quote Post 只保留主贴并删除 Quote 专用链接', () => {
  const root = post(100, '主贴自己的结论。\nhttps://x.com/quoted/status/900?s=20\nhttps://example.com/keep', { quoteId: 900 });
  const route = routeThread(normalizeFixture(root));
  assert.equal(route.resolvedInputType, 'quote_post');
  assert.deepEqual(ids(route), ['100']);
  assert.equal(route.selectedNodes[0].cleanedText, '主贴自己的结论。\n\nhttps://example.com/keep');
  assert(!route.selectedNodes[0].cleanedText.includes('/status/900'));
  assert(route.selectedNodes[0].cleanedText.includes('https://example.com/keep'));
  assert.deepEqual(route.selectedNodes[0].media, []);
  assert.deepEqual(route.audit.ignored_quote_ids, ['900']);
});

test('Quote 缺少显式 ID 时从 URL 补提取，无法提取则 fail closed', () => {
  const withUrl = post(100, '自己的观点。\nhttps://x.com/i/web/status/900');
  withUrl.quote = { url: 'https://x.com/quoted/status/900', text: '引用正文不能输出' };
  const route = routeThread(normalizeFixture(withUrl));
  assert.equal(route.resolvedInputType, 'quote_post');
  assert.equal(route.selectedNodes[0].cleanedText, '自己的观点。');
  assert.deepEqual(route.audit.ignored_quote_ids, ['900']);

  const missing = post(101, '自己的观点。');
  missing.quote = { text: '引用正文不能输出' };
  assert.throws(() => normalizeFixture(missing), (error) => error.code === 'quote_identity_missing');
});

test('Quote 直链变体会精确删除且不吞掉相邻中文', () => {
  for (const url of [
    'https://x.com/i/web/status/900?s=20',
    'https://twitter.com/i/web/status/900#ref',
    'https://mobile.twitter.com/quoted/status/900/photo/1'
  ]) {
    assert.equal(removeQuoteStatusUrl(`我的评论 ${url}。后半句不能丢`, '900'), '我的评论 。后半句不能丢');
  }
});

test('Quote t.co 短链只在实体映射到 Quote 时删除', () => {
  const root = post(100, '主贴观点 https://t.co/quote900\n普通链接 https://t.co/keep', { quoteId: 900 });
  root.entities = { urls: [
    { url: 'https://t.co/quote900', expanded_url: 'https://x.com/i/web/status/900' },
    { url: 'https://t.co/keep', expanded_url: 'https://example.com/keep' }
  ] };
  const route = routeThread(normalizeFixture(root));
  assert.equal(route.selectedNodes[0].cleanedText, '主贴观点\n普通链接 https://t.co/keep');
  const unresolved = post(101, '主贴观点 https://t.co/unknown', { quoteId: 901 });
  assert.throws(() => routeThread(normalizeFixture(unresolved)), (error) => error.code === 'unresolved_quote_short_url');
});

test('Thread 从中间链接向前找根并加载同作者连续链', () => {
  const root = post(100, '第一段。', { createdAt: '2026-08-05T00:00:00Z' });
  const middle = post(101, '第二段。', { replyTo: 100, createdAt: '2026-08-05T00:01:00Z' });
  const end = post(102, '第三段。', { replyTo: 101, createdAt: '2026-08-05T00:02:00Z' });
  const route = routeThread(normalizeFixture(middle, [root, middle, end]));
  assert.equal(route.resolvedInputType, 'thread');
  assert.deepEqual(route.audit.verified_chain_status_ids, ['100', '101', '102']);
  assert.deepEqual(ids(route), ['100', '101', '102']);
  assert.equal(route.audit.thread_root_status_id, '100');
});

test('Thread 同秒节点按数字 status ID 判定先后并保留连续链', () => {
  const sameSecond = '2026-08-05T00:00:00Z';
  const root = post(200, '同秒第一段。', { createdAt: sameSecond });
  const middle = post(201, '同秒第二段。', {
    replyTo: 200,
    createdAt: sameSecond
  });
  const end = post(202, '同秒第三段。', {
    replyTo: 201,
    createdAt: sameSecond
  });
  const route = routeThread(normalizeFixture(middle, [root, middle, end]));
  assert.equal(route.resolvedInputType, 'thread');
  assert.deepEqual(route.audit.verified_chain_status_ids, ['200', '201', '202']);
  assert.deepEqual(ids(route), ['200', '201', '202']);

  const lowerIdChild = post(199, '同秒但 ID 更小。', {
    replyTo: 200,
    createdAt: sameSecond
  });
  const rejected = routeThread(normalizeFixture(root, [root, lowerIdChild]));
  assert.deepEqual(ids(rejected), ['200']);
  assert.deepEqual(rejected.audit.excluded_not_later_ids, ['199']);
});

test('带 Quote 的 Thread 忽略 Quote 正文和 Quote 媒体但保留自身媒体', () => {
  const root = post(100, '第一段。', { createdAt: '2026-08-05T00:00:00Z' });
  const child = post(101, '第二段自己的文字。\nhttps://twitter.com/quoted/status/900', {
    replyTo: 100,
    createdAt: '2026-08-05T00:01:00Z',
    quoteId: 900,
    media: [{ id: 'own-photo', type: 'photo', url: 'https://pbs.twimg.com/media/own-photo.jpg', width: 10, height: 20 }]
  });
  const route = routeThread(normalizeFixture(root, [root, child]));
  assert.equal(route.resolvedInputType, 'thread_with_quote');
  assert.deepEqual(ids(route), ['100', '101']);
  assert.equal(route.selectedNodes[1].cleanedText, '第二段自己的文字。');
  assert.deepEqual(route.selectedNodes[1].media.map(({ id }) => id), ['own-photo']);
  assert(!JSON.stringify(route.selectedNodes.map(({ cleanedText, media }) => ({ cleanedText, media }))).includes('quote-media'));
});

test('source-only 对自身媒体与 Quote 媒体的 ID 或 URL 碰撞 fail closed', () => {
  const cases = [
    {
      label: 'same-id',
      own: { id: 'collision', type: 'photo', url: 'https://pbs.twimg.com/media/own.jpg' },
      quoted: { id: 'collision', type: 'photo', url: 'https://pbs.twimg.com/media/quoted.jpg' },
      expected: { id_collision: true, url_collision: false }
    },
    {
      label: 'same-url',
      own: { id: 'own-photo', type: 'photo', url: 'https://pbs.twimg.com/media/shared.jpg' },
      quoted: { id: 'quoted-photo', type: 'photo', url: 'https://pbs.twimg.com/media/shared.jpg' },
      expected: { id_collision: false, url_collision: true }
    },
    {
      label: 'missing-poster-video-same-id',
      own: { id: 'video-collision', type: 'photo', url: 'https://pbs.twimg.com/media/own-video-id.jpg' },
      quoted: {
        id: 'video-collision',
        type: 'video',
        formats: [{
          url: 'https://video.twimg.com/video/1280x720/quoted-id-only.mp4',
          container: 'mp4',
          bitrate: 3000000
        }]
      },
      expected: { id_collision: true, url_collision: false }
    },
    {
      label: 'missing-poster-video-same-url',
      own: {
        id: 'own-video',
        type: 'video',
        thumbnail_url: 'https://pbs.twimg.com/video_thumb/own-video.jpg',
        formats: [{
          url: 'https://video.twimg.com/video/1280x720/shared-video.mp4',
          container: 'mp4',
          bitrate: 3000000
        }]
      },
      quoted: {
        id: 'quoted-video',
        type: 'video',
        formats: [{
          url: 'https://video.twimg.com/video/1280x720/shared-video.mp4',
          container: 'mp4',
          bitrate: 3000000
        }]
      },
      expected: { id_collision: false, url_collision: true }
    }
  ];
  for (const fixture of cases) {
    const root = post(100, `碰撞测试 ${fixture.label}。\nhttps://x.com/quoted/status/900`, {
      quoteId: 900,
      media: [fixture.own]
    });
    root.quote.media = { all: [fixture.quoted] };
    const route = routeThread(normalizeFixture(root));
    const selectedMedia = route.selectedNodes.flatMap((selected) => selected.media);
    assert(route.audit.ignored_quote_media_ids.includes(String(fixture.quoted.id)));
    const collisions = quoteMediaCollisionAudit(selectedMedia, route.audit);
    assert.equal(collisions.length, 1);
    assert.equal(collisions[0].id_collision, fixture.expected.id_collision);
    assert.equal(Boolean(collisions[0].url_hash_collisions.length), fixture.expected.url_collision);
    assert.throws(
      () => assertNoQuoteMediaCollisions(selectedMedia, route.audit, `test-${fixture.label}`),
      (error) => error.code === 'quote_media_collision' && error.phase === `test-${fixture.label}`
    );
  }
});

test('Quote-only Thread 节点在去链接后无正文和自身媒体则跳过', () => {
  const root = post(100, '主贴正文。', { createdAt: '2026-08-05T00:00:00Z' });
  const quoteOnly = post(101, 'https://x.com/quoted/status/900?s=20', {
    replyTo: 100,
    createdAt: '2026-08-05T00:01:00Z',
    quoteId: 900
  });
  const route = routeThread(normalizeFixture(root, [root, quoteOnly]));
  assert.equal(route.resolvedInputType, 'thread_with_quote');
  assert.deepEqual(ids(route), ['100']);
  assert.deepEqual(route.audit.excluded_statuses, [{ id: '101', reason: 'quote_only', ignored_quote_id: '900' }]);
});

test('source-only 遇到选中节点 Article 信号时要求改走 Article materializer', async () => {
  const articleSignals = [
    { field: 'article', value: { id: 'article-900', title: '完整 Article 标题' } },
    { field: 'article', value: {} },
    { field: 'article_id', value: 'article-901' },
    { field: 'content_type', value: 'x_article' },
    { field: 'is_article', value: true },
    { field: 'card', value: { type: 'article' }, expectedField: 'card.type' }
  ];
  for (const [index, fixture] of articleSignals.entries()) {
    const root = post(130 + index, '这里只是 Article teaser。');
    root[fixture.field] = fixture.value;
    const route = routeThread(normalizeFixture(root));
    assert.throws(
      () => assertNoSelectedArticleSignals(route),
      (error) => (
        error.code === 'x_article_route_required'
        && error.requiredMaterializer === 'x_article'
        && error.statusIds[0] === String(130 + index)
        && error.articleNodes[0].signal_fields.includes(fixture.expectedField ?? fixture.field)
      )
    );
  }

  const root = post(140, '普通主贴引用一篇 Article。', { quoteId: 900 });
  root.quote.article = { id: 'quoted-article', title: '引用 Article 不属于主贴正文' };
  const quoteRoute = routeThread(normalizeFixture(root));
  assert.deepEqual(assertNoSelectedArticleSignals(quoteRoute), { article_signal_count: 0 });

  const threadRoot = post(150, 'Thread 根。', { createdAt: '2026-08-05T00:00:00Z' });
  const articleChild = post(151, '子节点也是 Article teaser。', {
    replyTo: 150,
    createdAt: '2026-08-05T00:00:01Z'
  });
  articleChild.article = { id: 'article-child' };
  const threadRoute = routeThread(normalizeFixture(threadRoot, [threadRoot, articleChild]));
  assert.throws(
    () => assertNoSelectedArticleSignals(threadRoute),
    (error) => error.code === 'x_article_route_required' && error.statusIds[0] === '151'
  );

  const pureArticleChild = post(152, '', {
    replyTo: 150,
    createdAt: '2026-08-05T00:00:01Z'
  });
  pureArticleChild.article = { id: 'pure-article-child' };
  const pureThreadRoute = routeThread(normalizeFixture(threadRoot, [threadRoot, pureArticleChild]));
  assert.deepEqual(ids(pureThreadRoute), ['150']);
  assert(pureThreadRoute.audit.excluded_statuses.some(({ id }) => id === '152'));
  assert.throws(
    () => assertNoSelectedArticleSignals(pureThreadRoute),
    (error) => error.code === 'x_article_route_required' && error.statusIds[0] === '152'
  );

  const directory = integrationDirectory('article-route-required');
  const sourceJson = path.join(directory, 'article.json');
  const outputDirectory = path.join(directory, 'output');
  const cliArticle = post(160, '');
  cliArticle.article = { id: 'article-cli' };
  fs.writeFileSync(sourceJson, JSON.stringify({ status: cliArticle, thread: [cliArticle] }), { flag: 'wx' });
  await assert.rejects(
    run({
      url: 'https://x.com/writer/status/160',
      sourceJson,
      sourceOnly: true,
      template: DEFAULT_TEMPLATE,
      output: outputDirectory
    }),
    (error) => error.code === 'x_article_route_required' && error.statusIds[0] === '160'
  );
  assert(!fs.existsSync(outputDirectory));
});

test('他人回复不进入 Thread', () => {
  const root = post(100, '主贴正文。', { createdAt: '2026-08-05T00:00:00Z' });
  const otherReply = post(101, '评论内容。', {
    replyTo: 100,
    replyHandle: 'writer',
    author: otherAuthor,
    createdAt: '2026-08-05T00:01:00Z'
  });
  const route = routeThread(normalizeFixture(root, [root, otherReply]));
  assert.equal(route.resolvedInputType, 'post');
  assert.deepEqual(ids(route), ['100']);
  assert.deepEqual(route.audit.excluded_other_author_reply_ids, ['101']);
});

test('回复外部账号的根不扩展为 Thread', () => {
  const focal = post(100, '我对别人的回复。', {
    replyTo: 80,
    replyHandle: 'outsider',
    createdAt: '2026-08-05T00:00:00Z'
  });
  const selfReply = post(101, '继续解释。', { replyTo: 100, createdAt: '2026-08-05T00:01:00Z' });
  const route = routeThread(normalizeFixture(focal, [focal, selfReply]));
  assert.equal(route.resolvedInputType, 'post');
  assert.deepEqual(ids(route), ['100']);
  assert.equal(route.audit.focal_is_external_reply, true);
});

test('同作者 Thread 父节点缺失时报 thread_parent_missing', () => {
  const middle = post(101, '中间一段。', {
    replyTo: 100,
    replyHandle: 'writer',
    createdAt: '2026-08-05T00:01:00Z'
  });
  assert.throws(
    () => routeThread(normalizeFixture(middle, [middle])),
    (error) => error.code === 'thread_parent_missing' && error.parentStatusId === '100'
  );
});

test('同一节点出现多个同作者直接子分支时报错', () => {
  const root = post(100, '主贴正文。', { createdAt: '2026-08-05T00:00:00Z' });
  const childOne = post(101, '分支一。', { replyTo: 100, createdAt: '2026-08-05T00:01:00Z' });
  const childTwo = post(102, '分支二。', { replyTo: 100, createdAt: '2026-08-05T00:02:00Z' });
  assert.throws(
    () => routeThread(normalizeFixture(root, [root, childOne, childTwo])),
    (error) => error.code === 'ambiguous_self_reply_branch' && error.parentStatusId === '100'
  );
});

test('缺失作者身份或非数字帖子 ID 时 fail closed', () => {
  const missingAuthor = post(100, '正文。', { author: {} });
  assert.throws(() => normalizeFixture(missingAuthor), /缺少可核验的作者身份/u);
  const malicious = post('../../../outside', '正文。');
  assert.throws(() => normalizeFixture(malicious), /帖子 ID 不是有效数字 ID/u);
  const unsafeMedia = post(101, '正文。', {
    media: [{ id: 'unsafe', type: 'photo', url: 'file:///etc/passwd', width: 10, height: 10 }]
  });
  assert.throws(() => routeThread(normalizeFixture(unsafeMedia)), /拒绝非白名单/u);
});

test('视频保留封面并选择无需上采样的安全 MP4 供成片完整嵌入', () => {
  const root = post(100, '视频帖子。', {
    media: [{
      id: 'video-1',
      type: 'video',
      url: 'https://video.twimg.com/video/high.mp4',
      thumbnail_url: 'https://pbs.twimg.com/video_thumb/cover.jpg',
      duration: 87.492,
      width: 1920,
      height: 1080,
      format: 'video/mp4',
      formats: [
        { url: 'https://video.twimg.com/video/playlist.m3u8', container: 'm3u8' },
        { url: 'https://video.twimg.com/video/640x360/low.mp4', container: 'mp4', codec: 'h264', bitrate: 832000 },
        { url: 'https://video.twimg.com/video/1280x720/canvas.mp4', container: 'mp4', codec: 'h264', bitrate: 3000000 },
        { url: 'https://video.twimg.com/video/1920x1080/high.mp4', container: 'mp4', codec: 'h264', bitrate: 6000000 },
        { url: 'https://evil.invalid/video/3840x2160/unsafe.mp4', container: 'mp4', codec: 'h264', bitrate: 99999999 }
      ]
    }]
  });
  assert.deepEqual(ownMedia(root), [{
    id: 'video-1',
    type: 'video',
    url: 'https://pbs.twimg.com/video_thumb/cover.jpg',
    poster_url: 'https://pbs.twimg.com/video_thumb/cover.jpg',
    width: null,
    height: null,
    video_url: 'https://video.twimg.com/video/1280x720/canvas.mp4',
    video_duration_seconds: 87.492,
    video_variant: {
      url: 'https://video.twimg.com/video/1280x720/canvas.mp4',
      container: 'mp4',
      codec: 'h264',
      bitrate: 3000000,
      width: 1280,
      height: 720,
      selection: 'canvas_matched_mp4'
    }
  }]);
  assert.equal(selectNativeVideoVariant({
    url: 'file:///etc/passwd',
    format: 'video/mp4',
    formats: [{ url: 'https://video.invalid/a.mp4', container: 'mp4', bitrate: 1 }]
  }), null);
  assert.deepEqual(selectNativeVideoVariant({
    url: 'https://video.twimg.com/video/1080x1920/fallback.mp4',
    format: 'video/mp4',
    width: 1080,
    height: 1920
  }), {
    url: 'https://video.twimg.com/video/1080x1920/fallback.mp4',
    container: 'mp4',
    codec: null,
    bitrate: null,
    width: 1080,
    height: 1920,
    selection: 'validated_top_level_mp4_fallback'
  });
  const missingPoster = post(102, '缺封面视频。', {
    media: [{
      id: 'video-without-poster',
      type: 'video',
      url: 'https://video.twimg.com/video/1280x720/source.mp4',
      format: 'video/mp4'
    }]
  });
  assert.throws(
    () => ownMedia(missingPoster),
    (error) => (
      error.code === 'media_video_poster_missing'
      && error.statusId === '102'
      && error.mediaSource === 'all'
      && error.mediaIndex === 0
      && error.mediaId === 'video-without-poster'
    )
  );
});

test('缺少 media.all 的照片视频混合媒体不猜顺序，单一类型仍可 fallback', () => {
  const photo = {
    id: 'photo-1',
    type: 'photo',
    url: 'https://pbs.twimg.com/media/photo-1.jpg',
    width: 1200,
    height: 800
  };
  const video = {
    id: 'video-1',
    type: 'video',
    thumbnail_url: 'https://pbs.twimg.com/video_thumb/video-1.jpg',
    duration: 9.2,
    formats: [{
      url: 'https://video.twimg.com/video/1280x720/video-1.mp4',
      container: 'mp4',
      bitrate: 3000000
    }]
  };

  const mixedWithoutOrder = post(103, '照片和视频混合。');
  mixedWithoutOrder.media = { photos: [photo], videos: [video] };
  assert.throws(
    () => ownMedia(mixedWithoutOrder),
    (error) => (
      error.code === 'mixed_media_order_unavailable'
      && error.statusId === '103'
      && error.photoCount === 1
      && error.videoCount === 1
    )
  );
  assert.throws(
    () => routeThread(normalizeFixture(mixedWithoutOrder)),
    (error) => error.code === 'mixed_media_order_unavailable' && error.statusId === '103'
  );

  const photosOnly = post(104, '只有照片。');
  photosOnly.media = { photos: [photo] };
  assert.deepEqual(ownMedia(photosOnly).map(({ id, type }) => ({ id, type })), [
    { id: 'photo-1', type: 'photo' }
  ]);

  const videosOnly = post(105, '只有视频。');
  videosOnly.media = { videos: [video] };
  assert.deepEqual(ownMedia(videosOnly).map(({ id, type }) => ({ id, type })), [
    { id: 'video-1', type: 'video' }
  ]);

  const mixedWithOrder = post(106, '有明确顺序的混合媒体。', { media: [video, photo] });
  assert.deepEqual(ownMedia(mixedWithOrder).map(({ id, type }) => ({ id, type })), [
    { id: 'video-1', type: 'video' },
    { id: 'photo-1', type: 'photo' }
  ]);
});

test('media.all 的无效条目、未知类型、图片缺 URL 与空数组矛盾均结构化失败', () => {
  const invalidEntries = [
    { label: 'null', item: null },
    { label: 'non-object', item: 'not-an-object' },
    { label: 'empty-object', item: {} }
  ];
  for (const [caseIndex, fixture] of invalidEntries.entries()) {
    const root = post(110 + caseIndex, `无效媒体条目：${fixture.label}。`, { media: [fixture.item] });
    assert.throws(
      () => ownMedia(root),
      (error) => (
        error.code === 'media_entry_invalid'
        && error.statusId === String(110 + caseIndex)
        && error.mediaSource === 'all'
        && error.mediaIndex === 0
      )
    );
  }

  const unknownType = post(113, '未知媒体类型。', {
    media: [{ id: 'audio-1', type: 'audio', url: 'https://pbs.twimg.com/media/audio-1' }]
  });
  assert.throws(
    () => routeThread(normalizeFixture(unknownType)),
    (error) => (
      error.code === 'media_type_unknown'
      && error.statusId === '113'
      && error.mediaSource === 'all'
      && error.mediaIndex === 0
      && error.mediaId === 'audio-1'
      && error.mediaType === 'audio'
    )
  );

  const imageWithoutUrl = post(114, '图片缺少 URL。', {
    media: [{ id: 'image-1', type: 'image', url: '   ' }]
  });
  assert.throws(
    () => routeThread(normalizeFixture(imageWithoutUrl)),
    (error) => (
      error.code === 'media_image_url_missing'
      && error.statusId === '114'
      && error.mediaSource === 'all'
      && error.mediaIndex === 0
      && error.mediaId === 'image-1'
      && error.mediaType === 'image'
    )
  );

  const photoFallback = {
    id: 'photo-fallback',
    type: 'photo',
    url: 'https://pbs.twimg.com/media/photo-fallback.jpg'
  };
  const contradictoryEmptyAll = post(115, '空 all 与照片数组矛盾。');
  contradictoryEmptyAll.media = { all: [], photos: [photoFallback] };
  assert.throws(
    () => routeThread(normalizeFixture(contradictoryEmptyAll)),
    (error) => (
      error.code === 'media_all_inconsistent'
      && error.statusId === '115'
      && error.reason === 'empty_all_with_fallback_items'
      && error.photoCount === 1
      && error.videoCount === 0
    )
  );

  const contradictoryEmptyAllWithVideo = post(116, '空 all 与视频数组矛盾。');
  contradictoryEmptyAllWithVideo.media = {
    all: [],
    videos: [{
      id: 'video-fallback',
      type: 'video',
      thumbnail_url: 'https://pbs.twimg.com/video_thumb/video-fallback.jpg'
    }]
  };
  assert.throws(
    () => ownMedia(contradictoryEmptyAllWithVideo),
    (error) => (
      error.code === 'media_all_inconsistent'
      && error.statusId === '116'
      && error.reason === 'empty_all_with_fallback_items'
      && error.photoCount === 0
      && error.videoCount === 1
    )
  );
});

test('持久化审计清洗媒体 URL 凭据、查询与 fragment，但运行时下载仍保留完整 URL', async () => {
  const signedPhoto = 'https://media-user:media-pass@pbs.twimg.com/media/private-photo.jpg?token=photo-secret#photo-fragment';
  const signedPoster = 'https://pbs.twimg.com/video_thumb/private-video.jpg?poster_token=poster-secret#poster-fragment';
  const signedVideo = 'https://video.twimg.com/video/1280x720/private-video.mp4?signature=video-secret#video-fragment';
  const signedAvatar = 'https://avatar-user:avatar-pass@pbs.twimg.com/profile_images/avatar.jpg?auth=avatar-secret#avatar-fragment';
  const signedStatus = 'https://status-user:status-pass@x.com/writer/status/120?auth=status-secret#status-fragment';
  const root = post(120, '带签名媒体。', {
    author: { ...author, avatar_url: signedAvatar },
    media: [
      { id: 'private-photo', type: 'photo', url: signedPhoto },
      {
        id: 'private-video',
        type: 'video',
        thumbnail_url: signedPoster,
        formats: [{ url: signedVideo, container: 'mp4', bitrate: 3000000 }]
      }
    ]
  });
  root.url = signedStatus;
  const normalized = normalizeFixture(root);
  const route = routeThread(normalized);
  assert.equal(route.selectedNodes[0].media[0].url, signedPhoto);
  assert.equal(route.selectedNodes[0].media[1].poster_url, signedPoster);
  assert.equal(route.selectedNodes[0].media[1].video_url, signedVideo);

  const status = parseStatusUrl('https://x.com/writer/status/120');
  const selectedSource = selectedSourceForDelivery(status, normalized, route);
  const persistedPhoto = selectedSource.selected_statuses[0].own_media[0];
  const persistedVideo = selectedSource.selected_statuses[0].own_media[1];
  assert.equal(selectedSource.selected_statuses[0].url, 'https://x.com/writer/status/120');
  assert.equal(selectedSource.selected_statuses[0].author.avatar_url, 'https://pbs.twimg.com/profile_images/avatar.jpg');
  assert.equal(persistedPhoto.url, 'https://pbs.twimg.com/media/private-photo.jpg');
  assert.equal(persistedVideo.url, 'https://pbs.twimg.com/video_thumb/private-video.jpg');
  assert.equal(persistedVideo.poster_url, 'https://pbs.twimg.com/video_thumb/private-video.jpg');
  assert.equal(persistedVideo.video_url, 'https://video.twimg.com/video/1280x720/private-video.mp4');
  assert.equal(persistedVideo.video_variant.url, 'https://video.twimg.com/video/1280x720/private-video.mp4');

  const manifest = manifestFor({
    options: { template: DEFAULT_TEMPLATE, video: false },
    status,
    normalized,
    route,
    templates: [TEMPLATES.find(({ id }) => id === DEFAULT_TEMPLATE)],
    outputs: [{
      source_full_text: '不进入 manifest',
      author: { avatar_url: signedAvatar },
      media: {
        url: signedPoster,
        poster_url: signedPoster,
        video_url: signedVideo,
        video_variant: { url: signedVideo },
        native_video: { selected_variant: { url: signedVideo } }
      }
    }],
    assets: {
      avatar: { source_url: signedAvatar },
      media: [{
        url: signedPoster,
        poster_url: signedPoster,
        video_url: signedVideo,
        video_variant: { url: signedVideo },
        native_video: { selected_variant: { url: signedVideo } }
      }]
    },
    previewSheet: {},
    coverage: {},
    outputDirectory: '/not-persisted'
  });
  assert.equal(manifest.assets.avatar.source_url, 'https://pbs.twimg.com/profile_images/avatar.jpg');
  assert.equal(manifest.assets.media[0].video_url, 'https://video.twimg.com/video/1280x720/private-video.mp4');
  assert.equal(manifest.assets.media[0].native_video.selected_variant.url, 'https://video.twimg.com/video/1280x720/private-video.mp4');
  assert.equal(manifest.outputs[0].author.avatar_url, 'https://pbs.twimg.com/profile_images/avatar.jpg');

  const persistedJson = JSON.stringify({ selectedSource, manifest });
  for (const secret of [
    'media-user', 'media-pass', 'photo-secret', 'photo-fragment',
    'poster-secret', 'poster-fragment', 'video-secret', 'video-fragment',
    'avatar-user', 'avatar-pass', 'avatar-secret', 'avatar-fragment',
    'status-user', 'status-pass', 'status-secret', 'status-fragment'
  ]) {
    assert(!persistedJson.includes(secret), `持久化 JSON 泄漏：${secret}`);
  }
  assert.deepEqual(sanitizeRemoteUrlsForPersistence({
    media_url: 'https://user:password@pbs.twimg.com/media/example.jpg?credential=secret#private'
  }), {
    media_url: 'https://pbs.twimg.com/media/example.jpg'
  });

  const originalFetch = globalThis.fetch;
  const jpeg = Buffer.alloc(32);
  jpeg[0] = 0xff;
  jpeg[1] = 0xd8;
  jpeg[2] = 0xff;
  let requestedUrl = null;
  globalThis.fetch = async (url) => {
    requestedUrl = String(url);
    return new Response(jpeg, {
      status: 200,
      headers: { 'content-type': 'image/jpeg', 'content-length': String(jpeg.length) }
    });
  };
  try {
    const directory = integrationDirectory('signed-url-download');
    await materializeAsset(signedPoster, path.join(directory, 'signed-poster.jpg'));
    assert.equal(requestedUrl, signedPoster);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('source-only Markdown 无人工标题并按节点嵌入媒体和 Thread marker', () => {
  const root = post(100, '第一条正文。', {
    createdAt: '2026-08-05T00:00:00Z',
    media: [{
      id: 'photo-1',
      type: 'photo',
      url: 'https://pbs.twimg.com/media/photo-1.jpg',
      width: 1200,
      height: 800
    }]
  });
  const child = post(101, '第二条正文。', {
    replyTo: 100,
    createdAt: '2026-08-05T00:01:00Z',
    media: [{
      id: 'video-1',
      type: 'video',
      thumbnail_url: 'https://pbs.twimg.com/video_thumb/video-1.jpg',
      duration: 9.2,
      formats: [{
        url: 'https://video.twimg.com/video/1280x720/video-1.mp4',
        container: 'mp4',
        bitrate: 3000000
      }]
    }]
  });
  const normalized = normalizeFixture(root, [root, child]);
  const route = routeThread(normalized);
  const assets = {
    avatar: null,
    media: [
      {
        id: 'photo-1',
        type: 'photo',
        source_post_id: '100',
        relative_path: 'assets/media-1-1.jpg',
        sha256: 'photo-sha',
        bytes: 101,
        content_type: 'image/jpeg'
      },
      {
        id: 'video-1',
        type: 'video',
        source_post_id: '101',
        relative_path: 'assets/media-2-1-poster.jpg',
        sha256: 'poster-sha',
        bytes: 202,
        content_type: 'image/jpeg',
        native_video: {
          relative_path: 'assets/media-2-1-source.mp4',
          sha256: 'video-sha',
          bytes: 303,
          content_type: 'video/mp4'
        }
      }
    ]
  };
  const status = parseStatusUrl('https://x.com/writer/status/100');
  const source = sourceMarkdownForDelivery(status, route, assets);
  assert(source.markdown.startsWith('---\nmode: thread\npreserve_text: true\nsource_kind: x\n'));
  assert(source.markdown.includes('source_url: "https://x.com/writer/status/100"'));
  assert(source.markdown.includes('title_policy: include'));
  assert(!source.markdown.includes('\n# '));
  assert(!source.markdown.includes('Thread1:'));
  assert.equal((source.markdown.match(/^Thread2:$/gmu) ?? []).length, 1);
  assert(source.markdown.indexOf('第一条正文。') < source.markdown.indexOf('![](assets/media-1-1.jpg)'));
  assert(source.markdown.indexOf('![](assets/media-1-1.jpg)') < source.markdown.indexOf('Thread2:'));
  assert(source.markdown.indexOf('第二条正文。') < source.markdown.indexOf('![原生视频封面](assets/media-2-1-poster.jpg)'));
  assert(source.markdown.includes('<!-- yichen-native-video: assets/media-2-1-source.mp4 -->'));
  assert.deepEqual(source.units.map(({ marker, status_id }) => [marker, status_id]), [
    [null, '100'], ['Thread2:', '101']
  ]);

  const sourceImport = sourceImportForDelivery({
    status,
    normalized,
    route,
    assets,
    sourceMarkdownSha256: 'source-md-sha',
    selectedSourceSha256: 'selected-source-sha',
    routingAuditSha256: 'routing-audit-sha'
  });
  assert.equal(sourceImport.artificial_title_added, false);
  assert.equal(sourceImport.checks.bound_media_count, 2);
  assert.equal(sourceImport.checks.native_video_count, 1);
  assert.equal(sourceImport.checks.all_native_videos_have_mp4, true);
  assert.equal(sourceImport.checks.quote_media_collision_count, 0);
  assert.deepEqual(sourceImport.units[1].media[0], {
    order: 1,
    global_order: 2,
    source_media_id: 'video-1',
    kind: 'video',
    path: 'assets/media-2-1-source.mp4',
    sha256: 'video-sha',
    bytes: 303,
    content_type: 'video/mp4',
    poster: {
      path: 'assets/media-2-1-poster.jpg',
      sha256: 'poster-sha',
      bytes: 202,
      content_type: 'image/jpeg'
    },
    markdown_embed: '![原生视频封面](assets/media-2-1-poster.jpg)',
    markdown_marker: '<!-- yichen-native-video: assets/media-2-1-source.mp4 -->'
  });
});

test('source-only 单帖正文 marker-like 独占行可逆编码且围栏内不改', () => {
  const root = post(100, [
    '开头。',
    'Thread2:',
    'Post 7',
    '```text',
    'Part3:',
    '```',
    '结尾。'
  ].join('\n'));
  const route = routeThread(normalizeFixture(root));
  const status = parseStatusUrl('https://x.com/writer/status/100');
  const source = sourceMarkdownForDelivery(status, route, { avatar: null, media: [] });
  assert.equal(source.literalMarkerEncoding.version, 'yichen-literal-marker/v1');
  assert.deepEqual(
    source.literalMarkerEncoding.replacements.map(({ unit_order, status_id, line_order, original_line }) => ({
      unit_order, status_id, line_order, original_line
    })),
    [
      { unit_order: 1, status_id: '100', line_order: 2, original_line: 'Thread2:' },
      { unit_order: 1, status_id: '100', line_order: 3, original_line: 'Post 7' }
    ]
  );
  for (const replacement of source.literalMarkerEncoding.replacements) {
    assert.equal(source.markdown.split('\n')[replacement.source_markdown_line - 1], replacement.encoded_line);
    assert(source.markdown.includes(replacement.encoded_line));
  }
  assert.match(source.markdown, /^Part3:$/mu);
  assert.equal((source.markdown.match(/^Thread2:$/gmu) ?? []).length, 0);
  const restoredText = encodeLiteralMarkerLines(root.text, { unitOrder: 1, statusId: '100' })
    .replacements
    .reduce((text, replacement) => text.replace(replacement.encoded_line, replacement.original_line),
      encodeLiteralMarkerLines(root.text, { unitOrder: 1, statusId: '100' }).text);
  assert.equal(restoredText, root.text);
});

test('source-only CommonMark fence 记录字符与长度，内层短 fence 和带后缀长 fence 不误关', () => {
  const fakeEncoded = `Thread2:<!-- yichen-literal-marker:v1:${'a'.repeat(64)} -->`;
  const root = post(100, [
    '开头。',
    '````markdown',
    '```python',
    'Thread2:',
    fakeEncoded,
    '```',
    '````still-code',
    'Part3:',
    '`````   ',
    'Post4:'
  ].join('\n'));
  const normalized = normalizeFixture(root);
  const route = routeThread(normalized);
  const status = parseStatusUrl('https://x.com/writer/status/100');
  const assets = { avatar: null, media: [] };
  const source = sourceMarkdownForDelivery(status, route, assets);
  assert.deepEqual(
    source.literalMarkerEncoding.replacements.map(({ line_order, original_line }) => ({ line_order, original_line })),
    [{ line_order: 10, original_line: 'Post4:' }]
  );
  assert.match(source.markdown, /^Thread2:$/mu);
  assert(source.markdown.includes(fakeEncoded));
  assert.match(source.markdown, /^Part3:$/mu);
  assert(!source.markdown.includes(`Post4:\n`));

  const sourceImport = sourceImportForDelivery({
    status,
    normalized,
    route,
    assets,
    literalMarkerEncoding: source.literalMarkerEncoding,
    sourceMarkdownSha256: 'source-md-sha',
    selectedSourceSha256: 'selected-source-sha',
    routingAuditSha256: 'routing-audit-sha'
  });
  assertLiteralMarkerEncodingIntegrity(source.markdown, sourceImport);
  assert.equal(sourceImport.checks.literal_marker_encoding_verified, true);
});

test('source-only 多帖结构 marker 与各节点正文 marker 编码不混淆', () => {
  const root = post(100, '根正文。\nThread2:', { createdAt: '2026-08-05T00:00:00Z' });
  const child = post(101, '子正文。\nPart 9', {
    replyTo: 100,
    createdAt: '2026-08-05T00:01:00Z'
  });
  const normalized = normalizeFixture(root, [root, child]);
  const route = routeThread(normalized);
  const status = parseStatusUrl('https://x.com/writer/status/100');
  const assets = { avatar: null, media: [] };
  const source = sourceMarkdownForDelivery(status, route, assets);
  assert.equal((source.markdown.match(/^Thread2:$/gmu) ?? []).length, 1);
  assert.deepEqual(
    source.literalMarkerEncoding.replacements.map(({ unit_order, status_id, line_order, original_line }) => ({
      unit_order, status_id, line_order, original_line
    })),
    [
      { unit_order: 1, status_id: '100', line_order: 2, original_line: 'Thread2:' },
      { unit_order: 2, status_id: '101', line_order: 2, original_line: 'Part 9' }
    ]
  );
  const sourceImport = sourceImportForDelivery({
    status,
    normalized,
    route,
    assets,
    literalMarkerEncoding: source.literalMarkerEncoding,
    sourceMarkdownSha256: 'source-md-sha',
    selectedSourceSha256: 'selected-source-sha',
    routingAuditSha256: 'routing-audit-sha'
  });
  assert.equal(sourceImport.checks.literal_marker_replacement_count, 2);
  assert.equal(sourceImport.literal_marker_encoding.replacements[1].unit_order, 2);
});

test('source-only 原生视频缺少 MP4 绑定时 fail closed', () => {
  const root = post(100, '视频正文。', {
    media: [{
      id: 'video-1',
      type: 'video',
      thumbnail_url: 'https://pbs.twimg.com/video_thumb/video-1.jpg',
      formats: [{
        url: 'https://video.twimg.com/video/1280x720/video-1.mp4',
        container: 'mp4',
        bitrate: 3000000
      }]
    }]
  });
  const route = routeThread(normalizeFixture(root));
  assert.throws(
    () => sourceMarkdownForDelivery(parseStatusUrl('https://x.com/writer/status/100'), route, {
      avatar: null,
      media: [{
        id: 'video-1',
        type: 'video',
        source_post_id: '100',
        relative_path: 'assets/media-1-1-poster.jpg',
        sha256: 'poster-sha',
        bytes: 202,
        content_type: 'image/jpeg'
      }]
    }),
    /缺少已下载 MP4；拒绝只把海报当视频/u
  );
});

test('通过 skills 目录软链接直接执行脚本不会静默退出', () => {
  const directory = integrationDirectory('direct-symlink');
  const script = path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'yichen_x_slicer.mjs');
  const linkedScript = path.join(directory, 'yichen_x_slicer.mjs');
  fs.symlinkSync(script, linkedScript);
  assert.equal(isDirectExecution(linkedScript, new URL('./yichen_x_slicer.mjs', import.meta.url).href), true);
  const execution = spawnSync(process.execPath, [linkedScript, '--help'], { encoding: 'utf8' });
  assert.equal(execution.status, 0, execution.stderr);
  assert.match(execution.stdout, /--source-only/u);
  assert.match(execution.stdout, /用法/u);
});

test('长正文按顺序完整拆帧且外围标题来自原文', () => {
  const text = Array.from({ length: 40 }, (_, index) => `第${index + 1}段：这是需要完整保留的正文内容。`).join('\n\n');
  const slices = splitText(text);
  assert(slices.length > 1);
  assert.equal(slices.join(''), text);
  for (const slice of slices) {
    const hook = deriveHook(slice);
    assert(slice.includes(hook));
  }
});

test('无空白切点的连续正文也能逐字完整拆帧', () => {
  for (const text of [
    '中'.repeat(400),
    'a'.repeat(400),
    Array.from({ length: 160 }, (_, index) => `第${index + 1}项。`).join('')
  ]) {
    const slices = splitText(text);
    assert(slices.length > 1);
    assert.equal(slices.join(''), text);
    assert(slices.every((slice) => slice.length <= 370));
  }
});

test('Emoji 字形与密集换行不会被拆坏或挤进单帧', () => {
  const emojiText = '👨‍👩‍👧‍👦'.repeat(371);
  const emojiSlices = splitText(emojiText);
  assert.equal(emojiSlices.join(''), emojiText);
  assert(emojiSlices.every((slice) => !slice.includes('\ufffd')));
  assert(emojiSlices.every((slice) => !slice.endsWith('\u200d')));

  const denseLines = Array.from({ length: 100 }, (_, index) => `第${index + 1}行`).join('\n');
  const denseSlices = splitText(denseLines);
  assert.equal(denseSlices.join(''), denseLines);
  assert(denseSlices.length > 1);
  assert(denseSlices.every((slice) => slice.split('\n').length <= 18));
});

test('source-only 图片按 JPEG PNG WebP AVIF GIF 魔数落真实扩展名', async () => {
  const jpeg = Buffer.alloc(32);
  jpeg.set([0xff, 0xd8, 0xff, 0xe0], 0);
  const png = Buffer.alloc(32);
  png.set([137, 80, 78, 71, 13, 10, 26, 10], 0);
  const webp = Buffer.alloc(32);
  webp.write('RIFF', 0, 'ascii');
  webp.writeUInt32LE(24, 4);
  webp.write('WEBP', 8, 'ascii');
  const avif = Buffer.alloc(32);
  avif.writeUInt32BE(24, 0);
  avif.write('ftyp', 4, 'ascii');
  avif.write('mif1', 8, 'ascii');
  avif.writeUInt32BE(0, 12);
  avif.write('avif', 16, 'ascii');
  const gif = Buffer.alloc(32);
  gif.write('GIF89a', 0, 'ascii');
  const fixtures = [
    { name: 'jpeg', bytes: jpeg, extension: '.jpg', contentType: 'image/jpeg' },
    { name: 'png', bytes: png, extension: '.png', contentType: 'image/png' },
    { name: 'webp', bytes: webp, extension: '.webp', contentType: 'image/webp' },
    { name: 'avif', bytes: avif, extension: '.avif', contentType: 'image/avif' },
    { name: 'gif', bytes: gif, extension: '.gif', contentType: 'image/gif' }
  ];
  for (const fixture of fixtures) {
    assert.deepEqual(detectImageFormat(fixture.bytes), {
      extension: fixture.extension,
      content_type: fixture.contentType
    });
  }

  const directory = integrationDirectory('source-image-extension');
  fs.mkdirSync(path.join(directory, 'assets'));
  const fixtureByUrl = new Map(fixtures.map((fixture) => [
    `https://pbs.twimg.com/media/source-only-${fixture.name}`,
    fixture
  ]));
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const fixture = fixtureByUrl.get(String(url));
    if (!fixture) throw new Error(`unexpected test URL: ${String(url)}`);
    return new Response(fixture.bytes, {
      status: 200,
      headers: {
        'content-type': fixture.contentType,
        'content-length': String(fixture.bytes.length)
      }
    });
  };
  try {
    const downloaded = [];
    for (let index = 0; index < fixtures.length; index += 1) {
      const fixture = fixtures[index];
      const record = await materializeSourceImage(
        `https://pbs.twimg.com/media/source-only-${fixture.name}`,
        directory,
        `assets/media-1-${index + 1}`
      );
      assert.equal(record.relative_path, `assets/media-1-${index + 1}${fixture.extension}`);
      assert.equal(record.content_type, fixture.contentType);
      assert.equal(record.extension, fixture.extension);
      const downloadedPath = path.join(directory, record.relative_path);
      assert(fs.existsSync(downloadedPath));
      assert.deepEqual(fs.readFileSync(downloadedPath), fixture.bytes);
      assert(!fs.existsSync(path.join(directory, `assets/media-1-${index + 1}.download`)));
      downloaded.push(record);
    }

    const root = post(300, '格式测试。', {
      media: fixtures.map((fixture, index) => ({
        id: `photo-${index + 1}`,
        type: 'photo',
        url: `https://pbs.twimg.com/media/source-only-${fixture.name}`
      }))
    });
    const normalized = normalizeFixture(root);
    const route = routeThread(normalized);
    const assets = {
      avatar: null,
      media: downloaded.map((record, index) => ({
        ...route.selectedNodes[0].media[index],
        ...record,
        source_post_id: '300'
      }))
    };
    const status = parseStatusUrl('https://x.com/writer/status/300');
    const source = sourceMarkdownForDelivery(status, route, assets);
    for (let index = 0; index < fixtures.length; index += 1) {
      assert(source.markdown.includes(`![](assets/media-1-${index + 1}${fixtures[index].extension})`));
    }
    const sourceImport = sourceImportForDelivery({
      status,
      normalized,
      route,
      assets,
      literalMarkerEncoding: source.literalMarkerEncoding,
      sourceMarkdownSha256: 'source-md-sha',
      selectedSourceSha256: 'selected-source-sha',
      routingAuditSha256: 'routing-audit-sha'
    });
    assert.deepEqual(
      sourceImport.units[0].media.map(({ path: mediaPath, content_type: contentType, sha256 }) => ({ mediaPath, contentType, sha256 })),
      fixtures.map((fixture, index) => ({
        mediaPath: `assets/media-1-${index + 1}${fixture.extension}`,
        contentType: fixture.contentType,
        sha256: downloaded[index].sha256
      }))
    );

    const videoPoster = await materializeSourceImage(
      'https://pbs.twimg.com/media/source-only-webp',
      directory,
      'assets/media-2-1-poster'
    );
    assert.equal(videoPoster.relative_path, 'assets/media-2-1-poster.webp');
    assert.deepEqual(
      fs.readFileSync(path.join(directory, videoPoster.relative_path)),
      webp
    );
    const videoRoot = post(301, '视频海报格式测试。', {
      media: [{
        id: 'video-webp-poster',
        type: 'video',
        thumbnail_url: 'https://pbs.twimg.com/media/source-only-webp',
        formats: [{
          url: 'https://video.twimg.com/video/1280x720/video.mp4',
          container: 'mp4',
          bitrate: 3000000
        }]
      }]
    });
    const videoNormalized = normalizeFixture(videoRoot);
    const videoRoute = routeThread(videoNormalized);
    const videoAssets = {
      avatar: null,
      media: [{
        ...videoRoute.selectedNodes[0].media[0],
        ...videoPoster,
        source_post_id: '301',
        native_video: {
          relative_path: 'assets/media-2-1-source.mp4',
          sha256: 'video-sha',
          bytes: 999,
          content_type: 'video/mp4'
        }
      }]
    };
    const videoStatus = parseStatusUrl('https://x.com/writer/status/301');
    const videoSource = sourceMarkdownForDelivery(videoStatus, videoRoute, videoAssets);
    assert(videoSource.markdown.includes('![原生视频封面](assets/media-2-1-poster.webp)'));
    assert(videoSource.markdown.includes('<!-- yichen-native-video: assets/media-2-1-source.mp4 -->'));
    const videoImport = sourceImportForDelivery({
      status: videoStatus,
      normalized: videoNormalized,
      route: videoRoute,
      assets: videoAssets,
      literalMarkerEncoding: videoSource.literalMarkerEncoding,
      sourceMarkdownSha256: 'source-md-sha',
      selectedSourceSha256: 'selected-source-sha',
      routingAuditSha256: 'routing-audit-sha'
    });
    assert.deepEqual(videoImport.units[0].media[0].poster, {
      path: 'assets/media-2-1-poster.webp',
      sha256: videoPoster.sha256,
      bytes: webp.length,
      content_type: 'image/webp'
    });

    const defaultPath = path.join(directory, 'assets/default-render-name.jpg');
    const defaultRecord = await materializeAsset(
      'https://pbs.twimg.com/media/source-only-png',
      defaultPath
    );
    assert.equal(defaultRecord.extension, '.png');
    assert(fs.existsSync(defaultPath));
    assert(!fs.existsSync(path.join(directory, 'assets/default-render-name.png')));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('缺失指标不伪装成真实零，外部本地素材一律拒绝', async () => {
  assert.equal(formatMetric(undefined, '阅读'), null);
  assert.equal(formatMetric(-1, '赞'), null);
  assert.equal(formatMetric(0, '收藏'), '0收藏');
  await assert.rejects(materializeAsset('/etc/passwd', '/tmp/yichen-x-slicer-never-written.jpg'), /拒绝本地路径/u);
  await assert.rejects(materializeAsset('data:image/png;base64,AA==', '/tmp/yichen-x-slicer-never-written.jpg'), /拒绝本地路径/u);
  await assert.rejects(materializeVideoAsset('/etc/passwd', '/tmp/yichen-x-slicer-never-written.mp4'), /拒绝本地路径/u);
});

let passed = 0;
for (const { name, callback } of tests) {
  try {
    await callback();
    passed += 1;
    process.stdout.write(`通过：${name}\n`);
  } catch (error) {
    process.stderr.write(`失败：${name}\n${error.stack}\n`);
    process.exitCode = 1;
  }
}

if (process.exitCode) {
  process.stderr.write(`测试失败：${tests.length - passed}/${tests.length}\n`);
} else {
  process.stdout.write(`全部通过：${passed}/${tests.length}\n`);
}
