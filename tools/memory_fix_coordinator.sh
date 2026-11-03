#!/bin/bash
# Run on appnode1 as cloudsupport (changes are made via sudo, i.e. as root).
# Usage: ./memory_fix_coordinator.sh [APP_ID] [XM_SIZE] [QUERY_MAX_MEMORY_PER_NODE]

set -u

APP_ID="${1:-b567fe34-ae50-4ffe-9d05-4b5319997309}"
XM_SIZE="${2:-28G}"
QUERY_MAX_MEMORY_PER_NODE="${3:-26GB}"

COORDINATOR_DIR="/var/IBM/Guardium/applications/${APP_ID}/runtime/coordinator"
JVM_CONFIG="${COORDINATOR_DIR}/jvm.config-server"
CONFIG_PROPERTIES="${COORDINATOR_DIR}/config.properties"

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

for f in "$JVM_CONFIG" "$CONFIG_PROPERTIES"; do
    if ! $SUDO test -f "$f"; then
        echo "ERROR: file not found: $f" >&2
        exit 1
    fi
done

TS="$(date +%Y%m%d_%H%M%S)"

set_line() {
    # set_line <file> <key_regex> <full_new_line>
    local file="$1" key_regex="$2" new_line="$3"
    if $SUDO grep -Eq "^${key_regex}" "$file"; then
        $SUDO sed -i -E "s|^${key_regex}.*$|${new_line}|" "$file"
    else
        echo "WARN: ${key_regex} not found in ${file}, appending" >&2
        echo "$new_line" | $SUDO tee -a "$file" > /dev/null
    fi
}

for f in "$JVM_CONFIG" "$CONFIG_PROPERTIES"; do
    $SUDO cp -p "$f" "${f}.bak_${TS}" || { echo "ERROR: backup of $f failed" >&2; exit 1; }
    echo "Backup: ${f}.bak_${TS}"
done

set_line "$JVM_CONFIG" "-Xmx" "-Xmx${XM_SIZE}"
set_line "$JVM_CONFIG" "-Xms" "-Xms${XM_SIZE}"
set_line "$CONFIG_PROPERTIES" "query\.max-memory-per-node=" "query.max-memory-per-node=${QUERY_MAX_MEMORY_PER_NODE}"

echo "--- ${JVM_CONFIG}"
$SUDO grep -E "^-Xm[xs]" "$JVM_CONFIG"
echo "--- ${CONFIG_PROPERTIES}"
$SUDO grep -E "^query\.max-memory" "$CONFIG_PROPERTIES"

ok=1
$SUDO grep -qx "-Xmx${XM_SIZE}" "$JVM_CONFIG" || ok=0
$SUDO grep -qx "-Xms${XM_SIZE}" "$JVM_CONFIG" || ok=0
$SUDO grep -qx "query.max-memory-per-node=${QUERY_MAX_MEMORY_PER_NODE}" "$CONFIG_PROPERTIES" || ok=0

if [ "$ok" -ne 1 ]; then
    echo "ERROR: verification failed" >&2
    exit 1
fi

echo "OK: memory settings updated (restart of the coordinator is not performed by this script)"
