# EchoGraph

EchoGraph builds a knowledge graph that follows the currently visible chat timeline. Local desktop chat and the SillyTavern plugin share `src/timeline/` for graph versions, extraction, retrieval, and manual edits.

## Entry points

- `run_ui.py`: desktop chat, graph, and configuration. Local chat uses `TimelineEngine`; Tavern mode displays the plugin chat through the backend timeline API.
- `api_server.py`: timeline HTTP API and desktop status controls. It is started by the desktop when needed.
- `E:\GitHub\echograph-sillytavern-plugin/index.js`: the SillyTavern adapter. It sends the full visible chat to `/timeline/sync`, supplies base data, and gets prompt context.

The local graph is stored under `data/local_conversations/timeline/`. Tavern timelines are stored under `data/tavern_timeline/`. Existing character data is left on disk but is no longer read by the active flow.

## Development

Use the EchoGraph Python environment to run `python -m pytest tests`. Plugin checks run with `node --check index.js` and `node --test`. See `docs/requirements/timeline-graph.md` for the timeline contract.
