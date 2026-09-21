# Reliability And Risks

Use this when judging public Mac WeChat dual-open tutorials.

## Common Tutorial Pattern

Most reliable-looking posts use this core method:

```bash
cp -R /Applications/WeChat.app ~/Applications/WeChat-2.app
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.tencent.xin2" ~/Applications/WeChat-2.app/Contents/Info.plist
codesign --force --deep --sign - ~/Applications/WeChat-2.app
```

Using `~/Applications` avoids `sudo` and keeps the copied app user-owned. The agent stops after preparation; the user opens the copied app manually because the agent must never launch or control WeChat.

## Verdict

Rate this approach roughly `6.5/10` to `7/10`:

- Works in practice on many macOS WeChat versions.
- Does not inject code or install a third-party tweak.
- Is easy to inspect and undo.
- Is not guaranteed across WeChat or macOS updates.

## Known Tradeoffs

- Updating WeChat can break the copy. Recopy, reapply bundle id, and re-sign, then have the user manually reopen it.
- Push notifications may be unreliable because APNs and entitlements are tied to the original app identity.
- Login state and keychain entries are isolated by bundle id.
- `codesign --force --deep --sign -` replaces the vendor signature with an ad-hoc signature. This is acceptable for a local copy but can fail if WeChat adds stricter signature checks.
- Tutorials that require downgrading or locking a specific WeChat version are less future-proof and can miss security updates.
- Third-party tweak/injection tools are higher risk than this copy-and-sign method.
- Social posts that require commenting to receive an "one-click script" are unnecessary; the underlying operations are simple.

## Recommended Response

When the user asks whether a social post is reliable, say:

- The mechanism is real: macOS and app data containers distinguish apps by bundle id.
- It is not official and not permanent.
- Prefer doing the steps manually or with a local audited script.
- Avoid downgrading unless the current version fails.
- Avoid third-party injection tools unless the user explicitly accepts that risk.

## Troubleshooting Notes

- If the copy opens in English, write language preference:
  `defaults write com.tencent.xin2 AppleLanguages -array zh-Hans en`
- If Finder or Dock shows a green icon after replacement, check all icon locations: outer `AppIcon.icns`, embedded `WeChatAppEx.app/.../app.icns`, `CFBundleIconName`, Finder custom icon, and icon caches.
- If Dock still shows the old icon after Finder is blue, quit the second WeChat and reopen it. Dock may show the icon captured at process start.
