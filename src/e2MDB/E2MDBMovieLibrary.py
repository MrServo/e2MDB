from os.path import isabs

from .E2MDBBackendClient import E2MDBBackendClient


class E2MDBMovieLibrary:
	label = "e2MDB"
	capabilities = frozenset(("details", "browse", "members", "seasons", "changes"))

	def normalizeItem(self, item):
		def imagePath(*names):
			return next((item[name] for name in names if isinstance(item.get(name), str) and isabs(item[name])), "")

		def integerValue(value, default=None):
			try:
				number = int(value)
				return number if number >= 0 else default
			except (TypeError, ValueError, OverflowError):
				return default

		return {
			"id": str(item.get("id") or item.get("media_hash") or ""),
			"path": item.get("file_path") or "",
			"title": item.get("title") or item.get("file_name") or "",
			"description": item.get("overview") or item.get("description") or "",
			"series": item.get("series_title") or "",
			"season": integerValue(item.get("season_no")),
			"episode": integerValue(item.get("episode_no")),
			"year": str(item.get("year") or ""),
			"genres": item.get("genres") or [],
			"rating": str(item.get("vote_average") or ""),
			"votes": str(item.get("vote_count") or ""),
			"runtime": str(item.get("runtime") or ""),
			"released": str(item.get("released") or ""),
			"ageRating": str(item.get("age_rating") or ""),
			"countries": item.get("countries") or [],
			"cast": item.get("cast") or [],
			"crew": item.get("crew") or [],
			"tagline": str(item.get("tagline") or ""),
			"originalTitle": str(item.get("original_title") or ""),
			"size": integerValue(item.get("size_bytes"), 0),
			"fileSize": integerValue(item.get("size_bytes"), 0),
			"type": item.get("media_type") or "",
			"poster": imagePath("poster_path", "cover_file_path", "cover_path"),
			"backdrop": imagePath("backdrop_file_path", "backdrop_path"),
			"group": item.get("browser_key") or "",
			"pending": str(item.get("browser_ready", "")).lower() not in ("1", "true"),
			"files": item.get("files") or [],
			"duration": integerValue(item.get("duration_seconds"), 0),
			"recordedAt": integerValue(item.get("recorded_at"), 0)
		}

	def request(self, operation, parameters):
		client = E2MDBBackendClient(timeout=3.0)
		if operation == "changes":
			result = client.request("movie_changes", events=parameters["events"])
			if not result.get("success"):
				raise RuntimeError(result.get("error", "e2MDB catalogue update unavailable"))
			return result
		if operation == "details":
			result = client.request("movie_details", paths=parameters["paths"])
			if not result.get("success"):
				raise RuntimeError(result.get("error", "e2MDB details unavailable"))
			return {"items": {path: self.normalizeItem(item) for path, item in result.get("items", {}).items()}}
		if operation == "browse":
			result = client.request("movie_catalogue", **parameters)
			if not result.get("success"):
				raise RuntimeError(result.get("error", "e2MDB library unavailable"))
			return {"items": [self.normalizeItem(item) for item in result.get("items", [])], "hasMore": bool(result.get("has_more")), "indexing": bool(result.get("indexing")), "physical": bool(result.get("physical"))}
		if operation in ("members", "seasons"):
			result = client.request("movie_members", id=parameters["id"], page=parameters.get("page", 1), season=parameters.get("season"), hiddenFolders=parameters.get("hiddenFolders", []), sort=parameters.get("sort", "episode"))
			if not result.get("success"):
				raise RuntimeError(result.get("error", "e2MDB movie unavailable"))
			return {"items": [self.normalizeItem(item) for item in result.get("items", [])], "hasMore": bool(result.get("has_more")), "seasons": result.get("seasons", []), "indexing": bool(result.get("indexing"))}
		raise ValueError(f"Unsupported movie library operation: {operation}")


movieLibraryProvider = E2MDBMovieLibrary()


def registerMovieLibrary(reason):
	# Older images do not have the optional core provider interface.
	try:
		from Components.MovieLibrary import movieLibrary
	except ImportError:
		return
	if reason == 0:
		if "e2mdb" not in movieLibrary.providers:
			movieLibrary.register("e2mdb", movieLibraryProvider)
	else:
		movieLibrary.unregister("e2mdb", movieLibraryProvider)
