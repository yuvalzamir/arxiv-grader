import sys
sys.path.insert(0, '/opt/arxiv-grader')

import feedparser
from scrapers.sources import _fetch_rss_via_flaresolverr

test_urls = [
    ('Tandfonline', 'https://www.tandfonline.com/feed/rss/upcp20'),
    ('Sage',        'https://journals.sagepub.com/action/showFeed?ui-bandeau-element=journalFeed&type=etoc&feed=rss&jc=gasa'),
    ('Wiley',       'https://onlinelibrary.wiley.com/feed/21928614/most-recent'),
    ('Chicago JoP', 'https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jop'),
]

for name, url in test_urls:
    result = _fetch_rss_via_flaresolverr(url)
    if not result:
        print(f"{name}: FAILED — None returned")
        continue
    feed = feedparser.parse(result)
    print(f"{name}: {len(feed.entries)} entries, bozo={feed.bozo}")
    if feed.entries:
        print(f"  first: {getattr(feed.entries[0], 'title', '?')[:80]}")
