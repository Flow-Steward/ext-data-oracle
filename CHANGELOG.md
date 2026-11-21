# Changelog

## 1.1.13 - 2026-11-21

- Refresh the reviewed Toolbox Go dependency lock and rebuild both Linux runtime targets.

## 1.1.12

- Rebuild Linux AMD64 and ARM64 native payloads with grpc-gateway v2.34.0 and its required indirect modules on the pinned Toolbox v1.17.0 and verified Go 1.27.4 baseline.
- Preserve the existing connector controls, approved profiles and dependency security fixes.

## 1.1.11 - 2026-11-15

### Added

- Added a Support tab with links for reporting a problem, asking a question or requesting a feature in this extension's GitHub repository, and what to include in a report.

## 1.1.10 - 2026-11-14

- Declare extension host contract 1.5.0 for the artifact-free service descriptor, so current hosts can install the release. Workflow action IDs, inputs, outputs and provider behavior are unchanged.

## 1.1.9

- Rebuild Linux AMD64 and ARM64 native payloads with google.golang.org/api v0.315.0 on the pinned Toolbox v1.17.0 and verified Go 1.27.4 baseline.
- Preserve the other selected dependency versions, connector controls and approved profiles; reject the superseded Google API module during package verification.


## 1.1.8

- Refresh Toolbox to v1.17.0 and the reviewed dependency lock; build both native targets in CI while preserving connector safety and profile restrictions.

## 1.1.7

- Clarify workflow action names, descriptions and field help; add setup and input examples. Existing action IDs, input schemas and runtime behavior are preserved.

