# Pi Token Speed Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show pi-token-speed RPC footer measurements in T3 Stats for nerds.

**Architecture:** Parse the tokenSpeed status entry in the Pi adapter into a separate nullable turn field. Preserve it in both projections and display it with an approximation mark.

**Tech Stack:** TypeScript, Effect, Vitest, Python packaging, GitHub Actions.

### Task 1: RPC parsing and adapter
Create packages/provider-pi/src/server/tokenSpeed.ts and tokenSpeed.test.ts; modify adapter.ts and adapter.test.ts. Test ANSI, decimals, placeholder, clear, unrelated key, malformed values, live update and settlement. Run node_modules/.bin/vp test run packages/provider-pi/src/server/tokenSpeed.test.ts packages/provider-pi/src/server/adapter.test.ts. Start with failing tests, then implement parsing and bounded emission; preserve the latest reading at settlement.

### Task 2: Contracts and persistence
Modify packages/contracts/src/orchestrationV2.ts, apps/server/src/orchestration-v2/ProjectionStore.ts, packages/client-runtime/src/state/orchestrationV2Projection.ts and their existing tests. Add responseTokenSpeed optional/null schema with finite nonnegative tokensPerSecond and pi_token_speed_extension basis. Preserve omitted telemetry and honor explicit null clearing.

### Task 3: Stats display
Modify apps/web/src/components/chat/ComposerStats.logic.ts, ComposerStats.tsx and ComposerStats.logic.test.ts. Pi rates use only matching extension basis, reject malformed numbers and show approximation and source explanation. Existing provider tests must remain green.

### Task 4: Export and build
Commit the feature as one new source patch, export all commits against installed upstream 6524a8d43795 and add Pi checks to checks.json. Document extension installation in README.md. Run every required check and Python installer tests, push the authorized branch and dispatch checked portable build. Import with build --build-only --no-pull --bundles and verify the resulting UI archives, then package the ZIP. Applying it requires T3 to be closed by the user.
