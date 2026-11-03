#!/bin/bash
# Run on raptor. Logs in to the appliance as cloudsupport and changes the coordinator memory settings via sudo (root).
# Host and cloudsupport password are read from /root/machines_info.json (private_ip of appnode1, custom_variables.cloudsupport_pwd).
#
# Usage: ./memory_fix_coordinator.sh [--host IP] [--appliance NAME] [--app-id ID] [--xm SIZE] [--max-memory-per-node SIZE] [--local]
#   --local  skip SSH and apply the change on the machine where the script runs (must be the appliance itself)

set -u

MACHINES_INFO="/root/machines_info.json"
APPLIANCE="appnode1"
HOST=""
APP_ID="b567fe34-ae50-4ffe-9d05-4b5319997309"
XM_SIZE="28G"
QUERY_MAX_MEMORY_PER_NODE="26GB"
LOCAL=0

while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST="$2"; shift 2 ;;
        --appliance) APPLIANCE="$2"; shift 2 ;;
        --app-id) APP_ID="$2"; shift 2 ;;
        --xm) XM_SIZE="$2"; shift 2 ;;
        --max-memory-per-node) QUERY_MAX_MEMORY_PER_NODE="$2"; shift 2 ;;
        --local) LOCAL=1; shift ;;
        *) echo "ERROR: unknown argument: $1" >&2; exit 1 ;;
    esac
done

apply_fix() {
    local app_id="$1" xm_size="$2" max_mem="$3"
    local coordinator_dir="/var/IBM/Guardium/applications/${app_id}/runtime/coordinator"
    local jvm_config="${coordinator_dir}/jvm.config-server"
    local config_properties="${coordinator_dir}/config.properties"
    local sudo_cmd="sudo"
    [ "$(id -u)" -eq 0 ] && sudo_cmd=""

    echo "Host: $(hostname)"

    local f
    for f in "$jvm_config" "$config_properties"; do
        if ! $sudo_cmd test -f "$f"; then
            echo "ERROR: file not found: $f" >&2
            return 1
        fi
    done

    local ts
    ts="$(date +%Y%m%d_%H%M%S)"
    for f in "$jvm_config" "$config_properties"; do
        $sudo_cmd cp -p "$f" "${f}.bak_${ts}" || { echo "ERROR: backup of $f failed" >&2; return 1; }
        echo "Backup: ${f}.bak_${ts}"
    done

    set_line() {
        local file="$1" key_regex="$2" new_line="$3"
        if $sudo_cmd grep -Eq "^${key_regex}" "$file"; then
            $sudo_cmd sed -i -E "s|^${key_regex}.*$|${new_line}|" "$file"
        else
            echo "WARN: ${key_regex} not found in ${file}, appending" >&2
            echo "$new_line" | $sudo_cmd tee -a "$file" > /dev/null
        fi
    }

    set_line "$jvm_config" "-Xmx" "-Xmx${xm_size}"
    set_line "$jvm_config" "-Xms" "-Xms${xm_size}"
    set_line "$config_properties" "query\.max-memory-per-node=" "query.max-memory-per-node=${max_mem}"

    echo "--- ${jvm_config}"
    $sudo_cmd grep -E "^-Xm[xs]" "$jvm_config"
    echo "--- ${config_properties}"
    $sudo_cmd grep -E "^query\.max-memory" "$config_properties"

    local ok=1
    $sudo_cmd grep -qx -- "-Xmx${xm_size}" "$jvm_config" || ok=0
    $sudo_cmd grep -qx -- "-Xms${xm_size}" "$jvm_config" || ok=0
    $sudo_cmd grep -qx -- "query.max-memory-per-node=${max_mem}" "$config_properties" || ok=0
    if [ "$ok" -ne 1 ]; then
        echo "ERROR: verification failed" >&2
        return 1
    fi

    echo "OK: memory settings updated (restart of the coordinator is not performed by this script)"
}

if [ "$LOCAL" -eq 1 ]; then
    apply_fix "$APP_ID" "$XM_SIZE" "$QUERY_MAX_MEMORY_PER_NODE"
    exit $?
fi

if [ ! -f "$MACHINES_INFO" ]; then
    echo "ERROR: $MACHINES_INFO not found (use --host and set CLOUDSUPPORT_PWD, or --local)" >&2
    exit 1
fi

read_json() {
    python3 - "$MACHINES_INFO" "$APPLIANCE" "$1" <<'PY'
import json, sys
path, appliance, what = sys.argv[1:4]
data = json.load(open(path))
if what == "pwd":
    print(data.get("custom_variables", {}).get("cloudsupport_pwd", ""))
else:
    for m in data.get("machines", []):
        if m.get("name", "").split("-")[0] == appliance:
            print(m.get("private_ip") or m.get("public_ip") or "")
            break
PY
}

[ -z "$HOST" ] && HOST="$(read_json host)"
PASSWORD="${CLOUDSUPPORT_PWD:-$(read_json pwd)}"

if [ -z "$HOST" ]; then
    echo "ERROR: cannot determine IP of ${APPLIANCE} from ${MACHINES_INFO}" >&2
    exit 1
fi
if [ -z "$PASSWORD" ]; then
    echo "ERROR: cloudsupport_pwd not found in ${MACHINES_INFO}" >&2
    exit 1
fi

SSH_OPTS=(-p 22 -o ConnectTimeout=30 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR
          -o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive)
REMOTE_SCRIPT="$(declare -f apply_fix); apply_fix '${APP_ID}' '${XM_SIZE}' '${QUERY_MAX_MEMORY_PER_NODE}'"

echo "Connecting to ${APPLIANCE} (${HOST}) as cloudsupport"

if command -v sshpass > /dev/null 2>&1; then
    SSHPASS="$PASSWORD" sshpass -e ssh "${SSH_OPTS[@]}" "cloudsupport@${HOST}" 'bash -s' <<< "$REMOTE_SCRIPT"
    exit $?
fi

ASKPASS="$(mktemp)"
trap 'rm -f "$ASKPASS"' EXIT
printf '#!/bin/sh\necho "$CLOUDSUPPORT_PWD_ASKPASS"\n' > "$ASKPASS"
chmod 700 "$ASKPASS"
CLOUDSUPPORT_PWD_ASKPASS="$PASSWORD" SSH_ASKPASS="$ASKPASS" SSH_ASKPASS_REQUIRE=force DISPLAY="${DISPLAY:-dummy:0}" \
    setsid -w ssh "${SSH_OPTS[@]}" "cloudsupport@${HOST}" 'bash -s' <<< "$REMOTE_SCRIPT"
exit $?
