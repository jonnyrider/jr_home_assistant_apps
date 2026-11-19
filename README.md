# Personal Home Assistant apps

## Real-Debrid to pyLoad (`realdebrid_pyload/`)

Sends finished Real-Debrid torrents to a self-hosted pyLoad as direct download links.
See [realdebrid_pyload/DOCS.md](realdebrid_pyload/DOCS.md).

## Installing

**Option A: local app (no GitHub needed)**

1. Install the **Samba share** or **Advanced SSH & Web Terminal** app in Home Assistant.
2. Copy the `realdebrid_pyload` folder into the `/addons` share, so you have
   `/addons/realdebrid_pyload/config.yaml`.
3. **Settings → Apps → App store → ⋮ → Check for updates.** It appears under
   **Local apps**. Install, configure, start.

**Option B: your own repository**

1. Push this folder to a GitHub repo and set the `url` in `repository.yaml`
   and `realdebrid_pyload/config.yaml`.
2. **Settings → Apps → App store → ⋮ → Repositories**, add the repo URL.

When you change the code, bump `version` in `config.yaml` and rebuild/update the app.
