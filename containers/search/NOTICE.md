# Chromium seccomp profile

Derived from Microsoft Playwright v1.64.1, Apache-2.0 (LICENSE.playwright):
https://raw.githubusercontent.com/microsoft/playwright/v1.64.1/utils/docker/seccomp_profile.json

Upstream SHA-256: cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849.

Local change (2026-11-27): permit chroot at the seccomp layer for Chromium's user namespace sandbox while retaining cap_drop ALL. Kernel capability checks still apply. All other rules and default-deny remain. Only the crawler uses this profile; other services use Docker defaults.

https://github.com/chromium/chromium/blob/main/sandbox/linux/README.md
