# IEMBOT

[![Docs](https://readthedocs.org/projects/iembot/badge/?version=latest)](https://readthedocs.org/projects/iembot/)
[![Build Status](https://github.com/akrherz/iembot/workflows/Install%20and%20Test/badge.svg)](https://github.com/akrherz/iembot)
[![Code Health](https://landscape.io/github/akrherz/iembot/master/landscape.svg?style=flat)](https://landscape.io/github/akrherz/iembot/master)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/akrherz/iembot/main.svg)](https://results.pre-commit.ci/latest/github/akrherz/iembot/main)

I am a XMPP client with limited bot capabilities.  In general, I am a message
router more than anything.  Currently requires python 3.11+.

## Run iembot in development

Place the `src` folder within your `PYTHONPATH` and then `python -m iembot.main run ...`

## Run iembot in production

Well, don't.  If you do, then the CLI is available `iembot run ...`

## Command line options

Option | Shortname | Default | Doc
--- | --- | --- | --
`--disable-atmosphere` | - | `False` | Disable Atmosphere message posting
`--disable-mastodon` | - | `False` | Disable Mastodon message posting
`--disable-slack` | - | `False` | Disable Slack message posting
`--disable-twitter` | - | `False` | Disable Twitter message posting
`--logfile` | `-l` | `logs/iembot.log` | Where to log to, `-` does stdout only
