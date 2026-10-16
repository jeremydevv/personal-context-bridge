#!/bin/sh
set -eu
umask 077

[ "$(uname -s)" = Darwin ] || { echo 'Build the native adapters on macOS.' >&2; exit 1; }
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DESTINATION=${1:-"$HOME/.local/share/personal-context-bridge/native-pim"}
case "$DESTINATION" in /*) ;; *) echo 'An absolute private destination is required.' >&2; exit 1 ;; esac
mkdir -p "$DESTINATION"
STAGING=$(mktemp -d "$DESTINATION/.build.XXXXXX")
trap 'rm -rf "$STAGING"' EXIT HUP INT TERM
swiftc -swift-version 5 -parse-as-library "$SOURCE_DIR/apple_pim_native.swift" -o "$STAGING/calendar-cli"
clang -fobjc-arc -F/System/Library/PrivateFrameworks -framework Foundation -framework CoreGraphics -framework ImageIO -framework PDFKit -framework ReminderKit \
    "$SOURCE_DIR/apple_reminder_private.m" -o "$STAGING/reminderkit-helper"
clang -fobjc-arc -framework Foundation -framework CoreGraphics -framework EventKit -framework ImageIO -framework PDFKit \
    "$SOURCE_DIR/apple_calendar_private.m" -o "$STAGING/eventkit-helper"
cp "$STAGING/calendar-cli" "$STAGING/reminder-cli"
chmod 700 "$STAGING/calendar-cli" "$STAGING/reminder-cli" "$STAGING/reminderkit-helper" "$STAGING/eventkit-helper"
for BINARY in calendar-cli reminder-cli reminderkit-helper eventkit-helper; do
    mv "$STAGING/$BINARY" "$DESTINATION/$BINARY"
done
echo "Native adapters built in $DESTINATION"
