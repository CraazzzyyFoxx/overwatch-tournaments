# Twitch Service

Placeholder service for Twitch integration.

> **Status: inactive.** This service is not part of the active runtime stack and is not started by the
> default or `workers` Docker Compose profiles. It exists as scaffolding for a future Twitch integration
> (e.g. stream status, live tournament overlays tied to [Anakq's Twitch](https://www.twitch.tv/anakq)).

When the integration is implemented, this README should be updated with its port, entry points, and
configuration. Until then there is nothing to run here.

## Configuration & environment

A `backend/env/twitch.env` template can inherit `backend/env/common.env` once the service is activated.
