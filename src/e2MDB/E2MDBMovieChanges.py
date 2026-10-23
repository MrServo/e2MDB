from hashlib import md5
from json import dumps, loads
from os.path import basename, dirname, splitext
from time import time
from provider.Common import normalize_text


def movieRecordingId(path):
	# Keep the released scanner/cache identity algorithm when a physical path changes.
	reduced = path.replace("/media/hdd", "").replace("/media/autofs", "")
	return md5(reduced.encode("utf-8", "replace")).hexdigest()


def insertMovieRow(connection, table, values):
	columns = ", ".join(values)
	placeholders = ", ".join("?" for key in values)
	connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values()))


def applyMovieChange(connection, event):
	path = event.get("path")
	identifier = event.get("id")
	action = event.get("action")
	if not isinstance(identifier, str) or not 1 <= len(identifier) <= 64 or not isinstance(path, str) or not path.startswith("/"):
		raise ValueError("Invalid movie change identity")
	if action not in ("move", "rename", "trash", "restore", "copy", "delete", "metadata", "status"):
		raise ValueError("Unsupported movie change")
	if connection.execute("SELECT 1 FROM e2mdb_movie_changes WHERE operation_id = ?", (identifier,)).fetchone():
		return
	if action in ("move", "rename", "trash", "restore", "copy"):
		target = event.get("target")
		if not isinstance(target, str) or not target.startswith("/") or target == path:
			raise ValueError("Invalid movie change destination")
		newHash = movieRecordingId(target)
		existing = connection.execute("SELECT file_path FROM e2mdb_media WHERE hash = ?", (newHash,)).fetchone()
		if existing is not None and existing["file_path"] != target:
			raise ValueError("Movie identity collision; catalogue was left unchanged")
	row = connection.execute("SELECT * FROM e2mdb_media WHERE file_path = ?", (path,)).fetchone()
	if action == "metadata":
		identifierHash = row["hash"] if row is not None else movieRecordingId(path)
		connection.execute("INSERT OR REPLACE INTO e2mdb_movie_overrides(media_hash, title, description) VALUES (?, ?, ?)", (identifierHash, str(event.get("title", "")), str(event.get("description", ""))))
	if row is not None:
		media = dict(row)
		oldHash = media["hash"]
		recording = connection.execute("SELECT * FROM e2mdb_recordings WHERE media_hash = ? AND path = ?", (oldHash, path)).fetchone()
		if action in ("move", "rename", "trash", "restore", "copy"):
			matches = connection.execute("SELECT * FROM e2mdb_provider_matches WHERE media_hash = ?", (oldHash,)).fetchall()
			connection.execute("DELETE FROM e2mdb_provider_matches WHERE media_hash = ?", (newHash,))
			connection.execute("DELETE FROM e2mdb_recordings WHERE media_hash = ?", (newHash,))
			connection.execute("DELETE FROM e2mdb_media WHERE hash = ?", (newHash,))
			media.pop("id", None)
			media.update(hash=newHash, file_path=target, file_name=basename(target))
			insertMovieRow(connection, "e2mdb_media", media)
			if recording is not None:
				recording = dict(recording)
				payload = loads(recording["payload_json"] or "{}")
				payload.update(id=newHash, path=target, folder=dirname(target), name=basename(target), extension=splitext(target)[1])
				recording.update(recording_id=newHash, media_hash=newHash, path=target, folder=dirname(target), name=basename(target), extension=splitext(target)[1], payload_json=dumps(payload, ensure_ascii=False))
				insertMovieRow(connection, "e2mdb_recordings", recording)
			for match in matches:
				match = dict(match)
				match.pop("id", None)
				match.update(media_hash=newHash, recording_id=newHash)
				insertMovieRow(connection, "e2mdb_provider_matches", match)
			# Images may still use their original cache key; retain that key until the media is removed.
			connection.execute("INSERT OR IGNORE INTO e2mdb_movie_cache_aliases(media_hash, cache_hash) VALUES (?, ?)", (newHash, oldHash))
			connection.execute("INSERT OR IGNORE INTO e2mdb_movie_cache_aliases(media_hash, cache_hash) SELECT ?, cache_hash FROM e2mdb_movie_cache_aliases WHERE media_hash = ?", (newHash, oldHash))
			connection.execute("INSERT OR REPLACE INTO e2mdb_movie_overrides(media_hash, title, description) SELECT ?, title, description FROM e2mdb_movie_overrides WHERE media_hash = ?", (newHash, oldHash))
			if action != "copy":
				for table, column in (("e2mdb_provider_matches", "media_hash"), ("e2mdb_recordings", "media_hash"), ("e2mdb_media", "hash"), ("e2mdb_movie_cache_aliases", "media_hash"), ("e2mdb_movie_overrides", "media_hash")):
					connection.execute(f"DELETE FROM {table} WHERE {column} = ?", (oldHash,))
		elif action == "delete":
			for table, column in (("e2mdb_provider_matches", "media_hash"), ("e2mdb_recordings", "media_hash"), ("e2mdb_media", "hash"), ("e2mdb_movie_cache_aliases", "media_hash"), ("e2mdb_movie_overrides", "media_hash")):
				connection.execute(f"DELETE FROM {table} WHERE {column} = ?", (oldHash,))
		elif action == "metadata":
			title, description = str(event.get("title", "")), str(event.get("description", ""))
			connection.execute("UPDATE e2mdb_media SET metadata_title = ?, metadata_overview = ?, search_string = ?, search_string_norm = ? WHERE hash = ?", (title, description, title, normalize_text(title), oldHash))
			if recording is not None:
				payload = loads(recording["payload_json"] or "{}")
				payload.update(title=title, description=description)
				searchText = f"{title} {description}"
				connection.execute("UPDATE e2mdb_recordings SET title = ?, description = ?, search_text = ?, search_text_norm = ?, payload_json = ? WHERE media_hash = ?", (title, description, searchText, normalize_text(searchText), dumps(payload, ensure_ascii=False), oldHash))
		elif action != "status":
			raise ValueError("Unsupported movie change")
	else:
		# Manual edits can precede the first scan of a new recording.
		oldHash = movieRecordingId(path)
		if action in ("move", "rename", "trash", "restore", "copy"):
			connection.execute("INSERT OR REPLACE INTO e2mdb_movie_overrides(media_hash, title, description) SELECT ?, title, description FROM e2mdb_movie_overrides WHERE media_hash = ?", (newHash, oldHash))
		if action in ("move", "rename", "trash", "restore", "delete"):
			connection.execute("DELETE FROM e2mdb_movie_overrides WHERE media_hash = ?", (oldHash,))
	if action in ("move", "rename", "trash", "restore", "delete"):
		connection.execute("INSERT OR REPLACE INTO e2mdb_movie_paths(path, retired) VALUES (?, 1)", (path,))
	if action in ("move", "rename", "trash", "restore", "copy"):
		connection.execute("INSERT OR REPLACE INTO e2mdb_movie_paths(path, retired) VALUES (?, 0)", (event["target"],))
	connection.execute("INSERT INTO e2mdb_movie_changes(operation_id, applied_at) VALUES (?, ?)", (identifier, int(time())))


