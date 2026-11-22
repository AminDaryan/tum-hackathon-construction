#!/bin/sh
# A mounted volume (a Fly volume, a host directory) can be owned by root, which the app user
# cannot write. Started as root, hand the data directory to twb and drop to it; started as any
# other user, run the command as is.
set -e
if [ "$(id -u)" = 0 ]; then
    chown -R twb:twb "${TWB_DATA_DIR:-/data}"
    exec setpriv --reuid=twb --regid=twb --init-groups "$@"
fi
exec "$@"
