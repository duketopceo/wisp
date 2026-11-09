---
name: postman
description: Postman - collections, requests, environments, send and inspect responses. Use for teaching API testing tasks in Postman.
tier: safe
app_classes: postman
asks: How do I send a request; How do I add a header; How do I switch environments
provenance: authored: wisp seed, 2026-11-08
---
# postman

## Teaching

### Where things live
- Left: collections, environments and history. Center: the request builder with the method, URL, and tabs for Params, Headers and Body. Bottom: the response.
- The environment selector sits at the top right.

### First steps
- Pick the method, type the URL, then press the Send button.
- Open the Headers tab under the URL to add a key and value.
- Pick an environment at the top right; variables appear as double curly braces in the URL.
- The response area has Body, Headers and Test Results tabs.

### Pitfalls
- A request that works in one environment may fail in another because a variable is unset; check the environment selector first.
