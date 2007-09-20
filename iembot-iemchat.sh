#!/bin/sh

#export PATH=/mesonet/python-2.4/bin:$PATH

kill -9 `cat iembot.pid `
twistd --pidfile=iembot.pid -y iembot-iemchat.tac
