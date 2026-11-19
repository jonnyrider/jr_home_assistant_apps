"""Work out whether a release is a TV show or a film from its name.

Release names follow loose conventions, e.g.
    The.Bear.S02E05.1080p.WEB.h264-GROUP      -> TV  / The Bear / Season 02
    Severance.S01.COMPLETE.2160p              -> TV  / Severance / Season 01
    Blue Planet II (2017) Season 1            -> TV  / Blue Planet II (2017) / Season 01
    Dune.Part.Two.2024.2160p.UHD.BluRay.x265  -> Film / Dune Part Two (2024)
Anything with no video files, or that can't be recognised, goes to "other".
"""

import re

VIDEO_EXT = (".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".ts", ".m2ts", ".webm", ".mpg")

_I = re.IGNORECASE
EPISODE = re.compile(r"\bS(\d{1,2})[ .-]?E\d{1,3}\b", _I)            # S01E02
CROSS_EP = re.compile(r"\b(\d{1,2})x\d{2,3}\b", _I)                  # 1x02
SEASON_RANGE = re.compile(r"\bS(\d{1,2})\s*-\s*S?\d{1,2}\b", _I)     # S01-S03
SEASON_TAG = re.compile(r"\bS(\d{1,2})\b", _I)                       # S02 (season pack)
SEASON_WORD = re.compile(r"\bSeasons?\s*(\d{1,2})\b", _I)            # Season 2
COMPLETE = re.compile(r"\b(complete\s+series|all\s+seasons|the\s+complete)\b", _I)
YEAR = re.compile(r"[\(\[]?\b(19[2-9]\d|20[0-4]\d)\b[\)\]]?")
QUALITY = re.compile(
    r"\b(2160p|1080p|720p|480p|4k|uhd|bluray|blu-ray|bdrip|brrip|web-?dl|webrip|web|"
    r"hdtv|dvdrip|remux|x264|x265|h\.?264|h\.?265|hevc|xvid|hdr|dv|proper|repack|"
    r"extended|unrated|imax|multi|dual)\b", _I)
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _normalise(name):
    name = re.sub(r"\.(mkv|mp4|avi|m4v|mov|wmv|ts|m2ts|webm|mpg)$", "", name, flags=_I)
    name = re.sub(r"^\s*\[[^\]]*\]\s*", "", name)            # leading [group] tag
    name = re.sub(r"^\s*www\.\S+\s*-?\s*", "", name, flags=_I)  # leading www.site.org -
    name = re.sub(r"[._]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _clean_title(text):
    text = re.sub(r"[\s\-\(\[\{]+$", "", text).strip(" -")
    text = INVALID_CHARS.sub("", text)
    if text.islower():
        text = text.title()
    return text.strip()


def _with_year(title):
    """'Doctor Who 2005' -> 'Doctor Who (2005)'."""
    m = re.search(r"\s[\(\[]?(19[2-9]\d|20[0-4]\d)[\)\]]?$", title)
    if m and m.start() > 0:
        return f"{title[:m.start()].strip()} ({m.group(1)})"
    return title


def _tv(name):
    """Return (show, season or None, episode tag or None) if `name` looks like TV,
    else None. The episode tag is e.g. 'S02E05'."""
    n = _normalise(name)
    for rx, has_season in ((EPISODE, True), (CROSS_EP, True), (SEASON_RANGE, False),
                           (SEASON_WORD, True), (SEASON_TAG, True), (COMPLETE, False)):
        m = rx.search(n)
        if m and m.start() > 0:
            show = _with_year(_clean_title(n[:m.start()]))
            if not show:
                continue
            season = int(m.group(1)) if has_season else None
            episode = None
            if rx is EPISODE:
                episode = re.sub(r"[ .-]", "", m.group(0)).upper()
            elif rx is CROSS_EP:
                s, e = m.group(0).lower().split("x")
                episode = f"S{int(s):02d}E{int(e):02d}"
            return show, season, episode
    return None


def _film(name):
    n = _normalise(name)
    # Use the last year that has a title in front of it ("2001 A Space Odyssey 1968").
    years = [m for m in YEAR.finditer(n) if m.start() > 0]
    if years:
        m = years[-1]
        title = _clean_title(n[:m.start()])
        if title:
            return f"{title} ({m.group(1)})"
    q = QUALITY.search(n)
    if q and q.start() > 0:
        title = _clean_title(n[:q.start()])
        if title:
            return title
    return None


def analyse(torrent_name, filenames):
    """Work out what a release is. Returns a dict with:
    kind ('tv' / 'film' / 'other'), title (readable name), and for TV: show,
    season, episode; for films: film."""
    safe_name = INVALID_CHARS.sub("", torrent_name).strip() or "Download"
    other = {"kind": "other", "title": safe_name}

    has_video = any(f.lower().endswith(VIDEO_EXT) for f in filenames) if filenames else True
    if not has_video:
        return other

    # Torrent name first, then the individual file names.
    tv = _tv(torrent_name)
    if tv is None:
        for f in filenames:
            tv = _tv(f)
            if tv:
                break
    if tv:
        show, season, episode = tv
        if episode and len(filenames) <= 1:
            title = f"{show} {episode}"              # The Bear S02E05
        elif season is not None:
            title = f"{show} Season {season}"         # The Bear Season 2
        else:
            title = show                              # The Bear
        return {"kind": "tv", "title": title, "show": show, "season": season,
                "episode": episode}

    film = _film(torrent_name)
    if film is None and len(filenames) == 1:
        film = _film(filenames[0])
    if film:
        return {"kind": "film", "title": film, "film": film}

    return other


def classify(torrent_name, filenames, opts):
    """Return (kind, folder, title). kind is 'tv', 'film' or 'other', folder is a
    path relative to pyLoad's download folder, title is a readable name such as
    'The Bear S02E05' or 'Dune Part Two (2024)'."""
    tv_root = opts.get("tv_folder", "TV Shows")
    film_root = opts.get("film_folder", "Movies")
    other_root = opts.get("other_folder", "Other")
    a = analyse(torrent_name, filenames)

    if a["kind"] == "tv":
        if not opts.get("tv_subfolders", True):
            return "tv", tv_root, a["title"]
        if a["season"] is None:
            return "tv", f"{tv_root}/{a['show']}", a["title"]
        return "tv", f"{tv_root}/{a['show']}/Season {a['season']:02d}", a["title"]

    if a["kind"] == "film":
        if not opts.get("film_subfolders", True):
            return "film", film_root, a["title"]
        return "film", f"{film_root}/{a['film']}", a["title"]

    return "other", f"{other_root}/{a['title']}", a["title"]
