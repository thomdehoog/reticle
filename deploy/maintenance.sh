#!/bin/sh
# Run one of the application's housekeeping commands inside the installation.
#
#   deploy/maintenance.sh purge-orphans --dry-run    # show what would be removed
#   deploy/maintenance.sh purge-orphans              # remove it
#   deploy/maintenance.sh --help                     # what the release installed here offers
#
# `purge-orphans` deletes uploaded files that nothing refers to any more,
# expired sessions and sign-in attempts, and cached PDFs of versions that are
# no longer current. Without it the data volume only ever grows.
#
# This script adds nothing of its own: every argument is handed to
# `python -m app.maintenance` unchanged, so the options are whatever that
# command documents (`--help`), not what this comment remembers. It works
# with the site running (the usual case) and with it stopped.
#
# Deleting is not undoable — except from a backup. deploy/systemd has a
# weekly timer for this which runs well after the nightly backup, for that
# reason; if you run it by hand before a big clean-up, take a backup first.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
set -eu

# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname -- "$0")/lib.sh"

[ "$#" -gt 0 ] || set -- --help

in_app python -m app.maintenance "$@" </dev/null
