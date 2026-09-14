"""Human-readable docs (summary + description) for stream-service RPC subjects,
merged into the gateway's OpenAPI by the export script. Keyed by RPC subject.
Prose only — types live in openapi_schemas.py. The gateway appends the RPC subject
footer itself.
"""

from __future__ import annotations

DOCS: dict[str, dict] = {
    "rpc.stream.tournament_streams": {
        "summary": "Get tournament streams",
        "description": (
            "Permission: public; no authentication required (identity is optional and only used for "
            "visibility). Returns the tournament's stream block: official broadcast links from its typed links "
            "(included whether or not they are on air) and the participant channels that are live "
            "right now. A hidden tournament answers 404 for an ineligible viewer. Twitch "
            "channels report live true/false; YouTube and other hosts report live null, meaning "
            "there is no live detection for them rather than offline. A participant entry carries "
            "the player behind the channel together with the team they play for in this tournament; "
            "that team is null until rosters are drafted, and the player itself is null on an "
            "official broadcast, which belongs to the organizer rather than to any participant."
        ),
    },
    "rpc.stream.repoll": {
        "summary": "Re-poll tournament streams",
        "description": (
            "Permission: workspace `stream.update` on the workspace that owns the tournament. "
            "Clears the live-status poll cursor so the next scheduler heartbeat polls immediately "
            "(202 Accepted — no poll runs inline). The call is recorded in the audit log."
        ),
    },
    "rpc.stream.health": {
        "summary": "Stream poller health",
        "description": (
            "Permission: global `stream.read`. Outcome of the last Twitch live-status poll tick next to the "
            "config that produced it: status, when it ran, how many tournaments and channels it covered, how "
            "many channels were live, and Twitch's remaining rate-limit budget. Exists because the tick "
            "swallows every Helix failure by design so an outage cannot kill the scheduler — without this a "
            "poller rejected by Twitch is indistinguishable from a working one. A null status means "
            "no tick has been recorded yet, which is not the same as a recorded failure. The grant is "
            "global rather than workspace-scoped because there is one poller for the whole platform, so the "
            "numbers carry no workspace dimension and a workspace-scoped grant is not enough."
        ),
    },
}
