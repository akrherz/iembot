#!/bin/sh

#export PATH=/mesonet/python-2.4/bin:$PATH

kill -9 `cat iembot.pid `
sleep 5
twistd --logfile=logs/iembot.log --pidfile=iembot.pid -y iembot-public.tac
