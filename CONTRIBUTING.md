# Contributing to DragonBench

DragonBench is characterization infrastructure, so changes should favor explicit,
reviewable behavior over clever shortcuts.

## Naming

Identifiers should carry domain meaning. Prefer names that say what a value is in
the DragonBench domain rather than its type, position, or a role-free abbreviation.

Avoid names such as `a`, `b`, `c`, `tmp`, or `data` when a meaningful
name is available. Conventional short loop indices and obvious counters are fine
when their scope is tiny and their meaning is unambiguous.

Examples:

- `suffix_len`, not `a`
- `device_id_len`, not `b`
- `ssid_len`, not `c`
- `retry_count` is clearer than `count` when more than one counter exists
