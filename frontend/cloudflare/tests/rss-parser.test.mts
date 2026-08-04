import assert from "node:assert/strict";
import { test } from "node:test";
import { parseFeed, type ParsedFeed } from "../workers/lib/collect/rss-parser.ts";

const RSS = `<?xml version="1.0"?><rss version="2.0"><channel>
  <title>Sample Feed</title><link>https://ex.com/</link>
  <item><title>Alpha story</title><link>https://ex.com/a</link>
    <description>Alpha body</description><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate><guid>a-1</guid></item>
  <item><title>Beta</title><link>https://ex.com/b</link><description>Beta body</description>
    <pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate><guid>b-2</guid></item>
</channel></rss>`;
const ATOM = `<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title><link href="https://ex2.com/"/>
  <entry><title>Gamma</title><link href="https://ex2.com/g"/>
    <summary>Gamma body</summary><published>2024-01-03T00:00:00Z</published><id>g-3</id></entry>
</feed>`;

test("parseFeed extracts RSS 2.0 channel + items", () => {
  const f = parseFeed(RSS);
  assert.equal(f.title, "Sample Feed");
  assert.equal(f.entries.length, 2);
  assert.equal(f.entries[0].title, "Alpha story");
  assert.equal(f.entries[0].link, "https://ex.com/a");
  assert.equal(f.entries[0].content, "Alpha body");
  assert.equal(f.entries[0].guid, "a-1");
  assert.ok(f.entries[0].published_at.length > 0);
});
test("parseFeed extracts Atom feed + entries (summary, published, id)", () => {
  const f = parseFeed(ATOM);
  assert.equal(f.title, "Atom Feed");
  assert.equal(f.entries.length, 1);
  assert.equal(f.entries[0].title, "Gamma");
  assert.equal(f.entries[0].content, "Gamma body");
  assert.equal(f.entries[0].guid, "g-3");
});
test("parseFeed returns empty feed on non-feed XML", () => {
  assert.deepEqual(parseFeed("<html></html>"), { title: "", link: "", entries: [] });
});
