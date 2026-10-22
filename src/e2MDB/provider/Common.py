# Shared by all providers (also in shell mode), the backend daemon and the GUI.
# It must not import Enigma2 or other e2MDB modules.
from html import unescape
from re import IGNORECASE, search, sub


class Fields:
	PROVIDER = "provider"
	# Common fields
	TITLE = "title"
	ORIGINAL_TITLE = "original_title"
	YEAR = "year"
	IMDB_ID = "imdb_id"
	MEDIA_TYPE = "media_type"
	RELEASED = "released"
	AGE_RATING = "age_rating"
	GENRES = "genres"
	COUNTRIES = "countries"
	OVERVIEW = "overview"
	RUNTIME = "runtime"

	VOTE_AVERAGE = "vote_average"
	VOTE_COUNT = "vote_count"

	COVER_URL = "cover_url"
	COVER_SRC = "cover_src"
	BACKDROP_URL = "backdrop_url"
	BACKDROP_SRC = "backdrop_src"
	TITLELOGO_URL = "titlelogo_url"
	TITLELOGO_SRC = "titlelogo_src"
	LAST_UPDATED = "last_updated"
	PROVIDER_IDS = "provider_ids"

	# Movie-specific fields
	DIRECTORS = "directors"
	WRITERS = "writers"
	ACTORS = "actors"

	# TV show-specific fields
	SEASONS = "seasons"
	SERIES_ID = "series_id"
	SEASON_NO = "season_no"
	SEASON_NAME = "season_name"
	EPISODE_NO = "episode_no"
	EPISODE_ID = "episode_id"
	EPISODE_NAME = "episode_name"

	# ACTORS and CREW
	CREW = "crew"
	CAST = "cast"
	JOB = "job"
	NAME = "name"
	CHARACTER = "character"
	PROFILE_ID = "profile_id"
	PROFILE_URL = "profile_url"

	# Additional fields
	TAGLINE = "tagline"
	ORIGINAL_LANGUAGE = "original_language"


TS_RECORDING_EXTS = (".ts", ".stream")
MEDIA_FILE_EXTS = (".mkv", ".avi", ".mp4", ".m4v", ".mpg", ".mpeg", ".mov", ".wmv", ".flv", ".iso", ".m2ts", ".mts")
VIDEO_EXTS = TS_RECORDING_EXTS + MEDIA_FILE_EXTS
EXCLUDED_DIRS = ("__pycache__", "@eaDir", "lost+found", "scan", ".scan", "trash", ".trash", "Trash", ".Trash", ".Trash-1000", "trashcan", ".trashcan")
CACHE_DIRS = ("data", "index", "series", "seasons", "backdrop", "cover", "titlelogo", "image", "preview", "fanart", "fernsehserien", "wikimedia", "wikipedia", "results")

# default provider order and state, the user settings may override it
SERIES_SEARCH_ORDER = {"tvdb": True, "tmdb": True, "tvmaze": False, "cinemeta": False, "anime": False, "kitsu": False, "omdb": True, "imdb": False}
MOVIE_SEARCH_ORDER = {"tmdb": True, "cinemeta": False, "anime": False, "kitsu": False, "tvdb": True, "omdb": True, "imdb": False}

# possible separators 'title|episodename' (separator, replacement), the order is essential!
FOREIGN_SEPAS = (("_", ""), (": ", ": "), (" – ", ""), (" - ", ""), ("! ", "! "))  # foreign recordings, e.g. '.mp4'
EPGTYPE_SEPAS = (("_", ""), (": ", ": "), (" – ", ""), (" - ", ""), ("! ", "! "), ("|", "|"), ("*", "*"))  # recordings with EPG data, e.g. EIT


def guess_separator(title, separators):  # the separator found least often wins, e.g. ('Show - Episode', SEPAS) -> (' - ', '')
	count_list = [(separator, replacement, title.count(separator)) for separator, replacement in separators if separator in title]
	return min(count_list, key=lambda x: x[2])[:2] if count_list else ("", "")


