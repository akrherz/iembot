#!/bin/sh
# Starts the IEMBot Process, run from ldm's crontab

if [ -e iembot.pid ]; then
	kill -INT `cat iembot.pid `
	sleep 5
	if [ -e iembot.pid ]; then
		echo 'IEMBot still alive? kill -9 this time'
		kill -9 `cat iembot.pid `
		sleep 1
		rm -f iembot.pid
	fi
fi
twistd --logfile=logs/iembot.log --pidfile=iembot.pid -y iembot.tac
