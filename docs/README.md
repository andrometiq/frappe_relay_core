# Relay Core documentation

Use Core for business permissions, contacts, tickets, and automation. Use
[Relay Hub](https://github.com/andrometiq/relay_hub/tree/develop/docs) to configure
provider accounts and transport.

## Get started

Owners, managers and staff: start with the [user guide](user-guide.md).

1. [Install Core on a test Frappe site](core-installation.md).
2. [Configure authentication and permissions](authentication.md).
3. [Read and reply to a verified conversation](messaging.md).

## Guides

- [Frontend development](../frontend/README.md).
- [Run tests and understand their coverage](testing.md).
- [Resolve common setup and delivery problems](troubleshooting.md).

## Reference

- [HTTP and MCP methods](api-reference.md).
- [Data model and message flow](concepts.md).
- [Current support and release limitations](implementation-status.md).
- [DocType schemas](../relay_core/relay_core/doctype/).

## Design records

These documents capture earlier decisions or dated test checkpoints.
Their planned features and historical counts are not the current support contract:

- [Focused WhatsApp product UI/UX redesign](relay-product-ui-ux.md) and the
  detailed [business inbox interaction specification](business-inbox-ui-ux.md).
- [Original architecture](architecture.md).
- [AI automation plan](ai-automation-plan.md), [review](ai-automation-plan-review.md),
  and [2026-09-22 implementation checkpoint](ai-automation-implementation.md).
- [Frappe table research](frappe-virtualization.md).
- [Communication expansion plan](communication-expansion.md).
- [Earlier route audit](route-api-audit.md) and [UI progress](ui-progress.md).

## Documentation conventions

These guides follow the organization used by
[GoogleTest](https://google.github.io/googletest/quickstart-cmake.html) and
[Abseil](https://abseil.io/docs/cpp/quickstart-cmake.html): prerequisites, a small
working example, observable results, focused guides, and a separate API reference.
The writing follows Google's
[documentation guide](https://google.github.io/styleguide/docguide/) and
[README guidance](https://google.github.io/styleguide/docguide/READMEs.html).
Sources reviewed on 2026-09-23. Relay's examples and explanations describe this
repository; they are not copied from those projects.

Update the relevant guide with its code change. Keep one authoritative description
of each contract, link to it elsewhere, and distinguish tested behavior from plans.

- [Groups and Calls workspace](groups-and-calls-ui.md).
