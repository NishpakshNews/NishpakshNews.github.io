"""Check every feed in config/feeds.yaml and report how many items it returns.

    python -m nishpaksh.tools.check_feeds
"""
from nishpaksh.config import load_yaml
from nishpaksh.ingest import fetch_article, fetch_feed


def main() -> None:
    for f in load_yaml("feeds.yaml")["feeds"]:
        try:
            entries = fetch_feed(f)
            sample = fetch_article(entries[0]["url"]) if entries else None
            body = len((sample or {}).get("text") or "")
            tag = f" [{f['lane']}]" if f.get("lane") else ""
            print(f"OK   {f['name'] + tag:34s} {len(entries):3d} items; first article text {body} chars  {f['url']}")
        except Exception as e:  # noqa: BLE001
            tag = f" [{f['lane']}]" if f.get("lane") else ""
            print(f"FAIL {f['name'] + tag:34s} {str(e)[:90]}  {f['url']}")


if __name__ == "__main__":
    main()
