<!-- markdownlint-configure-file {"MD024": { "siblings_only": true } } -->
# Changelog

All notable changes to this library are documented in this file.

## Unreleased Version

### API Changes

- Replace `python-twitter` dep with stdlib python code.

### New Features

- Better handling of Twitter/X status 403 errors (#156).
- Improved atmosphere test coverage and added `pytest-timeout` dev dep (#159).

### Bug Fixes

- Correct Mastodon message routing (#150).
- Correct handling of Twitter 401s Unauthorized (#154).
- Fix thread-safely of embedded `pymemcache` client (#148).
- Implement ATmosphere/bluesky media upload again (#144).
- Improve mastodon coverage and error handling (#161).
- Improve Twitter/X error 403 duplicate content error handling (#163).
- Removed unnecessary `pwd` (UNIX only) module usage (#142).

## **0.3.1** (4 Feb 2026)

### API Changes

- Replace `txyam2` dependency with `pymemcache` called from a thread (#140).

### New Features

### Bug Fixes

- Correct slack subscription logic when a new channel is joined (#136).

## **0.3.0** (4 Feb 2026)

First sane release of this code base onto pypi and hopefully conda-forge.
