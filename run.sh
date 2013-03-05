#!/bin/sh
# Starts the IEMBot Process, run from ldm's crontab

kill -9 `cat iembot.pid `
sleep 5
twistd --logfile=logs/iembot.log --pidfile=iembot.pid -y iembot.tac
