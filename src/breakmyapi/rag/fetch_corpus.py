"""Download the RAG corpus: the documents listed in corpus/sources.yaml.

Run from the project folder:  uv run python -m breakmyapi.rag.fetch_corpus
Files that are already downloaded are skipped, so it is safe to run again after a failure.
"""

import sys
import time
from pathlib import Path

import httpx
import yaml

from breakmyapi.checks import CHECKS

CORPUS_DIR = Path("corpus")
RAW_DIR = CORPUS_DIR / "raw"
MAX_ATTEMPTS = 3


def load_sources() -> list[dict]:
    text = (CORPUS_DIR / "sources.yaml").read_text(encoding="utf-8")
    sources = yaml.safe_load(text)["sources"]
    for source in sources:
        unknown = set(source["tags"]) - set(CHECKS)
        if unknown:
            raise ValueError(f"{source['id']}: unknown tags {sorted(unknown)}")
    return sources


def get_text(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()  # turn 4xx / 5xx answers into errors
    return response.text


def download(client: httpx.Client, url: str) -> str:
    """Fetch one file. Retry a few times, waiting longer after each failure."""
    for attempt in range(1, MAX_ATTEMPTS):
        try:
            return get_text(client, url)
        except httpx.HTTPError as e:
            wait = 2**attempt
            print(f"    attempt {attempt} failed ({type(e).__name__}), retrying in {wait}s")
            time.sleep(wait)
    return get_text(client, url)  # last attempt: if this fails too, the error goes to the caller


def main() -> None:
    sources = load_sources()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    downloaded, skipped, failed = 0, 0, []

    with httpx.Client(timeout=httpx.Timeout(60, connect=15)) as client:
        for source in sources:
            target = RAW_DIR / f"{source['id']}.md"
            if target.exists() and target.stat().st_size > 0:
                skipped += 1
                continue

            print(f"downloading {source['id']} ...")
            try:
                text = download(client, source["raw"])
            except httpx.HTTPError as e:
                print(f"    FAILED: {e}")
                failed.append(source["id"])
                continue

            # Write to a temporary file first, then rename: a download that is cut off
            # halfway can never be mistaken for a complete file.
            partial = target.with_suffix(".part")
            partial.write_text(text, encoding="utf-8", newline="")
            partial.replace(target)
            downloaded += 1

    print(f"\n{downloaded} downloaded, {skipped} already present, {len(failed)} failed")
    if failed:
        sys.exit(f"failed: {', '.join(failed)} (run again to retry only these)")


if __name__ == "__main__":
    main()
