#!/bin/sh

if [ -e iembot.pid ]; then
    kill -INT "$(cat iembot.pid)"
    sleep 5
    if [ -e iembot.pid ]; then
        echo 'IEMBot still alive? kill -9 this time'
        kill -9 "$(cat iembot.pid)"
        sleep 1
        rm -f iembot.pid
    fi
fi
if [ "$(whoami)" = "akrherz" ]; then
    echo "Setting custom SSL_CERT_FILE"
    export SSL_CERT_FILE=/etc/pki/ca-trust/extracted/openssl/ca-bundle.trust.crt
fi

python -m iembot.main run --logfile=- "$@"
