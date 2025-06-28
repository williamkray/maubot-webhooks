#!/usr/bin/env bash

docker run --rm \
  -v "$PWD"/data:/data \
  -v "$PWD":/opt/webhookbot \
  --user $UID:$GID \
  --name webhookbot \
  dock.mau.dev/maubot/maubot:standalone \
  python3 -m maubot.standalone \
    -m /opt/webhookbot/maubot.yaml \
    -c /data/config.yaml \
    -b /opt/webhookbot/example-standalone-config.yaml

