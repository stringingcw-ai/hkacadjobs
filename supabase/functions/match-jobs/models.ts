// What each Claude model supports and costs. The model is chosen with the MATCH_MODEL secret.

import type { TokenUsage } from "./types.ts";

/** US$ per million input / output tokens (Anthropic API list prices). */
const PRICES: Record<string, [number, number]> = {
  "claude-sonnet-5-5": [2, 10],
  "claude-sonnet-5": [2, 10],
  "claude-sonnet-4-6": [3, 15],
  "claude-opus-5-5": [4, 20],
  "claude-opus-5": [5, 25],
  "claude-opus-4-8": [5, 25],
  "claude-opus-4-7": [5, 25],
  "claude-opus-4-6": [5, 25],
  "claude-haiku-4-5": [1, 5],
  "claude-fable-5-1": [10, 50],
};
/** Unknown models are costed at the top price, so the daily budget errs on the safe side. */
const UNKNOWN_PRICE: [number, number] = [10, 50];

export function costUsd(model: string, usage: TokenUsage): number {
  const [input, output] = PRICES[model] ?? UNKNOWN_PRICE;
  const usd = (usage.input * input + usage.cacheWrite * input * 1.25 + usage.cacheRead * input * 0.1 +
    usage.output * output) / 1e6;
  return Math.round(usd * 1e5) / 1e5;
}

/** `output_config.effort` is rejected by Haiku 4.5 and Sonnet 4.5. */
export function supportsEffort(model: string): boolean {
  return /^claude-(opus-(5|4-[5-8])|sonnet-(5|4-6)|fable|mythos)/.test(model);
}

/** Web fetch with dynamic filtering needs a 4.6-or-later Opus/Sonnet; older models use the basic tool. */
export function usesDynamicWebFetch(model: string): boolean {
  return /^claude-(opus-(5|4-[678])|sonnet-(5|4-6)|fable)/.test(model);
}

/**
 * Models whose requests opt into server-side refusal fallback (`fallbacks: "default"`),
 * as Anthropic recommends for them.
 */
export function supportsServerFallback(model: string): boolean {
  return ["claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"].includes(model);
}
