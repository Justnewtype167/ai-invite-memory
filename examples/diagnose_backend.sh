#!/usr/bin/env bash
# Which Python backend is 爱邀 running, and where does it keep data?
#
# Read-only. Paste-run on the Tencent Cloud box:
#
#     bash diagnose_backend.sh
#
# It answers the three questions the memory bridge needs: which Python, which
# framework, which directory. Nothing is installed, nothing is written.
set -u

say() { printf "\n== %s ==\n" "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

say "host"
uname -a 2>/dev/null || true
[ -r /etc/os-release ] && . /etc/os-release && echo "distro: ${PRETTY_NAME:-unknown}"
echo "date: $(date -Is 2>/dev/null)"

say "python interpreters"
for py in python3 python; do
  if have "$py"; then printf "%-8s %s (%s)\n" "$py" "$($py -V 2>&1)" "$(command -v $py)"; fi
done
ls -d /opt/*/venv /srv/*/venv /root/*/venv /home/*/*/venv 2>/dev/null || true

say "python services (systemd)"
if have systemctl; then
  systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null \
    | awk '{print $1}' | while read -r unit; do
        exec_start=$(systemctl show -p ExecStart --value "$unit" 2>/dev/null || true)
        case "$exec_start" in
          *python*|*uvicorn*|*gunicorn*) printf "%-40s %s\n" "$unit" "$exec_start" ;;
        esac
      done
fi

say "python processes (pid user cwd cmdline)"
if have ps; then
  ps -eo pid=,user=,args= 2>/dev/null | grep -E "python|uvicorn|gunicorn|hypercorn|daphne" | grep -v grep | while read -r pid user rest; do
    cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || echo "?")
    printf "%-7s %-10s %s\n            cwd: %s\n" "$pid" "$user" "${rest:0:140}" "$cwd"
  done
fi

say "listening ports"
if have ss; then ss -ltnp 2>/dev/null | head -20; elif have netstat; then netstat -ltnp 2>/dev/null | head -20; fi

say "web framework in each venv"
for venv in /opt/*/venv /srv/*/venv /root/*/venv /home/*/*/venv; do
  [ -x "$venv/bin/pip" ] || continue
  echo "-- $venv"
  "$venv/bin/pip" freeze 2>/dev/null \
    | grep -Ei "^(fastapi|flask|django|starlette|uvicorn|gunicorn|hypercorn|daphne|tornado|sanic|aiohttp|litestar|quart)==" \
    || echo "   (no web framework in this venv)"
done

say "entry points near the app cwd"
for dir in /opt /srv /root /home/*; do
  find "$dir" -maxdepth 4 \( -name manage.py -o -name app.py -o -name main.py -o -name wsgi.py -o -name asgi.py \) \
    -not -path "*/site-packages/*" -not -path "*/node_modules/*" 2>/dev/null | head -10
done

say "databases and caches"
ps -eo args= 2>/dev/null | grep -E "mysqld|postgres|mongod|redis-server" | grep -v grep | head -5 || true
if have ss; then ss -ltn 2>/dev/null | grep -E ":(3306|5432|27017|6379) " || echo "   (none of 3306/5432/27017/6379 listening here)"; fi

say "disk and the likely store root"
df -h / /var /opt 2>/dev/null | head -6
for path in /var/lib/aiinvite/users /var/lib/aiinvite/stores /opt/aiinvite; do
  if [ -e "$path" ]; then ls -ld "$path"; fi
done

say "what this means"
cat <<'EOF'
  * One py process per port + pip freeze shows fastapi/flask  -> library embed:
      import AiyaoMemory in that app (docs/DEPLOY-TENCENT.md §12).
  * No framework in the venv, or the chat path is not Python     -> start with the
      bridge as a separate worker process and call it over JSON.
  * One store dir per (user, character) -> AIINVITE_ROOT must live on the local
      cloud disk (CBS/CVM), not on an NFS/COS mount: the engine needs byte-range
      appends, mtime_ns and flock (see §13 in the deploy doc).
EOF
