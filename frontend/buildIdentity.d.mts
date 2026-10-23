import type { Plugin } from "vite";
export interface BuildIdentity {
  service: string;
  git_sha: string | null;
  source_state: string;
  identity_scope: string;
}
export function captureBuildIdentity(root: string): Promise<BuildIdentity>;
export function buildIdentityPlugin(identity: BuildIdentity): Plugin;
