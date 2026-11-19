# Real-Debrid to pyLoad

Watches your Real-Debrid account. When a torrent finishes on Real-Debrid, the app
unrestricts its links and sends them to your pyLoad instance as a package (named
after the torrent), which starts downloading straight away.

## Setup

1. Get your API token from <https://real-debrid.com/apitoken>. (The app uses this
   token rather than your Real-Debrid password.)
2. In the app's **Configuration** tab, fill in the token and your pyLoad URL,
   username and password.
3. Start the app and watch the **Log** tab. You should see
   `Connected to Real-Debrid as <you>`.

## How it decides what to send

- Only torrents with status **downloaded** on Real-Debrid are sent.
- Each torrent is sent once. Sent torrent IDs are stored in `/data/processed.json`.
- With **Skip existing torrents on first run** on (the default), anything already
  finished when the app first starts is ignored, so you don't flood pyLoad with your
  whole history. Turn it off *before the first start* if you do want that.
- If any link of a torrent fails to unrestrict, the whole torrent is retried on the
  next check instead of being sent half-complete.

To re-send everything from scratch, stop the app, delete `processed.json` via the
Samba/SSH app (it lives in the app's data folder), and start it again.

## Sorting TV shows and films

With **Sort into TV / Movies folders** on, the app guesses from the release name:

| Release name | Saved to |
| --- | --- |
| `The.Bear.S02E05.1080p.WEB.h264-GROUP` | `TV Shows/The Bear/Season 02` |
| `Severance.S01.COMPLETE.2160p` | `TV Shows/Severance/Season 01` |
| `Show.Name.Complete.Series.1080p` | `TV Shows/Show Name` |
| `Dune.Part.Two.2024.2160p.BluRay.x265` | `Movies/Dune Part Two (2024)` |
| no video files, or not recognised | `Other/<release name>` |

It looks for episode/season markers (`S01E02`, `1x02`, `S01`, `Season 1`,
`Complete Series`) for TV, and a year or quality tags (`1080p`, `BluRay`...) for
films. If the torrent's name gives no clue, it checks the individual file names.
The Log tab shows which way each download was sorted.

**Current pyload-ng only allows one folder level**, and it replaces spaces and
other special characters with `_`. So with pyload-ng you get `TV_Shows/` and
`Movies/` (with each release's files inside), not the show/season subfolders
above. Use folder names without spaces (e.g. `TV`) to avoid the underscores. Plex,
Jellyfin and Emby all cope with this layout, because they read the show, season
and year from the file names.

Folders are **relative to pyLoad's download folder** (pyLoad → Settings → General →
Download folder). pyLoad's **"Create folder for each package"** setting must be on
(it is by default), otherwise pyLoad ignores package folders.

## Home Assistant sensor

The app keeps `sensor.realdebrid_pyload` up to date. Its state is `ok`, `error` or
`not configured`, with attributes such as `last_sent`, `last_sent_at`,
`sent_total`, `torrents_on_rd`, `last_check` and `error`. You can use it in
automations, e.g. to send a phone notification when `last_sent` changes.

Note: the sensor is recreated by the app and won't survive a Home Assistant
restart until the next check runs.

## pyLoad compatibility

- **Current pyload-ng:** its API only accepts an **API key** (starts with `pl_`),
  not a username/password. Create one in pyLoad's web interface and put it in
  **pyLoad API key**. The key's user must be an admin, or have the Add and Modify
  permissions.
- **Older pyload-ng / classic pyLoad 0.4.x:** leave the API key blank and use the
  username and password.

Links go to the **Queue**, so pyLoad starts downloading immediately.
