"""Real-Debrid -> pyLoad bridge, run as a Home Assistant app (add-on).

Every `poll_interval` seconds:
  1. List the torrents on your Real-Debrid account.
  2. For each torrent RD has finished downloading that we haven't handled yet,
     unrestrict its hoster links into direct download links.
  3. Send those links to pyLoad as one package (named after the torrent).
  4. Remember the torrent ID so it is never sent twice; optionally delete it from RD.

Status is published to Home Assistant as sensor.realdebrid_pyload.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

from classify import classify

OPTIONS_FILE = "/data/options.json"
STATE_FILE = "/data/processed.json"
RD_API = "https://api.real-debrid.com/rest/1.0"
HA_API = "http://supervisor/core/api"
HTTP_TIMEOUT = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("rd-pyload")


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {"initialised": data.get("initialised", False),
                "processed": set(data.get("processed", []))}
    except FileNotFoundError:
        return {"initialised": False, "processed": set()}
    except (OSError, ValueError) as e:
        log.warning("Could not read state file (%s); starting fresh", e)
        return {"initialised": False, "processed": set()}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"initialised": state["initialised"],
                   "processed": sorted(state["processed"])}, f)
    os.replace(tmp, STATE_FILE)


# --------------------------------------------------------------------------- #
# Real-Debrid
# --------------------------------------------------------------------------- #
class RealDebrid:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"

    def _req(self, method, path, **kw):
        for attempt in range(3):
            r = self.s.request(method, RD_API + path, timeout=HTTP_TIMEOUT, **kw)
            if r.status_code == 429:  # rate limited (250 req/min)
                wait = 5 * (attempt + 1)
                log.warning("Real-Debrid rate limit hit, waiting %ss", wait)
                time.sleep(wait)
                continue
            if r.status_code == 401:
                raise RuntimeError("Real-Debrid rejected the API token (401). "
                                   "Check rd_api_token in the app configuration.")
            r.raise_for_status()
            return r
        r.raise_for_status()
        return r

    def user(self):
        return self._req("GET", "/user").json()

    def torrents(self):
        out, page = [], 1
        while True:
            r = self._req("GET", "/torrents", params={"page": page, "limit": 100})
            if r.status_code == 204 or not r.content:
                break
            batch = r.json()
            out.extend(batch)
            total = int(r.headers.get("X-Total-Count", len(out)))
            if not batch or len(out) >= total:
                break
            page += 1
        return out

    def unrestrict(self, link):
        return self._req("POST", "/unrestrict/link", data={"link": link}).json()

    def delete_torrent(self, torrent_id):
        self._req("DELETE", f"/torrents/delete/{torrent_id}")


# --------------------------------------------------------------------------- #
# pyLoad (works with pyload-ng and classic pyLoad 0.4.x)
# --------------------------------------------------------------------------- #
class PyLoad:
    def __init__(self, url, username, password, api_key="", verify_ssl=True):
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self.api_key = (api_key or "").strip()
        self.s = requests.Session()
        self.s.verify = verify_ssl
        self.session_id = None
        if self.api_key:
            # Current pyload-ng: API key in a header, arguments as a JSON body.
            # It does not accept username/password on the API at all.
            self.s.headers["X-API-Key"] = self.api_key

    def login(self):
        r = self.s.post(f"{self.url}/api/login",
                        data={"username": self.username, "password": self.password},
                        timeout=HTTP_TIMEOUT)
        if r.status_code in (404, 405):
            raise RuntimeError(
                "This pyLoad version does not allow logging in to its API with a "
                "username and password. Create an API key in pyLoad's web interface "
                "and put it in the app's 'pyLoad API key' setting.")
        r.raise_for_status()
        result = r.json()
        if result is False or result is None:
            raise RuntimeError("pyLoad login failed - check username/password")
        # Classic pyLoad returns a session id string; pyload-ng uses a cookie.
        self.session_id = result if isinstance(result, str) else None

    def _call(self, variants):
        """Call an API method. `variants` is a list of (method_name, params) to try
        in order, because pyload-ng and classic pyLoad name methods and arguments
        differently (add_package/addPackage, package_id/pid)."""
        if self.api_key:
            return self._call_with_key(variants)
        if self.session_id is None and not self.s.cookies:
            self.login()
        last = None
        for name, params in variants:
            # pyLoad parses each form value as a Python/JSON literal.
            data = {k: json.dumps(v) for k, v in params.items()}
            if self.session_id:
                data["session"] = self.session_id
            r = self.s.post(f"{self.url}/api/{name}", data=data, timeout=HTTP_TIMEOUT)
            if r.status_code in (401, 403):
                # Session expired - log in again once and retry.
                self.login()
                if self.session_id:
                    data["session"] = self.session_id
                r = self.s.post(f"{self.url}/api/{name}", data=data, timeout=HTTP_TIMEOUT)
            if r.status_code == 404:
                last = r
                continue
            r.raise_for_status()
            return r.json() if r.content else None
        raise RuntimeError(f"pyLoad API method not found: {[v[0] for v in variants]} "
                           f"(HTTP {last.status_code if last else '?'})")

    def _call_with_key(self, variants):
        # Only the pyload-ng spelling applies here (the first variant).
        name, params = variants[0]
        r = self.s.post(f"{self.url}/api/{name}", json=params, timeout=HTTP_TIMEOUT)
        if r.status_code == 401:
            raise RuntimeError(f"pyLoad rejected the API key (HTTP 401: "
                               f"{r.text.strip()[:200]}). Check the key, and that its "
                               f"user is an admin or has Add and Modify permissions.")
        r.raise_for_status()
        return r.json() if r.content else None

    def add_package(self, name, links, folder=None):
        """Add links as a package. With `folder`, the package is created in the
        Collector, given its folder, then moved to the Queue so no file starts
        downloading before the folder is set. Returns the package id."""
        if not folder:
            # dest=1 -> Queue (starts downloading immediately).
            return self._call([("add_package", {"name": name, "links": links, "dest": 1}),
                               ("addPackage", {"name": name, "links": links, "dest": 1})])

        pid = self._call([("add_package", {"name": name, "links": links, "dest": 0}),
                          ("addPackage", {"name": name, "links": links, "dest": 0})])
        try:
            # pyload-ng: the attribute is "_folder" ("folder" is a read-only property,
            # which is what caused HTTP 500). pyload-ng also runs it through
            # secure_filename, which flattens "a/b" into "a_b" and turns spaces into
            # underscores, so only the top-level folder (TV / Movies / Other) is used.
            ng_folder = folder.split("/")[0]
            self._call([("set_package_data", {"package_id": pid,
                                              "data": {"_folder": ng_folder}}),
                        ("setPackageData", {"pid": pid, "data": {"folder": folder}})])
            if self.api_key and ng_folder != folder:
                log.info("pyload-ng only supports one folder level; '%s' goes in '%s'",
                         name, ng_folder)
        except Exception as e:  # still download it, just into the default folder
            log.warning("Could not set pyLoad folder for '%s' (%s); "
                        "it will download to pyLoad's default folder", name, e)
        try:
            self._call([("move_package", {"destination": 1, "package_id": pid}),
                        ("movePackage", {"destination": 1, "pid": pid})])
        except Exception as e:  # don't raise: the package exists, re-adding would duplicate it
            log.error("Added '%s' to pyLoad but could not move it to the Queue (%s). "
                      "Start it from pyLoad's Collector.", name, e)
        return pid


# --------------------------------------------------------------------------- #
# Home Assistant status sensor
# --------------------------------------------------------------------------- #
def publish_status(state_value, attrs):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    try:
        requests.post(
            f"{HA_API}/states/sensor.realdebrid_pyload",
            headers={"Authorization": f"Bearer {token}"},
            json={"state": state_value,
                  "attributes": {"friendly_name": "Real-Debrid to pyLoad",
                                 "icon": "mdi:cloud-download", **attrs}},
            timeout=10,
        )
    except requests.RequestException as e:
        log.debug("Could not update HA sensor: %s", e)


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def sync_once(rd, pyload, opts, state, stats):
    torrents = rd.torrents()
    done = [t for t in torrents if t.get("status") == "downloaded"]
    stats["torrents_on_rd"] = len(torrents)

    if not state["initialised"]:
        if opts["skip_existing_on_first_run"]:
            state["processed"].update(t["id"] for t in done)
            log.info("First run: marked %d existing finished torrent(s) as already "
                     "handled. Only new ones will be sent to pyLoad.", len(done))
        state["initialised"] = True
        save_state(state)
        if opts["skip_existing_on_first_run"]:
            return

    new = [t for t in done if t["id"] not in state["processed"]]
    if new:
        log.info("%d new finished torrent(s) to send", len(new))

    for t in new:
        name = t.get("filename") or t["id"]
        links = t.get("links") or []
        if not links:
            log.warning("'%s' has no links yet, will retry next cycle", name)
            continue

        direct, filenames = [], []
        for link in links:
            try:
                info = rd.unrestrict(link)
                direct.append(info["download"])
                filenames.append(info.get("filename") or "")
            except (requests.RequestException, KeyError) as e:
                log.error("Failed to unrestrict a link for '%s': %s", name, e)
                direct = None
                break
        if not direct:
            log.warning("Skipping '%s' this cycle; will retry", name)
            continue

        folder = None
        if opts.get("sort_downloads", True):
            kind, folder = classify(name, filenames, opts)
            log.info("'%s' looks like %s -> %s", name,
                     {"tv": "a TV show", "film": "a film"}.get(kind, "neither TV nor film"),
                     folder)
        pyload.add_package(name, direct, folder)
        log.info("Sent '%s' to pyLoad (%d file(s))", name, len(direct))
        state["processed"].add(t["id"])
        save_state(state)
        stats["sent_total"] += 1
        stats["last_sent"] = name
        stats["last_sent_at"] = datetime.now(timezone.utc).isoformat()

        if opts["delete_torrent_after_send"]:
            try:
                rd.delete_torrent(t["id"])
                state["processed"].discard(t["id"])  # gone from RD, no need to remember
                save_state(state)
                log.info("Deleted '%s' from Real-Debrid", name)
            except requests.RequestException as e:
                log.warning("Could not delete '%s' from Real-Debrid: %s", name, e)

    # Forget IDs no longer on RD so the state file doesn't grow forever.
    current_ids = {t["id"] for t in torrents}
    if state["processed"] - current_ids:
        state["processed"] &= current_ids
        save_state(state)


def main():
    with open(OPTIONS_FILE, encoding="utf-8") as f:
        opts = json.load(f)

    if not opts.get("rd_api_token"):
        log.error("rd_api_token is empty. Get yours from "
                  "https://real-debrid.com/apitoken and add it in the app's Configuration tab.")
        publish_status("not configured", {})
        while True:
            time.sleep(3600)

    rd = RealDebrid(opts["rd_api_token"])
    pyload = PyLoad(opts["pyload_url"], opts.get("pyload_username", ""),
                    opts.get("pyload_password", ""), opts.get("pyload_api_key", ""),
                    opts.get("verify_ssl", True))
    state = load_state()
    stats = {"sent_total": 0, "last_sent": None, "last_sent_at": None,
             "torrents_on_rd": None}

    try:
        me = rd.user()
        log.info("Connected to Real-Debrid as %s (%s, premium until %s)",
                 me.get("username"), me.get("type"), me.get("expiration"))
    except Exception as e:  # keep running; the loop will report errors
        log.error("Real-Debrid check failed: %s", e)

    interval = int(opts.get("poll_interval", 300))
    while True:
        try:
            sync_once(rd, pyload, opts, state, stats)
            publish_status("ok", {**stats,
                                  "last_check": datetime.now(timezone.utc).isoformat()})
        except Exception as e:
            log.error("Sync failed: %s", e)
            publish_status("error", {**stats, "error": str(e),
                                     "last_check": datetime.now(timezone.utc).isoformat()})
        time.sleep(interval)


if __name__ == "__main__":
    main()
