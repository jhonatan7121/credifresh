#!/bin/sh
set -eu

: "${API_BASE_URL:?Render must provide API_BASE_URL while building the static portal}"
printf 'window.CREDIFRESH_CONFIG = Object.freeze({apiBase: "%s"});\n' "$API_BASE_URL" > config.js
