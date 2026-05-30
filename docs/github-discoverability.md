# GitHub Discoverability Reference

This document records the public GitHub metadata and content contract used to keep News Sentry discoverable, understandable, and credible.

## Repository Description

Use this GitHub About description:

```text
Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows.
```

## Homepage

Use the README entry point until a dedicated project site exists:

```text
https://github.com/XucroYuri/NewsSentry#readme
```

## Topics

Recommended topics:

```text
ai
news
osint
intelligence
monitoring
journalism
media-monitoring
public-opinion
social-media-monitoring
multilingual
event-graph
research-tool
python
fastapi
rss
docker
```

## Core Search Phrases

The README files and project metadata should keep these phrases visible:

- AI news intelligence
- OSINT monitoring platform
- multilingual news
- social media monitoring
- public opinion monitoring
- source health
- canonical event graph
- professional research workflows
- human-in-the-loop research

## GitHub CLI Update Commands

Run these commands after README and metadata changes are merged:

```bash
gh repo edit XucroYuri/NewsSentry \
  --description "Open-source AI news intelligence and OSINT monitoring platform for multilingual news, social media, canonical event graphs, and research workflows." \
  --homepage "https://github.com/XucroYuri/NewsSentry#readme" \
  --enable-issues=true \
  --enable-wiki=true \
  --enable-discussions=true

gh repo edit XucroYuri/NewsSentry \
  --add-topic ai \
  --add-topic news \
  --add-topic osint \
  --add-topic intelligence \
  --add-topic monitoring \
  --add-topic journalism \
  --add-topic media-monitoring \
  --add-topic public-opinion \
  --add-topic social-media-monitoring \
  --add-topic multilingual \
  --add-topic event-graph \
  --add-topic research-tool \
  --add-topic python \
  --add-topic fastapi \
  --add-topic rss \
  --add-topic docker

gh repo view XucroYuri/NewsSentry \
  --json description,homepageUrl,repositoryTopics,hasDiscussionsEnabled,hasIssuesEnabled,hasWikiEnabled
```

If GitHub CLI reports an unsupported option for topics, update topics from the GitHub web UI using the same list above.

## Maintenance Rules

- Do not claim global cloud coverage until the cloud cluster exists.
- Do not publish artificial star, user, download, or performance numbers.
- Keep current capabilities and roadmap separate.
- Keep English README optimized for global developer search.
- Keep Chinese README useful for local professional users and long-term product direction.
- Do not commit `.env`, runtime data, `.omx`, browser profiles, logs, tokens, cookies, or local source credentials.
