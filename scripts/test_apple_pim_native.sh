#!/bin/sh
# Compile and run only in-memory EventKit tests. No authorization, reads or saves.
set -eu
umask 077
[ "$(uname -s)" = Darwin ] || { echo 'Native tests require macOS.' >&2; exit 1; }
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TASK_PIM_TEST_DIR=$(mktemp -d "${TMPDIR:-/tmp}/pim-native-tests.XXXXXX")
trap 'rm -rf "$TASK_PIM_TEST_DIR"' EXIT HUP INT TERM
swiftc -swift-version 5 -parse-as-library -D APPLE_PIM_TESTS \
    "$SOURCE_DIR/apple_pim_native.swift" "$SOURCE_DIR/apple_pim_native_tests.swift" \
    -o "$TASK_PIM_TEST_DIR/native-tests"
TZ=America/New_York "$TASK_PIM_TEST_DIR/native-tests"
