#!/bin/bash
# Alias de Reparar_Vibesbot.command (misma reparación, nombre antiguo).
set -e
TMP="$(mktemp -d)"
curl -fsSL -o "$TMP/Reparar_Vibesbot.command" \
  "https://raw.githubusercontent.com/knull66/Vibesbot/main/Reparar_Vibesbot.command"
chmod +x "$TMP/Reparar_Vibesbot.command"
exec "$TMP/Reparar_Vibesbot.command"
