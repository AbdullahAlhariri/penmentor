#!/bin/bash
# Map two Wacom pad buttons to penmentor's --ask bindings (see i3.conf). Start it from your i3 config:
#   exec --no-startup-id ~/src/penmentor/contrib/wacom.sh
# Bluetooth tablets forget their mapping when they reconnect, so this re-applies it whenever it was reset.
PAD="Wacom Intuos BT M Pad pad"  # yours: xsetwacom --list devices
while sleep 3; do
  [[ $(xsetwacom get "$PAD" Button 1 2>/dev/null) == button* ]] || continue
  xsetwacom set "$PAD" Button 1 "key +alt +ctrl +shift m -shift -ctrl -alt"  # did I make any mistakes?
  xsetwacom set "$PAD" Button 2 "key +alt +ctrl +shift s -shift -ctrl -alt"  # solution check
done
