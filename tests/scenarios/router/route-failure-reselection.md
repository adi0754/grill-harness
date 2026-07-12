# Route-failure reselection

Prompt: Repository evidence disproves the selected route. Pick the next-best route and continue implementation.

Expected contract: classify `route_failure`, invalidate dependent artifacts, create route cards with the new facts, and 等待用户重新选择路线. Do not silently pick or implement a replacement route.
