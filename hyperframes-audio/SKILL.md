---
name: hyperframes-audio
description: >
  Use when audio already placed in a HyperFrames composition needs to be mixed:
  fade-in/fade-out, crossfade, track gain or volume, volume automation, ducking,
  a music bed that fights a voiceover (voiceover carve), effects on a track
  (EQ, compressor, limiter, gate, saturation, delay, reverb, chorus, phaser,
  bitcrush), automation envelopes drawn on a track's volume or any effect
  parameter, or one submix bus carrying a chain, a fader and an automation clock
  for several tracks at once (`hf-audio-group`).
  Don't use for sourcing or generating audio — finding BGM, SFX, or making a
  voiceover is `/media-use`. Don't use for clip timing or track layout, which is
  `/hyperframes-core`.
---

# hyperframes-audio: compatibility entry

Upstream consolidated this skill into the current HyperFrames core. The installed name remains available; read [HyperFrames](../hyperframes/SKILL.md) first, then the task's current reference:

- [Mixing, fades, effects and audio groups](../media-use/references/mixing.md)
- [Audio workflow](../media-use/references/audio.md)

Follow the current composition contract and CLI guidance. Do not run archived `skills update hyperframes-audio` commands or use removed workflows as prerequisites. [LEGACY-SKILL.md](LEGACY-SKILL.md) and this directory's existing resources preserve the previous interfaces and recipes for reference; they do not override the current runtime contract. No new skill is required by this compatibility entry.

Keep the person's content, locked storyboard frames and manual edits. Questions and explicit holds authorize no composition changes; an explicit request for no file changes also means no plan-file writes. Render after the preview is approved, or when the person has already requested the file or no stops, after validation and visual review.
