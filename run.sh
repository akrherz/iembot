#!/bin/sh
# Starts the IEMBot Process, run from ldm's crontab

if [ -e iembot.pid ]; then
	kill -9 `cat iembot.pid `
	sleep 5
fi
twistd --logfile=logs/iembot.log --pidfile=iembot.pid -y iembot.tac
