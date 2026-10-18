# Market Detective

Purpose: help a curious investor investigate how a market event might travel across assets.
The first version explains mechanisms, evidence and counterfactuals. It does not predict prices or recommend trades.

The primary interaction is selecting a connection in a transmission map, reading its evidence, then challenging it.
All episodes are illustrative. Source documents support mechanisms, not a claim that an invented episode occurred.

Design contract: a cool, light investigation desk, with a left case index, a large central transmission map and a
right evidence notebook. Navy ink (#192943), cloud (#f2f5fa), white (#ffffff), blue (#365ee8), amber (#a96316)
and muted slate (#62718a) have explicit roles. Avenir Next/system sans carries the interface; Georgia is reserved
for the large editorial headline. One expressive graph earns the visual emphasis. No decorative market tickers.
On small screens the case selector becomes horizontal, the graph can scroll within its labelled frame and the
evidence notebook moves below it. Controls remain keyboard accessible, and motion respects reduced preference.

Finish condition: working case switching, evidence selection, source links, a reversible challenged-link state,
responsive desktop/mobile screenshots, graph/content validation, and a deployed issue-to-PR-to-Pages example.

Delivery: ordinary issues update the visible backlog. A maintainer-approved structured case issue can be handled
by a deterministic content worker that changes one JSON file and opens a PR. This worker makes zero model calls.
It is a bounded baseline for the agent kit, not a claim that an autonomous LLM has implemented arbitrary tickets.
The local-only inference/controller choice stays in force. New code features remain reviewable engineering work.
