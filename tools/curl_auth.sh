# curl_auth.sh — sourced by the curl-based tools/*.sh scripts, never run directly.
#
# Credentials passed as `curl -u user:token` or `-H "Authorization: …"` sit in the
# process's argv, which any local user can read with `ps` while the call runs.
# These helpers print a curl config instead; pass it with process substitution so
# the secret only travels through a pipe:
#
#   curl -K <(curl_basic_auth "$EMAIL" "$TOKEN") …
#   curl -K <(curl_bearer_auth "$TOKEN") …
#
# printf is a bash builtin and $(…) forks without exec, so nothing here puts the
# secret in an argv either.

_curl_cfg_quote() {
  local v=$1
  v=${v//\\/\\\\}
  v=${v//\"/\\\"}
  printf '"%s"' "$v"
}

curl_basic_auth() {
  printf 'user = %s\n' "$(_curl_cfg_quote "$1:$2")"
}

curl_bearer_auth() {
  printf 'header = %s\n' "$(_curl_cfg_quote "Authorization: Bearer $1")"
}
