# PageWatch (Intelligent Contract)

Has this page changed? PageWatch lets anyone pick a public web page and a key sentence on it (a privacy promise, a price, a rule, a terms clause). GenLayer validators confirm the sentence is on the page today. After that, **anyone** can ask the validators to re-check, and the page's **intact or changed** history is stored on-chain, readable by any contract.

Pages change quietly. A company edits its terms, a project deletes a promise, a price moves, and nobody can prove what the page said or when it changed. PageWatch makes "the page still says this" a fact that many independent validators agreed on, with a public history.

- **Contract (GenLayer Studio):** `0x14Cc462077D7Fe64B9e2a7b70EcD100a2b0b528E`
- **Contract source:** [`pagewatch.py`](./pagewatch.py)
- **Tests:** [`tests/test_pagewatch.py`](./tests/test_pagewatch.py)

## How it works

```
register(url, phrase) --> PENDING --confirm_baseline--> INTACT <--recheck--> CHANGED
                                                           |
                                          retire (owner) --+--> RETIRED
```

1. `register(url, phrase)` stores the page and a sentence of 8 to 200 characters.
2. `confirm_baseline(id)` (owner only): every validator fetches the page (`gl.nondet.web.render`) and returns `YES`, `NO` or `ERR`. They must match exactly (`gl.eq_principle.strict_eq`). On `YES` the watch becomes `INTACT`.
3. `recheck(id)` (**anyone**): validators fetch again. `YES` gives `INTACT`, `NO` gives `CHANGED`. An unreachable page changes nothing. Each result is added to the watch's history (last 10).
4. A `CHANGED` watch returns to `INTACT` if the page is restored, so the history shows both.
5. `is_intact(id)`, `get_watch(id)`, `get_watches_by_owner(owner)` and `get_recent(limit)` are the read API.

Layout does not count as an edit: capital letters and any run of spaces, tabs or line breaks are normalised before comparing. A reworded sentence does count.

## What it protects against

| Risk | How PageWatch handles it |
|---|---|
| Watching a sentence that was never on the page | The baseline must be confirmed by validators before the watch starts. |
| A flaky page flipping the status | An unreachable page is recorded as `UNREACHABLE` and never changes the status or the history. |
| Layout or capitalisation noise | Text is lowercased and whitespace collapsed before comparing. |
| Validators fetching internal addresses | Only `https` links to public hosts. `localhost`, private and link-local IPs, `.local`/`.internal`, credentials and IPv6 literals are refused. |
| Disagreement between validators | The answer is a plain `YES`/`NO`/`ERR`, so consensus is exact, with no model in the loop. |
| Spam | 30 checks per watch, 20 watches per wallet, no duplicate active watch, bounded phrase length and page size. Only the owner can confirm the baseline or retire. |

## Read API (composable)

- `get_watch(watch_id)` returns the watch as JSON, including its history
- `get_watches_by_owner(owner)` returns a wallet's watches
- `get_recent(limit)` returns the newest watches from everyone
- `is_intact(watch_id)` is `true` only while the last confirmed check found the sentence

## Tests

`tests/test_pagewatch.py` runs the contract's real logic against a small stand-in for the `genlayer` library, with the web fetch replaced by a dictionary of pages. No node is needed:

```
python3 tests/test_pagewatch.py
```

It covers link and phrase refusal, duplicates and caps, baseline rules, anyone re-checking, status following the page, layout noise, unreachable pages, the check and history caps, retiring and the read API (11 tests).

## Limits

- A watch only sees what validators fetch. Pages that need a login or build their text with scripts are not supported.
- It tracks one sentence, not the whole page, on purpose: whole pages change constantly (ads, dates) and validators could never agree.
- The contract has no clock, so history is ordered by check number, not by date.
- Studio test network only. No payments or enforcement. A web app for it lives in its own project repository.
