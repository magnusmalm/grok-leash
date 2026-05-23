#!/bin/bash
# Grok PreToolUse hook: read-file-guard.sh
#
# Prevents pathological repeated small reads of the same files (the classic
# runaway subagent pattern).
#
# Features:
# - Default hard cap of 42 reads per file per session (Elon's favorite number)
# - Counter resets when the file is modified (mtime check)
# - Both hard cap and warning threshold are configurable
# - Small-limit protection on source files

set -euo pipefail

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.toolName // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.toolInput.file_path // empty')
LIMIT=$(echo "$INPUT" | jq -r '.toolInput.limit // 0')
OFFSET=$(echo "$INPUT" | jq -r '.toolInput.offset // 0')
SESSION_ID=$(echo "$INPUT" | jq -r '.sessionId // "unknown"')

# Only care about read_file
if [[ "$TOOL_NAME" != "read_file" ]]; then
    echo '{"decision": "allow"}'
    exit 0
fi

COUNT_FILE="/tmp/grok-read-counts.${SESSION_ID}.txt"
mkdir -p "$(dirname "$COUNT_FILE")"

# Normalize path
NORM_PATH=$(realpath -m "$FILE_PATH" 2>/dev/null || echo "$FILE_PATH")

# Get current mtime of the file (if it exists)
CURRENT_MTIME=$(stat -c %Y "$NORM_PATH" 2>/dev/null || echo 0)

# State format: path|count|last_mtime
ENTRY=$(grep "^${NORM_PATH}|" "$COUNT_FILE" 2>/dev/null || echo "")

if [[ -n "$ENTRY" ]]; then
    IFS='|' read -r _ OLD_COUNT OLD_MTIME <<< "$ENTRY"

    if [[ "$CURRENT_MTIME" -gt "$OLD_MTIME" ]]; then
        # File was modified since last read → reset counter
        COUNT=1
    else
        COUNT=$((OLD_COUNT + 1))
    fi
else
    COUNT=1
fi

# Persist new state
grep -v "^${NORM_PATH}|" "$COUNT_FILE" > "${COUNT_FILE}.tmp" 2>/dev/null || true
echo "${NORM_PATH}|${COUNT}|${CURRENT_MTIME}" >> "${COUNT_FILE}.tmp"
mv "${COUNT_FILE}.tmp" "$COUNT_FILE"

# === Configuration ===

load_config_value() {
    local key="$1"
    local default="$2"
    local config_file="$HOME/.config/grok-leash/config.toml"

    if [[ -f "$config_file" ]]; then
        local val
        val=$(grep -E "^\s*${key}\s*=" "$config_file" 2>/dev/null | tail -1 | cut -d'=' -f2 | tr -d ' "')
        if [[ "$val" =~ ^[0-9]+$ ]]; then
            echo "$val"
            return
        fi
    fi
    echo "$default"
}

HARD_CAP=$(load_config_value "read_file_hard_cap" 42)
WARNING_THRESHOLD=$(load_config_value "read_file_warning_threshold" $(( HARD_CAP / 2 )) )

# === Policy ===

# 1. Block very small reads on source files (the original pathology)
if [[ "$LIMIT" -gt 0 && "$LIMIT" -lt 30 ]]; then
    if echo "$NORM_PATH" | grep -qE '\.(c|h|cc|cpp|rs|go|py|ts|tsx|js|jsx|java|scala)$'; then
        echo '{"decision": "deny", "reason": "Tiny read_file limit (<30) on source file. Use limit >= 50 or prefer grep first. This guard prevents runaway reading loops."}' 
        exit 2
    fi
fi

# 2. Hard cap on repeated reads of the same file
if [[ $COUNT -gt $HARD_CAP ]]; then
    echo '{"decision": "deny", "reason": "Too many repeated reads of the same file in this session ($COUNT > $HARD_CAP). Use grep, summarize to MEMORY.md, or ask the user for guidance. The limit resets when the file is modified."}' 
    exit 2
fi

# 3. Soft warning
if [[ $COUNT -gt $WARNING_THRESHOLD ]]; then
    echo "WARNING: $COUNT reads of $NORM_PATH in this session (hard cap is $HARD_CAP, warning at $WARNING_THRESHOLD). Consider using grep or increasing limit." >&2
fi

echo '{"decision": "allow"}'
exit 0