def applyMovieChanges(database, events):
	if not isinstance(events, list) or len(events) > 64 or any(not isinstance(event, dict) for event in events):
		return {"success": False, "error": "Expected at most 64 movie changes"}
	acknowledged = []
	errors = {}
	with database.lock:
		connection = database._connect()
		try:
			connection.execute("CREATE TABLE IF NOT EXISTS e2mdb_movie_changes(operation_id TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)")
			connection.execute("CREATE TABLE IF NOT EXISTS e2mdb_movie_cache_aliases(media_hash TEXT NOT NULL, cache_hash TEXT NOT NULL, PRIMARY KEY(media_hash, cache_hash))")
			connection.commit()
			for event in events:
				try:
					with connection:
						applyMovieChange(connection, event)
					acknowledged.append(event["id"])
				except Exception as error:
					errors[str(event.get("id", ""))] = str(error)
					break  # Preserve ordering: a later rename may depend on the failed change.
			with connection:
				connection.execute("DELETE FROM e2mdb_movie_changes WHERE operation_id IN (SELECT operation_id FROM e2mdb_movie_changes ORDER BY applied_at DESC, rowid DESC LIMIT -1 OFFSET 8192)")
		finally:
			connection.close()
	return {"success": True, "acknowledged": acknowledged, "errors": errors}
