# ADR-0001: Keep the hybrid macOS architecture

- Status: accepted
- Date: 2026-09-06

APEX will continue to use an AppKit/WKWebView shell, a browser-based interface, and
a local Python/FastAPI service. This preserves mature business behavior and allows
native macOS integration where it has practical value. Native views may be added
for a proven need, but a feature is not rewritten solely to make it native.

Performance work measures the shell, WebKit, backend, and automation processes
separately. A native-shell rewrite is not treated as a substitute for profiling.

