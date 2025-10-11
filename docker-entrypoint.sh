#!/bin/sh

echo "Setting umask to ${UMASK}"
umask ${UMASK}
echo "Creating download directory (${DOWNLOAD_DIR}), state directory (${STATE_DIR}), and temp dir (${TEMP_DIR})"
mkdir -p "${DOWNLOAD_DIR}" "${STATE_DIR}" "${TEMP_DIR}"

if [ `id -u` -eq 0 ] && [ `id -g` -eq 0 ]; then
    if [ "${UID}" -eq 0 ]; then
        echo "Warning: it is not recommended to run as root user, please check your setting of the UID environment variable"
    fi
    echo "Changing ownership of download and state directories to ${UID}:${GID}"
    chown -R "${UID}":"${GID}" /app "${DOWNLOAD_DIR}" "${STATE_DIR}" "${TEMP_DIR}"
    echo "Running MeTubeEX as user ${UID}:${GID}"
    exec gosu "${UID}":"${GID}" python3 app/main.py
else
    echo "User set by docker; running MeTubeEX as `id -u`:`id -g`"
    exec python3 app/main.py
fi
