#!/bin/sh

#export PATH=/mesonet/python-2.4/bin:$PATH

kill -9 `cat iembot.pid `
sleep 5
twistd --pidfile=iembot.pid -y iembot-iemchat.tac