def episode_name_variants(name):  # e.g. 'Zweierlei Maß * Doku, CDN 2025' -> ['zweierlei maß doku cdn 2025', 'zweierlei maß']
	name = str(name or "").strip()
	separator = guess_separator(name, EPGTYPE_SEPAS)[0]
	parentheses = search(r"^\s*([^(\r\n]*?)\s*\(", name)  # e.g. 'Zweierlei Maß (Korean-Air-Flug 6316)' -> 'Zweierlei Maß'
	short_names = (name.split(separator)[0] if separator else "", parentheses.group(1) if parentheses else "")
	full_name = normalize_text(name)  # without punctuation, e.g. 'Dr. James Covington' -> 'dr james covington'
	return list(dict.fromkeys([full_name] + [x for x in map(normalize_text, short_names) if x]))


def match_season_episode(episode_index, episode_name="", plain_season_episode=""):
	# Find an episode in a normalized episode index {"episodes": {"1-2": ("283766", "Die Warnung"), ...}}.
	# Returns e.g. ('1-2', '283766', 'Die Warnung') or () if nothing matches.
	result = ()
	episodes = list((episode_index or {}).get("episodes", {}).items())
	if plain_season_episode:
		episode_only = str(int(plain_season_episode)) if str(plain_season_episode).isdigit() else ""
		result = next(((key, value[0], value[1]) for key, value in episodes if key == plain_season_episode), ())
		if not result and episode_only:  # absolute numbering, e.g. '12' -> '1-12'
			result = next(((key, value[0], value[1]) for key, value in episodes if key.split("-")[-1] == episode_only), ())
	elif search_names := episode_name_variants(episode_name) if str(episode_name or "").strip() else []:
		indexed = [(key, value, episode_name_variants(value[1])) for key, value in episodes]
		# exact matches first, so 'Teil 1' does not hit 'Teil 10', substrings need 5+ chars ('Anne' must not hit 'Johanne')
		result = next(((key, value[0], value[1]) for key, value, index_names in indexed if set(search_names) & set(index_names)), ())
		if not result:
			result = next(((key, value[0], value[1]) for key, value, index_names in indexed if any((len(x) >= 5 and x in y) or (len(y) >= 5 and y in x) for x in search_names for y in index_names)), ())
	return result


def safe_int(value, default=0):
	try:
		return int(value)
	except Exception:
		return default


def set_dict_key(dictionary, key, value):  # skip empty values and the 'N/A' placeholder some providers return
	if value and value != "N/A":
		dictionary[key] = value
	return dictionary


def html_to_text(html):  # e.g. '<p>Line 1<br>Line &amp; 2</p>' -> 'Line 1\nLine & 2'
	if isinstance(html, bytes):
		html = html.decode("utf-8", "replace")
	return unescape(sub(r"<br\s*/?>", "\n", sub(r"<.*?>", "", html))).strip() if html else ""


def normalize_text(value):  # e.g. 'Dr._James-Covington!' -> 'dr james covington'
	value = str(value or "").strip().lower()
	value = sub(r"[._\-]+", " ", value)
	value = sub(r"[^a-z0-9äöüß ]+", " ", value)
	return sub(r"\s+", " ", value).strip()


def image_extension(url, fallback="jpg"):  # e.g. 'https://x/poster.webp?w=500' -> 'jpg'
	match = search(r"\.(jpe?g|png|gif|webp)(?=$|[/?#_;&=,])", str(url or ""), IGNORECASE)
	extension = match.group(1).lower() if match else fallback
	return "jpg" if extension == "webp" else extension


def candidate_title_year(value):  # search candidate as (title, year), e.g. ('Mayday', ''), ['Mayday', ''] (from JSON) or 'Mayday'
	if isinstance(value, (list, tuple)):
		title, year = (list(value) + ["", ""])[:2]
	else:
		title, year = value, ""
	return str(title or "").strip(), str(year or "").strip()
