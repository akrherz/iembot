<!-- markdownlint-configure-file {"MD024": { "siblings_only": true } } -->
# Changelog

All notable changes to this library are documented in this file.

## **0.4.0** (23 Feb 2026)

### API Changes

- Move `safe_twitter_text` to a more appropriate location in `iembot.util`.
- Remove `purge_logs` functionality as it is better left to end users to
  implement with tooling like `tmpwatch` or log archival (#167).
- Refactored webhooks database schema and loading.
- Replace `python-twitter` dep with stdlib python code.
- Substancial refactor to support `iembot_social_log` persistence of
  responses to messages IEMBot sends to various services (#182).
- Update `twitter.tweet_cb` signature to remove unused ``room`` argument.

### New Features

- Better handling of Twitter/X status 403 errors (#156).
- Improved atmosphere test coverage and added `pytest-timeout` dev dep (#159).
- Improved ATmosphere handling of a common `InvokeTimeoutError` (#168).

### Bug Fixes

- Correct Mastodon message routing (#150).
- Correct Mastodon oauth authorization reset (#169).
- Correct handling of Twitter 401s Unauthorized (#154).
- Fix thread-safely of embedded `pymemcache` client (#148).
- Handle ATmosphere HTTP 500+ errors more gracefully (#183).
- Handle Mastodon API Errors more gracefully (#175).
- Handle Twitter HTTP 500+ errors more gracefully (#171).
- Implement ATmosphere/bluesky media upload again (#144).
- Implement webhooks route registration (#165).
- Improve mastodon coverage and error handling (#161, #177, #180).
- Improve Twitter/X error 403 duplicate content error handling (#163).
- Removed unnecessary `pwd` (UNIX only) module usage (#142).
- Trim logs generated when Twitter/X API results in HTML response (#173).

## **0.3.1** (4 Feb 2026)

### API Changes

- Replace `txyam2` dependency with `pymemcache` called from a thread (#140).

### New Features

### Bug Fixes

- Correct slack subscription logic when a new channel is joined (#136).

## **0.3.0** (4 Feb 2026)

First sane release of this code base onto pypi and hopefully conda-forge.
