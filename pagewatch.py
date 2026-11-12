# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json

# Watch lifecycle: PENDING -> INTACT <-> CHANGED (anyone can re-check), or RETIRED (owner stops it)
PENDING, INTACT, CHANGED, RETIRED = "PENDING", "INTACT", "CHANGED", "RETIRED"
MAX_URL = 300
MAX_PHRASE = 200
MIN_PHRASE = 8
MAX_PAGE = 200000
MAX_CHECKS = 30
MAX_WATCHES_PER_OWNER = 20
MAX_HISTORY = 10
MAX_FEED = 20


def url_problem(url: str) -> str:
    """Reason the URL is not acceptable, or '' if fine. Validators fetch it, so
    only public https pages are allowed."""
    if not url.startswith("https://"):
        return "url must start with https://"
    if len(url) > MAX_URL:
        return "url is too long (max 300 characters)"
    if " " in url or "\n" in url or "\t" in url:
        return "url must not contain spaces"
    host = url[len("https://"):]
    for sep in ("/", "?", "#"):
        host = host.split(sep)[0]
    if host == "":
        return "url has no host"
    if "@" in host or host.startswith("["):
        return "url must not contain credentials or IPv6 literals"
    host = host.split(":")[0].lower()
    if host == "" or "." not in host:
        return "url host must be a public domain name"
    if host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        return "url host must be public"
    parts = host.split(".")
    if all(p.isdigit() for p in parts):
        nums = [int(p) for p in parts]
        a, b = nums[0], nums[1] if len(nums) > 1 else 0
        if (a in (0, 10, 127) or (a == 169 and b == 254) or (a == 192 and b == 168)
                or (a == 172 and 16 <= b <= 31)):
            return "url host must be public"
    return ""

def norm(text: str) -> str:
    """Lowercase and collapse all whitespace, so layout changes do not count as edits."""
    return " ".join(str(text).lower().split())


def phrase_present(page: str, phrase: str) -> bool:
    return norm(phrase) in norm(str(page)[:MAX_PAGE])


class PageWatch(gl.Contract):
    watches: TreeMap[u256, str]      # watch_id -> JSON record
    by_owner: TreeMap[str, str]      # owner address (lowercase) -> JSON list of ids
    next_id: u256

    def __init__(self):
        self.next_id = u256(1)

    # ---------- helpers ----------
    def _sender(self) -> str:
        return gl.message.sender_address.as_hex.lower()

    def _load(self, watch_id: int) -> dict:
        raw = self.watches.get(u256(watch_id))
        if raw is None:
            raise Exception("watch not found")
        return json.loads(raw)

    def _save(self, watch_id: int, rec: dict):
        self.watches[u256(watch_id)] = json.dumps(rec)

    def _owner_ids(self, owner: str) -> list:
        raw = self.by_owner.get(owner.lower())
        return json.loads(raw) if raw else []

    def _fetch(self, url: str, phrase: str) -> str:
        """Every validator fetches the page itself and returns YES / NO / ERR.
        The answer must match exactly (strict_eq)."""
        def check() -> str:
            try:
                text = gl.nondet.web.render(url, mode="text")
            except Exception:
                return "ERR"
            return "YES" if phrase_present(text, phrase) else "NO"
        out = gl.eq_principle.strict_eq(check)
        return out if out in ("YES", "NO", "ERR") else "ERR"

    # ---------- lifecycle ----------
    @gl.public.write
    def register(self, url: str, phrase: str) -> int:
        url = url.strip()
        phrase = " ".join(phrase.split())
        problem = url_problem(url)
        if problem:
            raise Exception(problem)
        if not (MIN_PHRASE <= len(phrase) <= MAX_PHRASE):
            raise Exception("phrase must be 8-200 characters")
        owner = self._sender()
        ids = self._owner_ids(owner)
        if len(ids) >= MAX_WATCHES_PER_OWNER:
            raise Exception("watch limit reached for this wallet")
        for wid in ids:
            old = self._load(wid)
            if old["url"] == url and norm(old["phrase"]) == norm(phrase) and old["status"] != RETIRED:
                raise Exception("you already watch this phrase on this page")
        watch_id = int(self.next_id)
        self.next_id = u256(watch_id + 1)
        self._save(watch_id, {
            "id": watch_id, "owner": owner, "url": url, "phrase": phrase,
            "status": PENDING, "checks": 0, "last_result": "", "history": [],
        })
        ids.append(watch_id)
        self.by_owner[owner] = json.dumps(ids)
        return watch_id

    @gl.public.write
    def confirm_baseline(self, watch_id: int):
        """Owner proves the phrase is on the page today. Only then does watching start."""
        rec = self._load(watch_id)
        if self._sender() != rec["owner"]:
            raise Exception("only the owner can confirm the baseline")
        if rec["status"] != PENDING:
            raise Exception("baseline already confirmed or watch retired")
        if rec["checks"] >= MAX_CHECKS:
            raise Exception("too many checks on this watch")
        result = self._fetch(rec["url"], rec["phrase"])
        rec["checks"] += 1
        if result == "YES":
            rec["status"] = INTACT
            rec["last_result"] = "INTACT"
            rec["history"] = [{"n": rec["checks"], "result": "INTACT"}]
        elif result == "NO":
            rec["last_result"] = "NOT_PRESENT"
        else:
            rec["last_result"] = "UNREACHABLE"
        self._save(watch_id, rec)

    @gl.public.write
    def recheck(self, watch_id: int):
        """Anyone can ask validators to look at the page again."""
        rec = self._load(watch_id)
        if rec["status"] not in (INTACT, CHANGED):
            raise Exception("watch is " + rec["status"] + ", nothing to re-check")
        if rec["checks"] >= MAX_CHECKS:
            raise Exception("this watch reached its check limit")
        result = self._fetch(rec["url"], rec["phrase"])
        rec["checks"] += 1
        if result == "ERR":
            rec["last_result"] = "UNREACHABLE"
        else:
            new_status = INTACT if result == "YES" else CHANGED
            rec["status"] = new_status
            rec["last_result"] = new_status
            hist = list(rec["history"])
            hist.append({"n": rec["checks"], "result": new_status})
            rec["history"] = hist[-MAX_HISTORY:]
        self._save(watch_id, rec)

    @gl.public.write
    def retire(self, watch_id: int):
        rec = self._load(watch_id)
        if self._sender() != rec["owner"]:
            raise Exception("only the owner can retire a watch")
        if rec["status"] == RETIRED:
            raise Exception("already retired")
        rec["status"] = RETIRED
        self._save(watch_id, rec)

    # ---------- composable read API ----------
    @gl.public.view
    def get_watch(self, watch_id: int) -> str:
        return json.dumps(self._load(watch_id))

    @gl.public.view
    def get_watches_by_owner(self, owner: str) -> str:
        out = []
        for wid in self._owner_ids(owner):
            w = self._load(wid)
            out.append({"id": w["id"], "url": w["url"], "phrase": w["phrase"], "status": w["status"]})
        return json.dumps(out)

    @gl.public.view
    def get_recent(self, limit: int) -> str:
        n = limit if 1 <= limit <= MAX_FEED else MAX_FEED
        out = []
        wid = int(self.next_id) - 1
        while wid >= 1 and len(out) < n:
            w = self._load(wid)
            out.append({"id": w["id"], "owner": w["owner"], "url": w["url"],
                        "phrase": w["phrase"], "status": w["status"]})
            wid -= 1
        return json.dumps(out)

    @gl.public.view
    def is_intact(self, watch_id: int) -> bool:
        return self._load(watch_id)["status"] == INTACT
